"""Room-scoped lobby dispatch and notification fanout for one listener loop."""

import copy
import secrets
import msgpack

from prizm_lobby import (LobbyService, ready_notification, join_notification,
                         leave_notification, in_game_start_notification, character_change_notification)
from prizm_protocol import read_command_message, ProtocolError, rpc_response
from prizm_discovery import room_access
from prizm_rooms import RoomError
from prizm_battle import (BATTLE_SERVICE, load_status_request, load_status_notification,
                          create_player_request,create_player_reply,create_player_notification,
                          create_enemy_request,create_enemy_notification,
                          update_status_request,update_status_notification,
                          object_action_request,object_action_notification,
                          object_liveness_request,object_liveness_notification,
                          create_minion_request,create_minion_notification,minion_recovery_parameters_match,
                          object_effect_request,object_effect_notification,
                          game_over_request,game_over_reply,game_over_notification,game_over_confirm_reply)


class RoomService:
    def __init__(self, rooms, registry, guild_provider=None,
                 event_catalog=None, eligibility_provider=None, room_settings_provider=None,
                 room_view_provider=None, player_provider=None, connection_provider=None,
                 battle_provider=None, battle_character_provider=None, battle_enemy_provider=None,
                 battle_minion_provider=None, completion_provider=None):
        self.rooms = rooms
        self.registry = registry
        self.guild_provider = guild_provider
        self.event_catalog = event_catalog
        self.eligibility_provider = eligibility_provider
        self.room_settings_provider = room_settings_provider
        self.room_view_provider = room_view_provider
        self.player_provider = player_provider
        self.connection_provider = connection_provider
        self.battle_provider = battle_provider
        self.battle_character_provider = battle_character_provider
        self.battle_enemy_provider = battle_enemy_provider
        self.battle_minion_provider = battle_minion_provider
        self.completion_provider = completion_provider
        self.lobby = LobbyService(rooms.snapshot)
        self.connections = {}

    @staticmethod
    def _object(room, guid):
        return (room.get('PlayerObjects',{}).get(guid) or room.get('EnemyObjects',{}).get(guid)
                or room.get('MinionObjects',{}).get(guid))

    def connected(self, connection):
        if connection.registry is not self.registry:
            raise ValueError('Room service and listener must share the session registry.')
        self.connections[connection.session.session_id] = connection

    def disconnected(self, connection):
        self.connections.pop(connection.session.session_id,None)

    def broadcast(self, room, notification, exclude=None, service=1000, recipient=None,
                  reliable=True, coalesce=None):
        members = {player['UserId'] for player in room['Players']}
        for connection in list(self.connections.values()):
            admission = connection.session.admission
            if (admission.room_id == room['RoomId'] and admission.account_id in members
                    and admission.account_id != exclude
                    and (recipient is None or admission.account_id == recipient)):
                connection.notify(service,notification,reliable=reliable,coalesce=coalesce)

    def admitted(self, room, account_id):
        """Called on the listener loop after authoritative HTTP admission."""
        player = next(entry for entry in room['Players'] if entry['UserId'] == account_id)
        self.broadcast(room,join_notification(player),exclude=account_id)

    def create(self, player, *configuration, **options):
        """Admit an authenticated server-owned player; roll back failed issuance."""
        room = self.rooms.create(player,*configuration,**options)
        return self._credentials(room,player['UserId'])

    def join(self, room_id, player, version):
        room = self.rooms.join(room_id,player,version)
        admission = self._credentials(room,player['UserId'])
        self.admitted(room,player['UserId'])
        return admission

    def join_checked(self, room_id, player, version, route, episode_ids):
        """Server-authorized event scope and current guild lookup on this loop.

        guild_provider must read server data on the listener thread, not retain
        a Flask request transaction. Checks run while the room lock is held.
        """
        if (type(episode_ids) not in (tuple,list,set,frozenset)
                or any(type(value) is not str for value in episode_ids)):
            raise ValueError('Invalid authorized episode scope.')
        def allowed(room):
            return self._access(room,player['UserId'],route,episode_ids)
        room = self.rooms.join(room_id,player,version,admission_policy=allowed)
        admission = self._credentials(room,player['UserId'])
        self.admitted(room,player['UserId'])
        return admission

    def _access(self, room, account_id, route, episode_ids):
        if room['EpisodeId'] not in episode_ids:
            return False
        host = next(entry for entry in room['Players'] if entry['IsHost'])
        viewer_guild = host_guild = None
        if room['PublicLevel'] == 3:
            if self.guild_provider is None:
                return False
            viewer_guild = self.guild_provider(account_id)
            host_guild = self.guild_provider(host['UserId'])
        return room_access(room,route,viewer_guild,host_guild)

    def discover(self, account_id, episode_ids, version, route=1, event_context=None):
        if (type(account_id) is not str or not account_id
                or type(route) is not int or route not in (1,2)
                or type(version) is not str or not version
                or type(episode_ids) not in (tuple,list,set,frozenset)
                or any(type(value) is not str for value in episode_ids)):
            raise ValueError('Invalid room discovery scope.')
        return self.rooms.discover(version,
            lambda room: self._event_matches(room,event_context)
                and self._access(room,account_id,route,episode_ids),matching=route == 2)

    @staticmethod
    def _event_matches(room, context):
        return (context is None or 'EventId' not in room
                or (room['EventId'],room['Difficulty']) == context)

    def match_checked(self, player, version, episode_ids, event_context=None):
        """Select and admit without releasing the room lock between them.

        Event difficulty/power eligibility must already define episode_ids.
        No compatible candidate is an error, not a fabricated admission.
        """
        with self.rooms.lock:
            if player['UserId'] in self.rooms.memberships:
                raise RoomError('Player already admitted.')
            candidates = self.discover(player['UserId'],episode_ids,version,route=2,
                                       event_context=event_context)
            if not candidates:
                raise RoomError('No available matching room.')
            return self.join_checked(candidates[0]['RoomId'],player,version,2,episode_ids)

    def _event_scope(self, account_id, event_id, difficulty):
        if self.event_catalog is None or self.eligibility_provider is None:
            raise RoomError('Event admission is not configured.')
        eligibility = self.eligibility_provider(account_id)
        return self.event_catalog.episode_scope(event_id,difficulty,
            eligibility['Power'],eligibility['Platform'],eligibility['ClientVersion'])

    def create_event(self, player, episode_id, version, public_level):
        if (self.event_catalog is None or self.eligibility_provider is None
                or self.room_settings_provider is None):
            raise RoomError('Event creation is not configured.')
        if type(public_level) is not int or public_level not in (1,2,3):
            raise RoomError('Invalid room public level.')
        with self.rooms.lock:
            eligibility = self.eligibility_provider(player['UserId'])
            context = self.event_catalog.eligible_event(episode_id,eligibility['Power'],
                eligibility['Platform'],eligibility['ClientVersion'])
            if public_level == 3 and (self.guild_provider is None
                    or not self.guild_provider(player['UserId'])):
                raise RoomError('Guild room requires current membership.')
            settings = self.room_settings_provider(episode_id)
            room,tcp,udp = self.create(player,episode_id,version,public_level == 2,
                                      public_level,settings['Mode'],settings['SuspendLimits'])
            current = self.rooms.rooms[room['RoomId']]
            current.update(EventId=context[0],Difficulty=context[1])
            return copy.deepcopy(current),tcp,udp

    def create_http(self, account_id, episode_id, version, public_level):
        if self.player_provider is None or self.connection_provider is None:
            raise RoomError('HTTP admission is not configured.')
        player = self.player_provider(account_id)
        if player.get('UserId') != account_id:
            raise RoomError('Player provider returned a different account.')
        if self.event_catalog is not None:
            episode_id = self.event_catalog.episodes.resolve_episode(episode_id)
        room,tcp,udp = self.create_event(player,episode_id,version,public_level)
        return self._http_admission(account_id,room,tcp,udp)

    def join_http(self, account_id, room_id, version, route):
        if (self.player_provider is None or self.connection_provider is None
                or self.event_catalog is None or self.eligibility_provider is None):
            raise RoomError('HTTP admission is not configured.')
        if type(route) is not int or route not in (1,2,3):
            raise RoomError('Invalid room join route.')
        with self.rooms.lock:
            room = self.rooms.rooms.get(room_id)
            if room is None:
                raise RoomError('Room unavailable.')
            eligibility = self.eligibility_provider(account_id)
            event_id,difficulty = self.event_catalog.eligible_event(room['EpisodeId'],
                eligibility['Power'],eligibility['Platform'],eligibility['ClientVersion'])
            player = self.player_provider(account_id)
            if player.get('UserId') != account_id:
                raise RoomError('Player provider returned a different account.')
            room,tcp,udp = self.join_event(room_id,player,version,route,event_id,difficulty)
            return self._http_admission(account_id,room,tcp,udp)

    def matching_http(self, account_id, event_id, difficulty, version):
        if (self.player_provider is None or self.connection_provider is None
                or self.room_view_provider is None):
            raise RoomError('HTTP matching is not configured.')
        with self.rooms.lock:
            scope = self._event_scope(account_id,event_id,difficulty)
            if account_id in self.rooms.memberships:
                raise RoomError('Player already admitted.')
            candidates = self.discover(account_id,scope,version,route=2,
                                       event_context=(event_id,difficulty))
            response = dict(Rooms=[],Prizm=None,RetryRequest=True,RetryCount=3,RetryInterval=1000)
            if not candidates:
                return response
            player = self.player_provider(account_id)
            if player.get('UserId') != account_id:
                raise RoomError('Player provider returned a different account.')
            room,tcp,udp = self.match_checked(player,version,scope,(event_id,difficulty))
            try:
                view = self.room_view_provider(account_id,copy.deepcopy(room))
            except Exception:
                self.leave(account_id,room['RoomId'])
                raise
            response.update(self._http_admission(account_id,room,tcp,udp))
            response.update(Rooms=[view],RetryRequest=False)
            return response

    def _http_admission(self, account_id, room, tcp, udp):
        try:
            connection = self.connection_provider(copy.deepcopy(room),tcp,udp)
            if (type(connection) is not dict or connection.get('RoomId') != room['RoomId']
                    or connection.get('JwtTcp') != tcp or connection.get('JwtUdp') != udp
                    or any(type(connection.get(field)) is not str or not connection[field]
                           for field in ('SearchId','Tcp','Udp'))
                    or len(connection['SearchId']) < 7):
                raise RoomError('Invalid server connection response.')
            return {'Prizm':connection}
        except Exception:
            self.leave(account_id,room['RoomId'])
            raise

    def match_event(self, player, version, event_id, difficulty):
        with self.rooms.lock:
            scope = self._event_scope(player['UserId'],event_id,difficulty)
            return self.match_checked(player,version,scope,(event_id,difficulty))

    def join_event(self, room_id, player, version, route, event_id, difficulty):
        with self.rooms.lock:
            room = self.rooms.rooms.get(room_id)
            if room is None or not self._event_matches(room,(event_id,difficulty)):
                raise RoomError('Room belongs to a different event.')
            scope = self._event_scope(player['UserId'],event_id,difficulty)
            return self.join_checked(room_id,player,version,route,scope)

    def start_http(self, account_id, episode_id, character_id, member_ids, member_character_ids):
        if self.event_catalog is not None:
            episode_id = self.event_catalog.episodes.resolve_episode(episode_id)
        return self.rooms.start_response(account_id,episode_id,character_id,
                                         member_ids,member_character_ids)

    def heartbeat_http(self, account_id, room_id):
        with self.rooms.lock:
            room = self.rooms.rooms.get(room_id)
            if (room is None or self.rooms.memberships.get(account_id) != room_id
                    or account_id not in {entry['UserId'] for entry in room['Players']}):
                raise RoomError('Heartbeat does not belong to an admitted room member.')
            return {}

    def complete_http(self, account_id, data, retire=False):
        from pve_completion import completion_request,completion_response,native_result_hash,decode_pve_playlog
        request = completion_request(account_id,data,retire)
        if not callable(self.completion_provider):
            raise RuntimeError('Raid completion policy is not configured.')
        with self.rooms.lock:
            room_id = self.rooms.memberships.get(account_id)
            room = self.rooms.rooms.get(room_id)
            prepared = room.get('PreparedBattle',{}).get(account_id) if room else None
            if (prepared is None or not secrets.compare_digest(
                    prepared['EpisodeToken'].encode('utf-8'),request['EpisodeToken'].encode('utf-8'))):
                raise RoomError('Completion token does not belong to this account battle.')
            previous = room.get('Completions',{}).get(account_id)
            identity = (retire,request)
            if previous is not None:
                if previous[0] != identity: raise RoomError('Battle completion already submitted.')
                # Only an explicitly implemented replay hook may refresh a result.
                # It must not settle if the durable record has disappeared.
                replay = getattr(type(self.completion_provider),'replay',None)
                if callable(replay):
                    response = completion_response(replay(self.completion_provider,account_id,
                        copy.deepcopy(room),copy.deepcopy(request),retire),retire)
                    room['Completions'][account_id] = copy.deepcopy((identity,response))
                    return copy.deepcopy(response)
                return copy.deepcopy(previous[1])
            if not retire and 'GameOver' not in room:
                raise RoomError('Battle outcome has not been reported.')
            if not retire and not secrets.compare_digest(request['ResultHash'].encode('utf-8'),
                    native_result_hash(prepared['BattleId'],room['GameOver'][1] == 1).encode('ascii')):
                raise RoomError('Battle result checksum does not match the reported outcome.')
            if request['Playlog']:
                decode_pve_playlog(request['Playlog'],prepared['EpisodeToken'])
            # The provider validates playlog/hash and owns durable, transactional
            # idempotency using BattleId/account. Transport victory is not proof.
            response = completion_response(self.completion_provider(account_id,
                copy.deepcopy(room),copy.deepcopy(request),retire),retire)
            room.setdefault('Completions',{})[account_id] = copy.deepcopy((identity,response))
            return copy.deepcopy(response)

    def discover_event(self, account_id, event_id, difficulty, version):
        if self.room_view_provider is None:
            raise RoomError('HTTP room views are not configured.')
        with self.rooms.lock:
            scope = self._event_scope(account_id,event_id,difficulty)
            rooms = self.discover(account_id,scope,version,event_context=(event_id,difficulty))
            return [self.room_view_provider(account_id,room) for room in rooms]

    def info_event(self, account_id, event_id, room_id, version):
        if (self.room_view_provider is None or self.event_catalog is None
                or self.eligibility_provider is None):
            raise RoomError('HTTP room information is not configured.')
        with self.rooms.lock:
            room = self.rooms.rooms.get(room_id)
            if (room is None or room['PveVersion'] != version
                    or room.get('EventId',event_id) != event_id):
                raise RoomError('Room information unavailable.')
            scope = set()
            for row in self.event_catalog.episodes.links:
                if row['EventId'] == event_id and row['EpisodeId'] == room['EpisodeId']:
                    scope.update(self._event_scope(account_id,event_id,row['Difficulty']))
            if not self._access(room,account_id,3,scope):
                raise RoomError('Room information unavailable.')
            return self.room_view_provider(account_id,copy.deepcopy(room))

    def _credentials(self, room, account_id):
        player = next(entry for entry in room['Players'] if entry['UserId'] == account_id)
        try:
            tcp,udp = self.registry.issue(account_id,room['RoomId'],player['Order']+1)
        except Exception:
            self.rooms.leave(account_id,room['RoomId'])
            raise
        return room,tcp,udp

    def leave(self, account_id, room_id):
        """Explicit departure, not socket loss (which may permit reconnect)."""
        room = self.rooms.leave(account_id,room_id)
        self.registry.revoke(account_id,room_id)
        for connection in list(self.connections.values()):
            admission = connection.session.admission
            if (admission.account_id,admission.room_id) == (account_id,room_id):
                connection.close()
        if room is not None:
            self.broadcast(room,leave_notification(account_id,room['Players']))
        return room

    def __call__(self, session, service, body, reliable):
        if service == BATTLE_SERVICE:
            command,_ = read_command_message(body)
            if command in (0,26):
                if not reliable:
                    raise ProtocolError('Battle completion requires reliable transport.')
                _,request_id,report = game_over_request(body)
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,command,False)
                    if 'PreparedBattle' not in room:
                        raise RoomError('Battle has not been prepared.')
                    current = self.rooms.rooms[room['RoomId']]
                    if command == 26:
                        reply = game_over_confirm_reply(current.get('GameOver'))
                    else:
                        player = next(entry for entry in room['Players'] if entry['UserId'] == session.admission.account_id)
                        members = set(current['PreparedBattle'])
                        if not player['IsHost'] or any(damage[1] not in members for damage in report[2]):
                            raise RoomError('Battle completion is not authorized.')
                        previous = current.get('GameOver')
                        if previous is not None and previous != report:
                            raise RoomError('Battle outcome has already been reported.')
                        if previous is None:
                            current['GameOver'] = copy.deepcopy(report)
                            self.broadcast(room,game_over_notification(report),exclude=session.admission.account_id,
                                           service=BATTLE_SERVICE)
                        reply = game_over_reply(report)
                    return [(BATTLE_SERVICE,rpc_response(command,request_id,reply),True)]
            if command == 2:
                if reliable:
                    raise ProtocolError('Object status requires unreliable transport.')
                request = update_status_request(body)
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,2,False)
                    current = self.rooms.rooms[room['RoomId']]
                    guid = request[1][1]
                    owner = self._object(current,guid)
                    if 'PreparedBattle' not in room or owner is None or owner[0] != session.admission.account_id:
                        raise RoomError('Object status sender does not own this object.')
                    current.setdefault('ObjectStatuses',{})[guid] = copy.deepcopy(request)
                    self.broadcast(room,update_status_notification(request),exclude=session.admission.account_id,
                                   service=BATTLE_SERVICE,reliable=False,coalesce=('status',guid))
                return []
            if not reliable:
                raise ProtocolError('Invalid battle load transport.')
            if command in (20,29,31,33):
                _,request,recipient = object_effect_request(body)
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,command,False)
                    current = self.rooms.rooms[room['RoomId']]
                    account,guid = session.admission.account_id,request[1][1]
                    owner = self._object(current,guid)
                    if 'PreparedBattle' not in room or owner is None or owner[0] != account:
                        raise RoomError('Effect sender does not own this object.')
                    if recipient is not None and recipient not in {entry['UserId'] for entry in room['Players']}:
                        raise RoomError('Effect recipient is not a room member.')
                    if recipient is None and command in (29,31):
                        buffs = current.setdefault('ObjectBuffs',{})
                        key = (guid,request.get(3 if command == 29 else 2,0))
                        if command == 29:
                            buffs[key] = copy.deepcopy(request)
                        else:
                            buffs.pop(key,None)
                    self.broadcast(room,object_effect_notification(command,request),exclude=account,
                                   service=BATTLE_SERVICE,recipient=recipient)
                return []
            if command in (22,24):
                _,request = object_liveness_request(body,session.admission.account_id)
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,command,False)
                    current = self.rooms.rooms[room['RoomId']]
                    guid = request[2 if command == 22 else 3][1]
                    owner = self._object(current,guid)
                    if 'PreparedBattle' not in room or owner is None:
                        raise RoomError('Unknown battle object.')
                    recipient = None if command == 22 else request[2]
                    if (command == 22 and owner[0] != session.admission.account_id
                            or command == 24 and (recipient != owner[0]
                                or recipient not in {entry['UserId'] for entry in room['Players']})):
                        raise RoomError('Object liveness ownership mismatch.')
                    self.broadcast(room,object_liveness_notification(command,request),
                                   exclude=session.admission.account_id,service=BATTLE_SERVICE,
                                   recipient=recipient,coalesce=('heartbeat',guid) if command == 22 else None)
                return []
            if command == 14:
                _,request = object_action_request(body)
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,14,False)
                    current = self.rooms.rooms[room['RoomId']]
                    account,guid = session.admission.account_id,request[1][1]
                    owner = self._object(current,guid)
                    retired = current.get('DestroyedObjects',{}).get(guid)
                    if 'PreparedBattle' not in room or (owner[0] if owner else retired) != account:
                        raise RoomError('Destruction sender does not own this object.')
                    recipient = request.get(2,'') or None
                    if recipient is not None and recipient not in {entry['UserId'] for entry in room['Players']}:
                        raise RoomError('Destruction recipient is not a room member.')
                    if owner is None:
                        return []
                    if recipient is None:
                        current.get('PlayerObjects',{}).pop(guid,None)
                        current.get('EnemyObjects',{}).pop(guid,None)
                        current.get('MinionObjects',{}).pop(guid,None)
                        current.get('ObjectStatuses',{}).pop(guid,None)
                        for key in list(current.get('ObjectBuffs',{})):
                            if key[0] == guid:
                                del current['ObjectBuffs'][key]
                        current.setdefault('DestroyedObjects',{})[guid] = account
                    self.broadcast(room,object_action_notification(14,request),exclude=account,
                                   service=BATTLE_SERVICE,recipient=recipient)
                return []
            if command in (4,6,8,16):
                _,request = object_action_request(body)
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,command,False)
                    current = self.rooms.rooms[room['RoomId']]
                    guid = request[1][1]
                    owner = self._object(current,guid)
                    if 'PreparedBattle' not in room or owner is None or owner[0] != session.admission.account_id:
                        raise RoomError('Action sender does not own this object.')
                    if command == 16:
                        credit = (request.get(5) or {}).get(1,'')
                        if credit and credit not in {entry['UserId'] for entry in room['Players']}:
                            raise RoomError('Damage credit is not a room member.')
                        for key in (2,3):
                            reference = (request.get(key) or {}).get(1)
                            if reference and reference.get(1) is not None and reference[1] != bytes(16):
                                referenced = reference[1]
                                if self._object(current,referenced) is None:
                                    raise RoomError('Reflection references an unknown room object.')
                    self.broadcast(room,object_action_notification(command,request),
                                   exclude=session.admission.account_id,service=BATTLE_SERVICE)
                return []
            command,_ = read_command_message(body)
            if command == 27:
                request = create_minion_request(body)
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,27,False)
                    current = self.rooms.rooms[room['RoomId']]
                    account = session.admission.account_id
                    parent = self._object(current,request[2][1])
                    if ('PreparedBattle' not in room or parent is None or parent[0] != account
                            or self.battle_minion_provider is None
                            or self.battle_minion_provider(account,copy.deepcopy(room),copy.deepcopy(request)) is not True):
                        raise RoomError('Minion creation is not authorized.')
                    recipient = request[7] or None
                    if recipient is not None and recipient not in {entry['UserId'] for entry in room['Players']}:
                        raise RoomError('Minion recipient is not a room member.')
                    guid = request[1][1]
                    if guid in current.get('DestroyedObjects',{}):
                        raise RoomError('Object GUID has already been destroyed.')
                    existing = self._object(current,guid)
                    objects = current.setdefault('MinionObjects',{})
                    if existing is not None and (guid not in objects or existing[0] != account
                            or {key:value for key,value in existing[1].items() if key not in (3,4,6,7)}
                            != {key:value for key,value in request.items() if key not in (3,4,6,7)}
                            or not minion_recovery_parameters_match(existing[1][6],request[6])):
                        raise RoomError('Minion object identity is already owned.')
                    if existing is None:
                        objects[guid] = (account,copy.deepcopy(request))
                    if existing is None or recipient is not None:
                        self.broadcast(room,create_minion_notification(request),exclude=account,
                                       service=BATTLE_SERVICE,recipient=recipient)
                return []
            if command == 12:
                request = create_enemy_request(body)
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,12,False)
                    if 'PreparedBattle' not in room or self.battle_enemy_provider is None:
                        raise RoomError('Battle enemy creation is not configured.')
                    account = session.admission.account_id
                    if hasattr(self.battle_enemy_provider, 'authorize'):
                        authorized = self.battle_enemy_provider.authorize(account,copy.deepcopy(room),request[4])
                    else:
                        allowed = self.battle_enemy_provider(account,copy.deepcopy(room))
                        authorized = type(allowed) in (set,frozenset,list,tuple) and request[4] in allowed
                    if authorized is not True:
                        raise RoomError('Enemy spawn is not authorized for this player.')
                    recipient = request[5] or None
                    if recipient is not None and recipient not in {entry['UserId'] for entry in room['Players']}:
                        raise RoomError('Enemy recipient is not a room member.')
                    current = self.rooms.rooms[room['RoomId']]
                    guid = request[1][1]
                    if guid in current.get('DestroyedObjects',{}):
                        raise RoomError('Object GUID has already been destroyed.')
                    if guid in current.get('PlayerObjects',{}) or guid in current.get('MinionObjects',{}):
                        raise RoomError('Object GUID is already used by a player.')
                    objects = current.setdefault('EnemyObjects',{})
                    existing = objects.get(guid)
                    if existing is not None and (existing[0] != account
                            or {key:value for key,value in existing[1].items() if key not in (2,3,5)}
                            != {key:value for key,value in request.items() if key not in (2,3,5)}):
                        raise RoomError('Enemy object identity is already owned.')
                    if existing is None:
                        objects[guid] = (account,copy.deepcopy(request))
                    if existing is None or recipient is not None:
                        self.broadcast(room,create_enemy_notification(request),exclude=account,
                                       service=BATTLE_SERVICE,recipient=recipient)
                return []
            if command == 10:
                with self.rooms.lock:
                    room = self.rooms.snapshot(session,10,False)
                    if 'PreparedBattle' not in room:
                        raise RoomError('Battle player creation is not configured.')
                    account = session.admission.account_id
                    player = next(entry for entry in room['Players'] if entry['UserId'] == account)
                    snapshots = self.rooms.rooms[room['RoomId']].get('BattleCharacters',{})
                    character = snapshots.get(account)
                    if character is None:
                        if self.battle_character_provider is None:
                            raise RoomError('Battle player creation is not configured.')
                        character = self.battle_character_provider(account,copy.deepcopy(room))
                    request_id,request = create_player_request(body,player,character)
                    recipient = request[7] or None
                    if recipient is not None and recipient not in {entry['UserId'] for entry in room['Players']}:
                        raise RoomError('Player object recipient is not a room member.')
                    objects = self.rooms.rooms[room['RoomId']].setdefault('PlayerObjects',{})
                    guid = request[1][1]
                    if guid in self.rooms.rooms[room['RoomId']].get('DestroyedObjects',{}):
                        raise RoomError('Object GUID has already been destroyed.')
                    if (guid in self.rooms.rooms[room['RoomId']].get('EnemyObjects',{})
                            or guid in self.rooms.rooms[room['RoomId']].get('MinionObjects',{})):
                        raise RoomError('Object GUID is already used by an enemy.')
                    existing = objects.get(guid)
                    if existing is not None:
                        def identity(value):
                            core = {key:item for key,item in value.items() if key not in (2,3,7)}
                            core[4] = {key:item for key,item in core[4].items() if key not in (6,7)}
                            return core
                        if (existing[0] != account
                                or identity(existing[1]) != identity(request)):
                            raise RoomError('Player object identity is already owned.')
                    else:
                        objects[guid] = (account,copy.deepcopy(request))
                    self.rooms.rooms[room['RoomId']].setdefault('BattleCharacters',{}).setdefault(account,copy.deepcopy(character))
                    if existing is None or recipient is not None:
                        self.broadcast(room,create_player_notification(request),exclude=account,
                                       service=BATTLE_SERVICE,recipient=recipient)
                    return [(BATTLE_SERVICE,rpc_response(10,request_id,create_player_reply(player)),True)]
            status = load_status_request(body,session.admission.account_id)
            with self.rooms.lock:
                room = self.rooms.snapshot(session,18,False)
                if 'PreparedBattle' not in room:
                    raise RoomError('Battle has not been prepared.')
                current = self.rooms.rooms[room['RoomId']]
                current.setdefault('LoadStatuses',{})[session.admission.account_id] = status
                self.broadcast(room,load_status_notification(session.admission.account_id,status),
                               service=BATTLE_SERVICE)
            return []
        command, payload = read_command_message(body)
        if command == 5:
            if service != 1000 or not reliable:
                raise ProtocolError('Invalid character change transport.')
            try:
                request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                    max_map_len=16,max_array_len=32,max_str_len=1024,max_bin_len=0)
            except (ValueError,msgpack.UnpackException):
                raise ProtocolError('Invalid character change payload.') from None
            account = session.admission.account_id
            if (type(request) is not dict or set(request) != {1} or type(next(iter(request))) is not int
                    or type(request[1]) is not dict or request[1].get(1) != account
                    or type(request[1].get(3)) is not str or not request[1][3]
                    or any(type(key) is not int or not 1 <= key <= 16 for key in request[1])):
                raise ProtocolError('Invalid character change identity.')
            resolver = getattr(self.player_provider,'for_character',None)
            if resolver is None:
                resolver = getattr(getattr(self.player_provider,'__self__',None),'for_character',None)
            if not callable(resolver):
                raise RoomError('Owned character selection is not configured.')
            with self.rooms.lock:
                self.rooms.snapshot(session,5,False)
                player = resolver(account,request[1][3])
                if player.get('CharacterId') != request[1][3]:
                    raise RoomError('Character resolver returned a different selection.')
                room,player = self.rooms.change_character(session,player)
                self.broadcast(room,character_change_notification(player))
            return []
        if command == 9:
            if service != 1000 or not reliable:
                raise ProtocolError('Invalid battle start transport.')
            try:
                request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                         max_map_len=1,max_str_len=128,max_array_len=0,max_bin_len=0)
            except (ValueError, msgpack.UnpackException):
                raise ProtocolError('Invalid battle start payload.') from None
            if (type(request) is not dict or set(request) != {1}
                    or type(next(iter(request))) is not int
                    or request[1] != session.admission.account_id):
                raise ProtocolError('Invalid battle start identity.')
            room = self.rooms.prepare_battle(session,self.battle_provider,self.battle_character_provider)
            self.broadcast(room,in_game_start_notification(session.admission.account_id))
            return []
        if command == 3:
            if service != 1000 or not reliable:
                raise ProtocolError('Invalid departure transport.')
            try:
                request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                         max_map_len=1,max_str_len=512,max_array_len=0,max_bin_len=0)
            except (ValueError, msgpack.UnpackException):
                raise ProtocolError('Invalid departure payload.') from None
            if (type(request) is not dict
                    or any(type(key) is not int or key != 1 for key in request)
                    or type(request.get(1,'')) is not str):
                raise ProtocolError('Invalid departure reason.')
            self.leave(session.admission.account_id,session.admission.room_id)
            return []
        if command != 7:
            return self.lobby(session,service,body,reliable)
        if service != 1000 or not reliable:
            raise ValueError('Invalid readiness transport.')
        request = msgpack.unpackb(payload,raw=False,strict_map_key=False,
                                 max_map_len=8,max_str_len=128,max_array_len=8,max_bin_len=128)
        if (not isinstance(request,dict) or any(type(key) is not int or key not in (1,2) for key in request)
                or type(request.get(1)) is not str):
            raise ValueError('Invalid readiness request.')
        ready = request.get(2,0)
        room = self.rooms.ready(session,request[1],ready)
        notification = ready_notification(request[1],ready)
        self.broadcast(room,notification)
        return []
