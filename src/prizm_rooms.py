"""Process-local authoritative room membership for the raid prototype.

Callers must authenticate HTTP admissions and enforce event/visibility rules.
Snapshots never accept client-provided battle statistics or room identity.
"""

import copy
import secrets
import threading
import msgpack
from dataclasses import dataclass
from prizm_battle import character_data_payload
from prizm_protocol import ProtocolError

from prizm_lobby import player_payload


class RoomError(ValueError):
    pass


@dataclass
class BattlePreparation:
    """Paired HTTP and transport snapshots produced by one preparation."""
    responses: dict
    characters: dict
    identities: dict = None


class Rooms:
    def __init__(self, capacity, room_limit=256):
        if type(capacity) is not int or not 1 <= capacity <= 32:
            raise RoomError('Invalid player capacity.')
        if type(room_limit) is not int or room_limit < 1:
            raise RoomError('Invalid room limit.')
        self.capacity = capacity
        self.room_limit = room_limit
        self.lock = threading.RLock()
        self.rooms = {}
        self.memberships = {}
        self.search_ids = {}

    def resolve_room_id(self, identity):
        """Resolve a displayed room code without replacing transport identity."""
        if type(identity) is not str or not identity:
            raise RoomError('Invalid room identity.')
        with self.lock:
            if identity in self.rooms:
                return identity
            room_id = self.search_ids.get(identity)
            if room_id is None or room_id not in self.rooms:
                raise RoomError('Unknown room.')
            return room_id

    def _new_search_id(self):
        # Native input has seven decimal slots; preserve leading zeroes.
        for _ in range(100):
            code = format(secrets.randbelow(10**7), '07d')
            if code not in self.search_ids:
                return code
        raise RoomError('Room search identity unavailable.')

    def create(self, player, episode_id, version, private, public_level,
               mode, suspend_limits):
        player_payload(player,allow_unselected=True)
        if not episode_id or not version or type(private) is not bool:
            raise RoomError('Invalid room configuration.')
        for value in (public_level,mode,*suspend_limits):
            if type(value) is not int or not 0 <= value < 2**31:
                raise RoomError('Invalid room configuration integer.')
        if len(suspend_limits) != 3:
            raise RoomError('Three suspend limits are required.')
        with self.lock:
            account = player['UserId']
            if account in self.memberships or len(self.rooms) >= self.room_limit:
                raise RoomError('Player already admitted or room limit reached.')
            room_id = secrets.token_hex(16)
            search_id = self._new_search_id()
            host = copy.deepcopy(player)
            # OpenSetup indexes contents[Order - 1]; zero is not a lobby slot.
            host.update(Order=1,IsHost=True,Ready=0)
            room = dict(RoomId=room_id,SearchId=search_id,EpisodeId=episode_id,PveVersion=version,
                        Players=[host],IsPrivate=private,PublicLevel=public_level,
                        Mode=mode,Status=0,LimitSuspendTime=suspend_limits[0],
                        LimitSuspendCount=suspend_limits[1],
                        OnetimeLimitSuspendTime=suspend_limits[2])
            self.rooms[room_id] = room
            self.search_ids[search_id] = room_id
            self.memberships[account] = room_id
            return copy.deepcopy(room)

    def join(self, room_id, player, version, admission_policy=None):
        player_payload(player,allow_unselected=True)
        with self.lock:
            room = self.rooms.get(room_id)
            if room is None:
                raise RoomError('Unknown room.')
            account = player['UserId']
            if account in self.memberships:
                raise RoomError('Player already admitted.')
            if room['PveVersion'] != version or room['Status'] != 0 or 'PreparedBattle' in room:
                raise RoomError('Incompatible or unavailable room.')
            if admission_policy is not None and admission_policy(copy.deepcopy(room)) is not True:
                raise RoomError('Room admission denied.')
            if len(room['Players']) >= self.capacity:
                raise RoomError('Room is full.')
            used = {entry['Order'] for entry in room['Players']}
            order = next(slot for slot in range(1,self.capacity + 1) if slot not in used)
            entry = copy.deepcopy(player)
            entry.update(Order=order,IsHost=False,Ready=0)
            room['Players'].append(entry)
            room['Players'].sort(key=lambda entry: entry['Order'])
            self.memberships[account] = room_id
            return copy.deepcopy(room)

    def leave(self, account, room_id):
        with self.lock:
            if self.memberships.get(account) != room_id:
                raise RoomError('Player is not a room member.')
            room = self.rooms[room_id]
            room['Players'] = [entry for entry in room['Players'] if entry['UserId'] != account]
            del self.memberships[account]
            if not room['Players']:
                del self.rooms[room_id]
                self.search_ids.pop(room['SearchId'], None)
                return None
            if not any(entry['IsHost'] for entry in room['Players']):
                room['Players'][0]['IsHost'] = True
            return copy.deepcopy(room)

    def discover(self, version, predicate, matching=False):
        with self.lock:
            results = []
            for room in self.rooms.values():
                if room['PveVersion'] != version or room['Status'] != 0 or 'PreparedBattle' in room:
                    continue
                if matching and len(room['Players']) >= self.capacity:
                    continue
                snapshot = copy.deepcopy(room)
                if predicate(snapshot) is True:
                    results.append(snapshot)
            return results

    def snapshot(self, session, command, rejoin):
        with self.lock:
            admission = session.admission
            if self.memberships.get(admission.account_id) != admission.room_id:
                raise RoomError('Room admission was revoked.')
            room = self.rooms.get(admission.room_id)
            if room is None:
                raise RoomError('Room no longer exists.')
            return copy.deepcopy(room)

    def change_character(self, session, player):
        player_payload(player)
        account = session.admission.account_id
        if player['UserId'] != account:
            raise RoomError('Cannot change another player character.')
        with self.lock:
            self.snapshot(session,5,False)
            room = self.rooms[session.admission.room_id]
            if room['Status'] != 0 or 'PreparedBattle' in room:
                raise RoomError('Lobby is no longer open.')
            current = next(entry for entry in room['Players'] if entry['UserId'] == account)
            replacement = copy.deepcopy(player)
            replacement.update(Order=current['Order'],IsHost=current['IsHost'],Ready=0)
            current.clear()
            current.update(replacement)
            return copy.deepcopy(room),copy.deepcopy(current)

    def ready(self, session, user_id, ready):
        if user_id != session.admission.account_id:
            raise RoomError('Cannot change another player readiness.')
        if type(ready) is not int or not 0 <= ready < 2**31:
            raise RoomError('Invalid readiness value.')
        with self.lock:
            self.snapshot(session,7,False)
            room = self.rooms[session.admission.room_id]
            if room['Status'] != 0 or 'PreparedBattle' in room:
                raise RoomError('Lobby is no longer open.')
            entry = next(player for player in room['Players'] if player['UserId'] == user_id)
            if ready and not entry['CharacterId']:
                raise RoomError('Select an owned character before readiness.')
            entry['Ready'] = ready
            return copy.deepcopy(room)

    def start_candidate(self, session):
        """Validate the host's lobby snapshot before server battle preparation.

        This does not start a battle or issue tokens; preparation must later
        atomically revalidate this roster before committing the transition.
        """
        with self.lock:
            room = self.snapshot(session,9,False)
            host = next(entry for entry in room['Players']
                        if entry['UserId'] == session.admission.account_id)
            if not host['IsHost'] or room['Status'] != 0 or 'PreparedBattle' in room:
                raise RoomError('Only the host of an open lobby can prepare battle.')
            if any(not entry['CharacterId'] for entry in room['Players']):
                raise RoomError('All participants must select owned characters.')
            if any(entry['Ready'] != 1 for entry in room['Players'] if not entry['IsHost']):
                raise RoomError('Guests are not ready.')
            return room

    def prepare_battle(self, session, provider, character_provider=None):
        """Prepare all member responses before freezing this lobby.

        The provider builds detached data only; it must not write progress or
        publish tokens externally. A failed preparation leaves the lobby open.
        Wire RoomInfo.Status semantics are not inferred from this internal gate.
        """
        if not callable(provider):
            raise RoomError('Battle preparation is not configured.')
        with self.lock:
            candidate = self.start_candidate(session)
            prepared = provider(copy.deepcopy(candidate))
            bundled_characters = None
            identities = None
            paired = isinstance(prepared, BattlePreparation)
            if paired:
                if character_provider is not None:
                    raise RoomError('Use one paired battle provider.')
                bundled_characters = prepared.characters
                identities = prepared.identities
                prepared = prepared.responses
            fields = {'EpisodeToken','CharacterDetail','EnemyDetail','EpisodeDetail',
                      'EpisodeDetailUser','MasterGroup','LimitTime','BgmId','BattleId'}
            accounts = {entry['UserId'] for entry in candidate['Players']}
            if (type(prepared) is not dict or set(prepared) != accounts
                    or any(type(response) is not dict or set(response) != fields
                           for response in prepared.values())):
                raise RoomError('Invalid prepared battle responses.')
            battle_ids = [response['BattleId'] for response in prepared.values()]
            tokens = [response['EpisodeToken'] for response in prepared.values()]
            if (any(type(value) is not str or not value for value in battle_ids + tokens)
                    or len(set(battle_ids)) != 1 or len(set(tokens)) != len(tokens)):
                raise RoomError('Invalid battle identity or member tokens.')
            for response in prepared.values():
                if (any(type(response[field]) is not dict for field in
                        ('CharacterDetail','EnemyDetail','EpisodeDetail','EpisodeDetailUser','MasterGroup'))
                        or type(response['LimitTime']) is not int or not 0 <= response['LimitTime'] < 2**31
                        or type(response['BgmId']) is not str):
                    raise RoomError('Invalid battle response field types.')
                try:
                    msgpack.packb(response,use_bin_type=True,strict_types=True)
                except (TypeError, ValueError, OverflowError):
                    raise RoomError('Battle response cannot be serialized.') from None
            detached = copy.deepcopy(prepared)
            characters = None
            if paired:
                if type(bundled_characters) is not dict or set(bundled_characters) != accounts:
                    raise RoomError('Invalid paired battle characters.')
                try:
                    characters = {account:character_data_payload(value)
                                  for account,value in bundled_characters.items()}
                except ProtocolError:
                    raise RoomError('Invalid prepared battle character.') from None
                selected = {player['UserId']:player['CharacterId'] for player in candidate['Players']}
                if identities is not None and (type(identities) is not dict or set(identities) != accounts):
                    raise RoomError('Invalid prepared character identities.')
                for account,character in characters.items():
                    identity = (selected[account], selected[account]) if identities is None else identities[account]
                    if (type(identity) is not tuple or len(identity) != 2
                            or identity[0] != selected[account] or identity[1] != character[1]):
                        raise RoomError('Prepared character identity mismatch.')
                    play = detached[account]['EpisodeDetailUser'].get('playCharacters')
                    expected = {'characterId':character[1], 'level':character[4],
                                'exp':character[5], 'hp':character[6], 'sp':character[7]}
                    if (type(play) is not list
                            or len(play) != 1 or type(play[0]) is not dict
                            or any(play[0].get(key) != value
                                   or type(play[0].get(key)) is not type(value)
                                   for key,value in expected.items())):
                        raise RoomError('Paired HTTP and transport character mismatch.')
            if character_provider is not None:
                if not callable(character_provider):
                    raise RoomError('Battle character preparation is not configured.')
                context = copy.deepcopy(candidate)
                context['PreparedBattle'] = copy.deepcopy(detached)
                try:
                    characters = {account:character_data_payload(
                        character_provider(account,copy.deepcopy(context))) for account in accounts}
                except ProtocolError:
                    raise RoomError('Invalid prepared battle character.') from None
            if self.start_candidate(session) != candidate:
                raise RoomError('Lobby changed during battle preparation.')
            self.rooms[candidate['RoomId']]['PreparedBattle'] = detached
            self.rooms[candidate['RoomId']]['BattleRoster'] = {
                entry['UserId']:entry['CharacterId'] for entry in candidate['Players']}
            if characters is not None:
                self.rooms[candidate['RoomId']]['BattleCharacters'] = characters
            return copy.deepcopy(self.rooms[candidate['RoomId']])

    def battle_roster(self, session, episode_id, character_id, member_ids, member_character_ids):
        """Validate PvE start inputs for a member without trusting its roster."""
        with self.lock:
            room = self.snapshot(session,9,False)
            return self._battle_roster(room,session.admission.account_id,episode_id,
                                       character_id,member_ids,member_character_ids)

    def start_response(self, account_id, episode_id, character_id, member_ids, member_character_ids):
        """Authenticated HTTP retrieval; each member receives only its own token."""
        with self.lock:
            room_id = self.memberships.get(account_id)
            room = self.rooms.get(room_id)
            if room is None or 'PreparedBattle' not in room:
                raise RoomError('Battle has not been prepared.')
            self._battle_roster(room,account_id,episode_id,character_id,member_ids,member_character_ids)
            return copy.deepcopy(room['PreparedBattle'][account_id])

    def _battle_roster(self, room, account_id, episode_id, character_id, member_ids, member_character_ids):
        if type(member_ids) is list and len(member_ids) == 4:
            member_ids = list(member_ids)
            while member_ids and member_ids[-1] is None:
                member_ids.pop()
        if (type(member_ids) is not list or type(member_character_ids) is not list
                or len(member_ids) != len(member_character_ids)
                or any(type(value) is not str for value in member_ids + member_character_ids)
                or len(set(member_ids)) != len(member_ids)):
            raise RoomError('Invalid battle roster.')
        if account_id not in {entry['UserId'] for entry in room['Players']}:
            raise RoomError('Player is not a current room member.')
        expected = room.get('BattleRoster',
                            {entry['UserId']:entry['CharacterId'] for entry in room['Players']})
        if (episode_id != room['EpisodeId'] or character_id != expected.get(account_id)
                or dict(zip(member_ids,member_character_ids)) != expected):
            raise RoomError('Battle request differs from authoritative room.')
        return copy.deepcopy(room)
