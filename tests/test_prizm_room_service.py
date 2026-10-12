import sys
import unittest
from unittest.mock import patch
from pathlib import Path
import msgpack

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_rooms import Rooms,RoomError
from prizm_room_service import RoomService
from prizm_sessions import SessionRegistry, SessionError
from prizm_connection import Connection
from prizm_protocol import (hello_request,user_message,command_message,
                            FrameDecoder,read_user_message,read_command_message,rpc_request,read_rpc_response,
                            fallback_request,Opcode)
from test_prizm_lobby import player
from prizm_lobby import player_payload
from prizm_protocol import ProtocolError


class RoomServiceTests(unittest.TestCase):
    def test_damage_reflection_authenticates_source_for_remote_target(self):
        rooms,registry = Rooms(4),SessionRegistry()
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        host = Connection(registry,service)
        host.receive(hello_request(tcp))
        _,tcp,_ = service.join(room['RoomId'],player('bob'),'v')
        guest = Connection(registry,service)
        guest.receive(hello_request(tcp))
        host.notifications()
        guest.notifications()
        host_guid,guest_guid,boss_guid = (bytes([n])*16 for n in (1,2,3))
        current = rooms.rooms[room['RoomId']]
        current.update(PreparedBattle={'alice':{'BattleId':'battle'},'bob':{'BattleId':'battle'}},
                       PlayerObjects={host_guid:('alice',{}),guest_guid:('bob',{})},
                       EnemyObjects={boss_guid:('alice',{})})
        def reflection(target,source,credit):
            return {1:{1:target},2:{1:{1:source}},3:{1:{1:target}},4:{3:100},5:{1:credit,2:100}}
        for sender,recipient,target,source,credit in (
                (guest,host,boss_guid,guest_guid,'bob'),
                (host,guest,guest_guid,boss_guid,'alice')):
            request = reflection(target,source,credit)
            service(sender.session,2000,command_message(16,msgpack.packb(request)),True)
            notifications = recipient.notifications()
            self.assertEqual(len(notifications),1)
            sid,body = read_user_message(FrameDecoder().feed(notifications[0])[0][1])
            command,payload = read_command_message(body)
            self.assertEqual((sid,command),(2000,17))
            self.assertEqual(msgpack.unpackb(payload,raw=False,strict_map_key=False),request)
            self.assertEqual(sender.notifications(),[])
        for request in (reflection(boss_guid,host_guid,'bob'),
                        reflection(boss_guid,bytes([9])*16,'bob'),
                        reflection(bytes([9])*16,guest_guid,'bob'),
                        reflection(boss_guid,bytes(16),'bob'),
                        reflection(boss_guid,guest_guid,'outsider'),
                        {1:{1:boss_guid},4:{3:100}}):
            with self.assertRaises(RoomError):
                service(guest.session,2000,command_message(16,msgpack.packb(request)),True)
        self.assertEqual(host.notifications(),[])
        # Source-less local effects retain their existing owner authorization.
        service(host.session,2000,command_message(16,msgpack.packb({1:{1:boss_guid},4:{3:100}})),True)
        self.assertEqual(len(guest.notifications()),1)
        # Remote damage does not grant movement or HP-update ownership.
        for command,request,reliable in ((4,{1:{1:boss_guid}},True),
                                         (2,{1:{1:boss_guid},2:{1:1.0}},False)):
            with self.assertRaises(RoomError):
                service(guest.session,2000,command_message(command,msgpack.packb(request)),reliable)

    def test_battle_relays_do_not_copy_frozen_master_data(self):
        class FrozenMasterData:
            def __deepcopy__(self, memo):
                raise AssertionError('Battle relay copied frozen HTTP master data')

        rooms,registry = Rooms(4),SessionRegistry()
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        host = Connection(registry,service)
        host.receive(hello_request(tcp))
        _,peer_tcp,_ = service.join(room['RoomId'],player('bob'),'v')
        peer = Connection(registry,service)
        peer.receive(hello_request(peer_tcp))
        peer.notifications()
        current = rooms.rooms[room['RoomId']]
        guid = bytes(range(16))
        current.update(PreparedBattle={'alice':{'BattleId':'battle','MasterGroup':FrozenMasterData()}},
                       PlayerObjects={guid:('alice',{})})
        reference = {1:guid}
        requests = [(2,{1:reference,2:{1:1.0}},False),
                    (4,{1:reference,2:{},3:{},4:{}},True),
                    (6,{1:reference,2:1,3:{}},True),
                    (8,{1:reference,2:{},3:[]},True),
                    (16,{1:reference,2:{1:reference},3:{1:reference},4:{},5:{1:'alice',2:1}},True),
                    (20,{1:reference,2:1,20:1},True),
                    (22,{1:'alice',2:reference},True),
                    (24,{1:'alice',2:'alice',3:reference},True),
                    (29,{1:reference,2:1,3:7},True),
                    (31,{1:reference,2:7},True),
                    (33,{1:reference,2:7,3:1,4:b'data'},True),
                    (14,{1:reference},True)]
        for command,request,reliable in requests:
            with self.subTest(command=command):
                body = command_message(command,msgpack.packb(request))
                if command != 24:
                    with self.assertRaises((RoomError,ProtocolError)):
                        service(peer.session,2000,body,reliable)
                self.assertEqual(service(host.session,2000,body,reliable),[])
                peer.notifications()
        del rooms.memberships['alice']
        with self.assertRaises(RoomError):
            service(host.session,2000,command_message(22,msgpack.packb({1:'alice',2:reference})),True)

    def test_status_action_defers_until_authorized_enemy_creation(self):
        rooms,registry = Rooms(4),SessionRegistry()
        service = RoomService(rooms,registry,battle_enemy_provider=lambda account,room:{'spawn'})
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        connection = Connection(registry,service)
        connection.receive(hello_request(tcp))
        current = rooms.rooms[room['RoomId']]
        current.update(PreparedBattle={'alice':{'BattleId':'battle'}},BattleRoster={'alice':'pl001'})
        guid = bytes(range(16))
        effect = {1:{1:guid},2:11,3:1,20:8}
        body = command_message(20,msgpack.packb(effect))
        with patch.object(service,'broadcast') as broadcast:
            self.assertEqual(service(connection.session,2000,body,True),[])
            broadcast.assert_not_called()
            self.assertNotIn('EnemyObjects',current)
            creation = {1:{1:guid},2:{},3:{},4:'spawn'}
            service(connection.session,2000,command_message(12,msgpack.packb(creation)),True)
            commands = [read_command_message(call.args[1])[0] for call in broadcast.call_args_list]
            self.assertEqual(commands,[13,21])
        self.assertEqual(current['PendingBattleActions'],[])
        current['EnemyObjects'][guid] = ('bob',{})
        with self.assertRaises(RoomError): service(connection.session,2000,body,True)
        current['EnemyObjects'] = {}
        current['DestroyedObjects'] = {guid:'alice'}
        with self.assertRaises(RoomError): service(connection.session,2000,body,True)

    def test_deferred_status_recipient_and_battle_generation_are_rechecked(self):
        rooms = Rooms(4)
        service = RoomService(rooms,SessionRegistry())
        room = {'RoomId':'test','Players':[{'UserId':'alice'},{'UserId':'bob'}],
                'BattleRoster':{'alice':'pl001'},'PreparedBattle':{'alice':{'BattleId':'battle'}}}
        rooms.rooms['test'] = room
        guid = bytes(range(16))
        request = {1:{1:guid},2:11,20:8}
        service._defer_action(room,'alice',guid,request,20,'bob')
        room['Players'].pop()
        with patch.object(service,'broadcast') as broadcast:
            service._flush_actions(room,'alice',guid)
            broadcast.assert_not_called()
        service._defer_action(room,'alice',guid,request,20)
        room['PreparedBattle'] = {'alice':{'BattleId':'next'}}
        with patch.object(service,'broadcast') as broadcast:
            service._flush_actions(room,'alice',guid)
            broadcast.assert_not_called()
        self.assertEqual(room['PendingBattleActions'],[])

    def test_native_send_only_reset_reopens_settled_host_and_retains_previous_result(self):
        rooms,registry = Rooms(4),SessionRegistry(reconnect=True)
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        connection = Connection(registry,service)
        connection.receive(hello_request(tcp))
        current = rooms.rooms[room['RoomId']]
        body = command_message(11,msgpack.packb({}))
        with self.assertRaises(RoomError): service(connection.session,1000,body,True)
        report = {1:1,2:[{1:'alice',2:100}],3:'',4:0}
        current.update(Status=1,PreparedBattle={'alice':{'EpisodeToken':'token'}},
                       GameOver=report,Completions={'alice':('identity',{})})
        guid = bytes(range(16))
        current['PlayerObjects'] = {guid:('alice',{})}
        for invalid in ([],{1:1},None):
            with self.assertRaises(ProtocolError):
                service(connection.session,1000,command_message(11,msgpack.packb(invalid)),True)
        with self.assertRaises(ProtocolError): service(connection.session,1000,body,False)
        self.assertEqual(service(connection.session,1000,body,True),[])
        self.assertEqual(current['Status'],0)
        self.assertNotIn('PreparedBattle',current)
        self.assertIn('alice',current['PreviousBattle']['Completions'])
        self.assertEqual(current['Players'][0]['Ready'],0)
        self.assertEqual(connection.notifications(),[])
        heartbeat = command_message(22,msgpack.packb({1:'alice',2:{1:guid}}))
        with patch.object(service,'broadcast') as broadcast:
            self.assertEqual(service(connection.session,2000,heartbeat,True),[])
            broadcast.assert_not_called()
        unknown = command_message(22,msgpack.packb({1:'alice',2:{1:b'x'*16}}))
        with patch.object(service,'broadcast') as broadcast:
            self.assertEqual(service(connection.session,2000,unknown,True),[])
            broadcast.assert_not_called()
        current['PreviousBattle']['PlayerObjects'][guid] = ('bob',{})
        with self.assertRaises(RoomError):
            service(connection.session,2000,heartbeat,True)
        current['PreviousBattle']['PlayerObjects'][guid] = ('alice',{})
        finish = rpc_request(0,81,msgpack.packb(report))
        with patch.object(service,'broadcast') as broadcast:
            replies = connection.receive(user_message(2000,finish))
            broadcast.assert_not_called()
        self.assertEqual(len(replies),1)
        self.assertFalse(connection.closed)
        confirm = rpc_request(26,82,msgpack.packb({}))
        response = service(connection.session,2000,confirm,True)[0][1]
        self.assertEqual(msgpack.unpackb(read_rpc_response(response)[3],strict_map_key=False),{1:1,2:report})
        with self.assertRaises(RoomError):
            service(connection.session,2000,rpc_request(0,83,msgpack.packb(report | {1:0})),True)
        cleanup = command_message(14,msgpack.packb({1:{1:guid}}))
        with patch.object(service,'broadcast') as broadcast:
            self.assertEqual(connection.receive(user_message(2000,cleanup)),[])
            broadcast.assert_not_called()
        previous = current['PreviousBattle']
        previous['PlayerObjects'].pop(guid)
        previous['DestroyedObjects'] = {guid:'alice'}
        self.assertEqual(service(connection.session,2000,cleanup,True),[])
        previous['DestroyedObjects'][guid] = 'bob'
        with self.assertRaises(RoomError):
            service(connection.session,2000,cleanup,True)
        previous['DestroyedObjects'][guid] = 'alice'
        unknown_cleanup = command_message(14,msgpack.packb({1:{1:b'x'*16}}))
        with patch.object(service,'broadcast') as broadcast:
            self.assertEqual(connection.receive(user_message(2000,unknown_cleanup)),[])
            broadcast.assert_not_called()
        import copy
        before = copy.deepcopy(current)
        self.assertEqual(service(connection.session,1000,body,True),[])
        self.assertEqual(current,before)
        service.release_returned_member('alice')
        self.assertTrue(connection.closed)
        self.assertNotIn('alice',rooms.memberships)

    def test_late_peer_return_after_host_reset_is_bounded_to_previous_open_lobby(self):
        rooms,registry = Rooms(4),SessionRegistry()
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        host = Connection(registry,service)
        host.receive(hello_request(tcp))
        _,peer_tcp,_ = service.join(room['RoomId'],player('bob'),'v')
        peer = Connection(registry,service)
        peer.receive(hello_request(peer_tcp))
        response = dict(EpisodeToken='token',BattleId='battle',CharacterDetail={},
            EnemyDetail={},EpisodeDetail={},EpisodeDetailUser={},MasterGroup={},LimitTime=60,BgmId='bgm')
        current = rooms.rooms[room['RoomId']]
        current.update(Status=1,PreparedBattle={'alice':response,'bob':response},GameOver={1:1},
                       Completions={'alice':('identity',{}),'bob':('identity',{})})
        reset = command_message(11,msgpack.packb({}))
        service(host.session,1000,reset,True)
        returned = command_message(35,msgpack.packb({1:'bob'}))
        service(peer.session,2000,returned,True)
        self.assertEqual(current['BackHomeUsers'],{'alice','bob'})
        self.assertEqual(service(peer.session,1000,reset,True),[])
        rooms.ready(peer.session,'bob',1)
        rooms.prepare_battle(host.session,lambda room:{'alice':response,
            'bob':response | {'EpisodeToken':'bob-token'}})
        self.assertNotIn('BackHomeUsers',current)
        service.release_returned_member('bob')
        self.assertEqual(rooms.memberships['bob'],room['RoomId'])
        self.assertFalse(peer.closed)
        with self.assertRaises(RoomError): service(peer.session,2000,returned,True)
        with self.assertRaises(RoomError): service(peer.session,1000,reset,True)

    def test_return_reset_preserves_unsettled_peer_and_nonhost_cannot_reopen(self):
        rooms,registry = Rooms(4),SessionRegistry()
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        host = Connection(registry,service)
        host.receive(hello_request(tcp))
        _,peer_tcp,_ = service.join(room['RoomId'],player('bob'),'v')
        peer = Connection(registry,service)
        peer.receive(hello_request(peer_tcp))
        current = rooms.rooms[room['RoomId']]
        current.update(Status=1,PreparedBattle={'alice':{},'bob':{}},GameOver={1:1},
                       Completions={'alice':('identity',{})})
        body = command_message(11,msgpack.packb({}))
        self.assertEqual(service(host.session,1000,body,True),[])
        self.assertIn('PreparedBattle',current)
        current['Completions']['bob'] = ('identity',{})
        self.assertEqual(service(peer.session,1000,body,True),[])
        self.assertIn('PreparedBattle',current)
        self.assertEqual(current['Status'],1)

    def test_unknown_heartbeat_is_dropped_without_registration_or_notification(self):
        import copy
        rooms,registry = Rooms(4),SessionRegistry()
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        connection = Connection(registry,service)
        connection.receive(hello_request(tcp))
        guid = bytes(range(16))
        body = command_message(22,msgpack.packb({1:'alice',2:{1:guid}}))
        with self.assertRaises(RoomError): service(connection.session,2000,body,True)
        current = rooms.rooms[room['RoomId']]
        current['PreparedBattle'] = {'alice':{}}
        before = copy.deepcopy(current)
        with patch.object(service,'broadcast') as broadcast:
            self.assertEqual(service(connection.session,2000,body,True),[])
            broadcast.assert_not_called()
        self.assertEqual(current,before)
        current['PlayerObjects'] = {guid:('bob',{})}
        with self.assertRaises(RoomError): service(connection.session,2000,body,True)
        current['PlayerObjects'] = {}
        confirm = command_message(24,msgpack.packb({1:'alice',2:'bob',3:{1:guid},4:True}))
        with self.assertRaises(RoomError): service(connection.session,2000,confirm,True)
        spoof = command_message(22,msgpack.packb({1:'bob',2:{1:guid}}))
        with self.assertRaises(ProtocolError): service(connection.session,2000,spoof,True)

    def test_back_home_is_authenticated_settled_and_allows_explicit_fresh_admission(self):
        rooms,registry = Rooms(4),SessionRegistry(reconnect=True)
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        connection = Connection(registry,service)
        connection.receive(hello_request(tcp))
        current = rooms.rooms[room['RoomId']]
        current.update(Status=1,PreparedBattle={'alice':{}},GameOver={1:1})
        body = command_message(35,msgpack.packb({1:'alice'}))
        with self.assertRaises(RoomError):
            service(connection.session,2000,body,True)
        current['Completions'] = {'alice':('identity',{})}
        service.release_returned_member('alice')
        self.assertEqual(rooms.memberships['alice'],room['RoomId'])
        for invalid in ({1:'bob'},{1:'alice',2:1},{True:'alice'}):
            with self.assertRaises(ProtocolError):
                service(connection.session,2000,command_message(35,msgpack.packb(invalid)),True)
        with self.assertRaises(ProtocolError): service(connection.session,2000,body,False)
        with patch.object(service,'broadcast') as broadcast:
            self.assertEqual(service(connection.session,2000,body,True),[])
            args,kwargs = broadcast.call_args
            self.assertEqual(kwargs['exclude'],'alice')
            command,payload = read_command_message(args[1])
            self.assertEqual(command,36)
            self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),{1:'alice'})
        self.assertEqual(current['BackHomeUsers'],{'alice'})
        self.assertEqual(rooms.memberships['alice'],room['RoomId'])
        self.assertEqual(connection.notifications(),[])
        current['Completions'] = {}
        service.release_returned_member('alice')
        self.assertEqual(rooms.memberships['alice'],room['RoomId'])
        current['Completions'] = {'alice':('identity',{})}
        service.release_returned_member('alice')
        self.assertNotIn('alice',rooms.memberships)
        self.assertTrue(connection.closed)
        new,_,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        self.assertNotEqual(new['RoomId'],room['RoomId'])

    def test_settled_disconnected_member_expires_without_dropping_unsettled_peer(self):
        now = [0]
        registry = SessionRegistry(clock=lambda:now[0],session_timeout=10,reconnect=True)
        rooms = Rooms(4)
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        host = Connection(registry,service)
        host.receive(hello_request(tcp))
        _,peer_tcp,_ = service.join(room['RoomId'],player('bob'),'v')
        peer = Connection(registry,service)
        peer.receive(hello_request(peer_tcp))
        current = rooms.rooms[room['RoomId']]
        current.update(Status=1,PreparedBattle={'alice':{},'bob':{}},
                       BattleRoster={'alice':'pl001','bob':'pl001'},GameOver={1:1},
                       Completions={'alice':('identity',{})})
        host.close()
        peer.close()
        now[0] = 9
        service.expire_lobbies()
        self.assertEqual(rooms.memberships['alice'],room['RoomId'])
        now[0] = 10
        service.expire_lobbies()
        self.assertNotIn('alice',rooms.memberships)
        self.assertEqual(rooms.memberships['bob'],room['RoomId'])
        self.assertEqual(current['BattleRoster'],{'alice':'pl001','bob':'pl001'})
        with self.assertRaises(SessionError): registry.open(tcp)
        new,_,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        self.assertNotEqual(new['RoomId'],room['RoomId'])

    def test_settled_active_member_is_not_expired(self):
        rooms,registry = Rooms(4),SessionRegistry(reconnect=True)
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,1,1,(60,3,20))
        connection = Connection(registry,service)
        connection.receive(hello_request(tcp))
        rooms.rooms[room['RoomId']].update(Status=1,PreparedBattle={'alice':{}},
            GameOver={1:1},Completions={'alice':('identity',{})})
        service.expire_lobbies()
        self.assertEqual(rooms.memberships['alice'],room['RoomId'])
        self.assertFalse(connection.closed)

    def test_pending_actions_are_bounded_expire_and_only_flush_for_creator(self):
        rooms = Rooms(4)
        service = RoomService(rooms,SessionRegistry())
        room = {'RoomId':'test','Players':[{'UserId':'alice'}],
                'BattleRoster':{'alice':'pl001'},'PreparedBattle':{'alice':{'BattleId':'battle-1'}}}
        rooms.rooms['test'] = room
        guid = bytes(range(16))
        request = {1:{1:guid}}
        with patch('prizm_room_service.time.monotonic',return_value=10):
            for _ in range(8): service._defer_action(room,'alice',guid,request)
            with self.assertRaises(RoomError): service._defer_action(room,'alice',guid,request)
        with patch('prizm_room_service.time.monotonic',return_value=16):
            service._defer_action(room,'alice',guid,request)
            self.assertEqual(len(room['PendingBattleActions']),1)
            service._defer_action(room,'bob',guid,request)
            with patch.object(service,'broadcast') as broadcast:
                service._flush_actions(room,'alice',guid)
                self.assertEqual(broadcast.call_count,1)
            self.assertEqual(room['PendingBattleActions'],[])
            service._defer_action(room,'alice',guid,request)
            room['PreparedBattle'] = {'alice':{'BattleId':'battle-2'}}
            with patch.object(service,'broadcast') as broadcast:
                service._flush_actions(room,'alice',guid)
                broadcast.assert_not_called()
            self.assertEqual(room['PendingBattleActions'],[])
            with self.assertRaises(RoomError):
                service._defer_action(room,'alice',guid,{1:{1:guid},2:{1:'x'*65536}})

    def test_character_change_rebuilds_stats_and_preserves_membership(self):
        from prizm_rooms import RoomError
        class Profiles:
            def for_character(self,account,character):
                if character != 'owned': raise RoomError('Not owned')
                return player(account) | {'CharacterId':character,'CharacterHp':123}
        rooms, registry = Rooms(2), SessionRegistry()
        service = RoomService(rooms,registry,player_provider=Profiles())
        room = service.create(player(),'ep','v',False,1,1,(60,3,20))[0]
        tcp,_ = registry.issue('alice',room['RoomId'],1)
        connection = Connection(registry,service)
        connection.receive(hello_request(tcp))
        request = {1:player_payload(player()) | {3:'owned',13:999999,8:False,7:99}}
        self.assertEqual(connection.receive(user_message(1000,
            command_message(5,msgpack.packb(request)))),[])
        current = rooms.rooms[room['RoomId']]['Players'][0]
        self.assertEqual((current['CharacterId'],current['CharacterHp'],current['Order'],current['IsHost']),
                         ('owned',123,1,True))
        _,body = read_user_message(FrameDecoder().feed(connection.notifications()[0])[0][1])
        command,payload = read_command_message(body)
        self.assertEqual(command,6)
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False)[2][13],123)
        for invalid in ({1:request[1] | {1:'bob'}},{1:request[1] | {3:'unowned'}}):
            with self.assertRaises((RoomError,ProtocolError)):
                service(connection.session,1000,command_message(5,msgpack.packb(invalid)),True)
        rooms.rooms[room['RoomId']]['PreparedBattle'] = {}
        with self.assertRaises(RoomError):
            service(connection.session,1000,command_message(5,msgpack.packb(request)),True)

    def test_host_start_prepares_once_and_notifies_room_members(self):
        from prizm_rooms import RoomError
        from pve_preparation import PreparedEnemySpawns
        rooms,registry = Rooms(2),SessionRegistry()
        prepared_calls = []
        def prepare(room):
            prepared_calls.append(room)
            return {entry['UserId']:dict(EpisodeToken='token-'+entry['UserId'],BattleId='battle',
                CharacterDetail={},EnemyDetail={},EpisodeDetail={'LayoutGroup':{'Enemies':[
                    dict(EpisodeEnemyId='spawn',EnemyId='boss')]}},EpisodeDetailUser={},
                MasterGroup={'enemyIndividuals':[dict(Index='boss')]},LimitTime=60,BgmId='bgm')
                for entry in room['Players']}
        character = {1:'pl001',2:'master',3:'Alice',4:1,5:0,6:100,7:10,8:[],9:[],10:[]}
        service = RoomService(rooms,registry,battle_provider=prepare,
                              battle_character_provider=lambda account,room:character,
                              battle_enemy_provider=PreparedEnemySpawns(),
                              battle_minion_provider=lambda account,room,request:request[5] == 'minion' and request[6] == '')
        room = service.create(player(),'ep','v',False,1,1,(60,3,20))[0]
        rooms.join(room['RoomId'],player('bob',1,False),'v')
        clients = []
        for name,number in [('alice',1),('bob',2)]:
            tcp,udp = registry.issue(name,room['RoomId'],number)
            connection = Connection(registry,service)
            connection.receive(hello_request(tcp))
            connection.receive(fallback_request(udp))
            clients.append(connection)
        start = command_message(9,msgpack.packb({1:'alice'}))
        load = command_message(18,msgpack.packb({1:'bob',2:1}))
        with self.assertRaises(RoomError): service(clients[1].session,2000,load,True)
        with self.assertRaises(RoomError): service(clients[0].session,1000,start,True)
        rooms.ready(clients[1].session,'bob',1)
        with self.assertRaises(RoomError):
            service(clients[1].session,1000,command_message(9,msgpack.packb({1:'bob'})),True)
        self.assertEqual(prepared_calls,[])
        self.assertEqual(clients[0].receive(user_message(1000,start)),[])
        self.assertEqual(len(prepared_calls),1)
        for connection in clients:
            sid,body = read_user_message(FrameDecoder().feed(connection.notifications()[0])[0][1])
            command,payload = read_command_message(body)
            self.assertEqual((sid,command),(1000,10))
            self.assertEqual(msgpack.unpackb(payload,raw=False,strict_map_key=False),{1:'alice'})
        with self.assertRaises(RoomError): service(clients[0].session,1000,start,True)
        self.assertEqual(len(prepared_calls),1)
        self.assertEqual(clients[1].receive(user_message(2000,load)),[])
        for connection in clients:
            sid,body = read_user_message(FrameDecoder().feed(connection.notifications()[0])[0][1])
            command,payload = read_command_message(body)
            self.assertEqual((sid,command),(2000,19))
            self.assertEqual(msgpack.unpackb(payload,raw=False,strict_map_key=False),{1:'bob',2:1})
        self.assertEqual(rooms.rooms[room['RoomId']]['LoadStatuses'],{'bob':1})
        creation = {1:{1:bytes(range(16))},2:{},3:{4:1.0},4:character,
                    6:player_payload(rooms.rooms[room['RoomId']]['Players'][0])}
        wire = rpc_request(10,42,msgpack.packb(creation))
        replies = clients[0].receive(user_message(2000,wire))
        self.assertEqual(len(replies),1)
        sid,body = read_user_message(FrameDecoder().feed(replies[0])[0][1])
        command,status,request_id,payload = read_rpc_response(body)
        self.assertEqual((sid,command,status,request_id),(2000,10,1,42))
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False)[1],creation[6])
        sid,body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
        self.assertEqual((sid,read_command_message(body)[0]),(2000,11))
        self.assertEqual(clients[0].notifications(),[])
        original_character_provider = service.battle_character_provider
        service.battle_character_provider = lambda account,room: character | {6:999}
        self.assertEqual(len(clients[0].receive(user_message(2000,wire))),1)
        self.assertEqual(rooms.rooms[room['RoomId']]['BattleCharacters']['alice'][6],100)
        for values in ({6:101},{7:11},{6:-1},{6:True}):
            invalid_recovery = creation | {4:character | values,100:'bob'}
            with self.assertRaises(ProtocolError):
                service(clients[0].session,2000,rpc_request(10,42,msgpack.packb(invalid_recovery)),True)
        self.assertEqual(clients[1].notifications(),[])
        service.battle_character_provider = original_character_provider
        damaged = creation | {2:{1:12.0,3:-4.0},3:{2:0.5,4:0.5},
                              4:character | {6:50,7:5},100:'bob'}
        service(clients[0].session,2000,rpc_request(10,42,msgpack.packb(damaged)),True)
        peer_frame = FrameDecoder().feed(clients[1].notifications()[0])[0]
        _,peer_body = read_user_message(peer_frame[1])
        _,peer_payload = read_command_message(peer_body)
        self.assertEqual(msgpack.unpackb(peer_payload,strict_map_key=False)[4][6],50)
        self.assertEqual(msgpack.unpackb(peer_payload,strict_map_key=False)[2],damaged[2])
        self.assertEqual(msgpack.unpackb(peer_payload,strict_map_key=False)[3],damaged[3])
        self.assertEqual(msgpack.unpackb(peer_payload,strict_map_key=False)[100],'bob')
        self.assertEqual(rooms.rooms[room['RoomId']]['BattleCharacters']['alice'][6],100)
        self.assertEqual(clients[1].notifications(),[])
        forged = dict(creation)
        forged[6] = player_payload(rooms.rooms[room['RoomId']]['Players'][1])
        with self.assertRaises(RoomError):
            service(clients[1].session,2000,rpc_request(10,43,msgpack.packb(forged)),True)
        self.assertEqual(len(rooms.rooms[room['RoomId']]['PlayerObjects']),1)
        enemy = {1:{1:bytes(range(1,17))},2:{},3:{4:1.0},4:'spawn'}
        enemy_wire = command_message(12,msgpack.packb(enemy))
        early_action = command_message(4,msgpack.packb({1:enemy[1],2:{},3:{},4:{}}))
        service(clients[0].session,2000,early_action,True)
        self.assertEqual(clients[1].notifications(),[])
        with self.assertRaises(RoomError): service(clients[1].session,2000,enemy_wire,True)
        self.assertEqual(clients[0].receive(user_message(2000,enemy_wire)),[])
        notifications = clients[1].notifications()
        self.assertEqual(len(notifications),2)
        sid,body = read_user_message(FrameDecoder().feed(notifications[0])[0][1])
        self.assertEqual((sid,read_command_message(body)[0]),(2000,13))
        _,body = read_user_message(FrameDecoder().feed(notifications[1])[0][1])
        self.assertEqual(read_command_message(body)[0],5)
        with self.assertRaises(RoomError): service(clients[1].session,2000,early_action,True)
        self.assertEqual(clients[0].receive(user_message(2000,enemy_wire)),[])
        self.assertEqual(clients[1].notifications(),[])
        for altered in (enemy | {4:'unknown'},enemy | {100:'outsider'},enemy | {1:creation[1]}):
            with self.assertRaises(RoomError):
                service(clients[0].session,2000,command_message(12,msgpack.packb(altered)),True)
        self.assertEqual(len(rooms.rooms[room['RoomId']]['EnemyObjects']),1)
        minion = {1:{1:bytes(range(3,19))},2:creation[1],3:{},4:{4:1.0},5:'minion'}
        minion_wire = command_message(27,msgpack.packb(minion))
        with self.assertRaises(RoomError): service(clients[1].session,2000,minion_wire,True)
        service(clients[0].session,2000,minion_wire,True)
        sid,body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
        self.assertEqual((sid,read_command_message(body)[0]),(2000,28))
        service(clients[0].session,2000,minion_wire,True)
        self.assertEqual(clients[1].notifications(),[])
        moved_minion = minion | {3:{1:3.0,2:4.0},4:{2:0.5,4:0.5},100:'bob'}
        service(clients[0].session,2000,command_message(27,msgpack.packb(moved_minion)),True)
        _,moved_body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
        moved_command,moved_payload = read_command_message(moved_body)
        self.assertEqual(moved_command,28)
        recovered_minion = msgpack.unpackb(moved_payload,strict_map_key=False)
        self.assertEqual(recovered_minion[3],moved_minion[3])
        self.assertEqual(recovered_minion[4],moved_minion[4])
        for altered in (minion | {5:'unknown'},minion | {6:'unknown'},minion | {1:enemy[1]}):
            with self.assertRaises(RoomError):
                service(clients[0].session,2000,command_message(27,msgpack.packb(altered)),True)
        minion_status = command_message(2,msgpack.packb({1:minion[1],2:{1:1.0}}))
        service(clients[0].session,2000,minion_status,False)
        self.assertEqual(len(clients[1].notifications()),1)
        heartbeat = command_message(22,msgpack.packb({1:'alice',2:creation[1]}))
        service(clients[0].session,2000,heartbeat,True)
        sid,body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
        self.assertEqual((sid,read_command_message(body)[0]),(2000,23))
        missing = command_message(24,msgpack.packb({1:'bob',2:'alice',3:creation[1],4:False}))
        service(clients[1].session,2000,missing,True)
        sid,body = read_user_message(FrameDecoder().feed(clients[0].notifications()[0])[0][1])
        self.assertEqual((sid,read_command_message(body)[0]),(2000,25))
        self.assertEqual(clients[1].notifications(),[])
        for targeted,command,target_field in [(creation,10,100),(enemy,12,100)]:
            request = targeted | {target_field:'bob'}
            if command == 12:
                request.update({2:{1:8.0},3:{2:0.5,4:0.5}})
            for _ in range(2):
                body = rpc_request(command,44,msgpack.packb(request)) if command == 10 else command_message(command,msgpack.packb(request))
                service(clients[0].session,2000,body,True)
                notifications = clients[1].notifications()
                self.assertEqual(len(notifications),1)
                sid,body = read_user_message(FrameDecoder().feed(notifications[0])[0][1])
                peer,payload = read_command_message(body)
                self.assertEqual((sid,peer),(2000,command+1))
                self.assertEqual(msgpack.unpackb(payload,strict_map_key=False)[target_field],'bob')
                if command == 12:
                    recovered = msgpack.unpackb(payload,strict_map_key=False)
                    self.assertEqual(recovered[2],request[2])
                    self.assertEqual(recovered[3],request[3])
                self.assertEqual(clients[0].notifications(),[])
        self.assertEqual(len(rooms.rooms[room['RoomId']]['PlayerObjects']),1)
        self.assertEqual(len(rooms.rooms[room['RoomId']]['EnemyObjects']),1)
        status = {1:creation[1],2:{1:1.0},3:{4:1.0},6:{1:40},9:1,10:1,11:1}
        status_wire = command_message(2,msgpack.packb(status))
        with self.assertRaises(RoomError): service(clients[1].session,2000,status_wire,False)
        self.assertEqual(clients[0].receive(user_message(2000,status_wire,fallback=True)),[])
        # A movement-only update must not erase the queued battle-status update.
        updated = {key:value for key,value in (status | {2:{1:2.0},9:2}).items() if key != 6}
        clients[0].receive(user_message(2000,command_message(2,msgpack.packb(updated)),fallback=True))
        notifications = clients[1].notifications()
        self.assertEqual(len(notifications),2)
        first_service,first_body = read_user_message(FrameDecoder().feed(notifications[0])[0][1])
        self.assertEqual(first_service,2000)
        self.assertEqual(msgpack.unpackb(read_command_message(first_body)[1],strict_map_key=False),status)
        opcode,payload = FrameDecoder().feed(notifications[1])[0]
        self.assertEqual(opcode,Opcode.FALLBACK_MESSAGE)
        sid,body = read_user_message(payload)
        command,payload = read_command_message(body)
        self.assertEqual((sid,command),(2000,3))
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),updated)
        self.assertEqual(rooms.rooms[room['RoomId']]['ObjectStatuses'][creation[1][1]],updated)
        reflection = {1:enemy[1],2:{1:creation[1]},3:{1:enemy[1]},4:{},5:{1:'alice',2:100}}
        for altered in (reflection | {5:{1:'outsider',2:100}},
                        reflection | {3:{1:{1:bytes(range(2,18))}}}):
            with self.assertRaises(RoomError):
                service(clients[0].session,2000,command_message(16,msgpack.packb(altered)),True)
        for command,action in [(16,reflection),
                               (4,{1:creation[1],2:{},3:{1:2.0},4:{4:1.0},8:1}),
                               (6,{1:creation[1],2:1,3:{1:2.0}}),
                               (8,{1:creation[1],2:{},3:['attack']})]:
            action_wire = command_message(command,msgpack.packb(action))
            with self.assertRaises(RoomError): service(clients[1].session,2000,action_wire,True)
            self.assertEqual(clients[0].receive(user_message(2000,action_wire)),[])
            opcode,payload = FrameDecoder().feed(clients[1].notifications()[0])[0]
            self.assertEqual(opcode,Opcode.USER_MESSAGE)
            sid,body = read_user_message(payload)
            self.assertEqual((sid,read_command_message(body)[0]),(2000,command+1))
        destroy = command_message(14,msgpack.packb({1:creation[1]}))
        for command,effect in [(20,{1:creation[1],2:1,3:1,30:True}),
                               (29,{1:creation[1],2:1,3:7,5:[1],10:{1:1.0}}),
                               (33,{1:creation[1],2:7,3:1,4:b'data',100:'bob'}),
                               (31,{1:creation[1],2:7})]:
            effect_wire = command_message(command,msgpack.packb(effect))
            with self.assertRaises(RoomError): service(clients[1].session,2000,effect_wire,True)
            service(clients[0].session,2000,effect_wire,True)
            sid,body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
            self.assertEqual((sid,read_command_message(body)[0]),(2000,command+1))
            if command == 29:
                self.assertIn((creation[1][1],7),rooms.rooms[room['RoomId']]['ObjectBuffs'])
        self.assertEqual(rooms.rooms[room['RoomId']]['ObjectBuffs'],{})
        with self.assertRaises(RoomError): service(clients[1].session,2000,destroy,True)
        target_destroy = command_message(14,msgpack.packb({1:creation[1],100:'bob'}))
        service(clients[0].session,2000,target_destroy,True)
        self.assertEqual(len(clients[1].notifications()),1)
        self.assertIn(creation[1][1],rooms.rooms[room['RoomId']]['PlayerObjects'])
        self.assertEqual(clients[0].receive(user_message(2000,destroy)),[])
        sid,body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
        self.assertEqual((sid,read_command_message(body)[0]),(2000,15))
        self.assertNotIn(creation[1][1],rooms.rooms[room['RoomId']]['PlayerObjects'])
        self.assertNotIn(creation[1][1],rooms.rooms[room['RoomId']]['ObjectStatuses'])
        self.assertEqual(clients[0].receive(user_message(2000,destroy)),[])
        self.assertEqual(clients[1].notifications(),[])
        with self.assertRaises(RoomError): service(clients[0].session,2000,status_wire,False)
        with self.assertRaises(RoomError):
            service(clients[0].session,2000,command_message(4,msgpack.packb({1:creation[1]})),True)
        with self.assertRaises(RoomError): service(clients[0].session,2000,wire,True)
        confirm = rpc_request(26,45,msgpack.packb({}))
        response = service(clients[1].session,2000,confirm,True)[0][1]
        self.assertEqual(msgpack.unpackb(read_rpc_response(response)[3],strict_map_key=False),{1:0,2:None})
        report = {1:1,2:[{1:'alice',2:100},{1:'bob',2:50}],3:'',4:0}
        finish = rpc_request(0,46,msgpack.packb(report))
        with self.assertRaises(RoomError): service(clients[1].session,2000,finish,True)
        replies = clients[0].receive(user_message(2000,finish))
        sid,body = read_user_message(FrameDecoder().feed(replies[0])[0][1])
        command,status,req_id,payload = read_rpc_response(body)
        self.assertEqual((sid,command,status,req_id),(2000,0,1,46))
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),{1:report[2],2:0})
        sid,body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
        self.assertEqual((sid,read_command_message(body)[0]),(2000,1))
        service(clients[0].session,2000,finish,True)
        self.assertEqual(clients[1].notifications(),[])
        response = service(clients[1].session,2000,confirm,True)[0][1]
        self.assertEqual(msgpack.unpackb(read_rpc_response(response)[3],strict_map_key=False),{1:1,2:report})
        with self.assertRaises(RoomError):
            service(clients[0].session,2000,rpc_request(0,47,msgpack.packb(report | {1:0})),True)
        self.assertEqual(rooms.rooms[room['RoomId']]['GameOver'],report)
        for connection in clients: connection.close()

    def test_matching_admits_atomic_last_slot_and_does_not_expose_private_rooms(self):
        from concurrent.futures import ThreadPoolExecutor
        from prizm_rooms import RoomError
        rooms,registry = Rooms(2),SessionRegistry()
        service = RoomService(rooms,registry)
        private = service.create(player('private'),'ep','v',True,2,1,(60,3,20))[0]['RoomId']
        public = service.create(player('host'),'ep','v',False,1,1,(60,3,20))[0]['RoomId']
        def match(name):
            try:
                return service.match_checked(player(name),'v',['ep'])
            except RoomError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(match,['bob','celia']))
        self.assertEqual(sum(result is not None for result in results),1)
        winner = next(result for result in results if result is not None)
        self.assertEqual(winner[0]['RoomId'],public)
        self.assertEqual(len(rooms.rooms[public]['Players']),2)
        self.assertEqual(len(rooms.rooms[private]['Players']),1)
        session = registry.open(winner[1])
        self.assertIn(session.admission.account_id,rooms.memberships)
        registry.fallback(session.session_id,winner[2])
        with self.assertRaises(RoomError): service.match_checked(player('other'),'v',['ep'])
        self.assertNotIn('other',rooms.memberships)

    def test_discovery_filters_event_version_privacy_guild_and_matching_capacity(self):
        rooms,registry = Rooms(2),SessionRegistry()
        guilds = {'viewer':'guild','guild-host':'guild'}
        service = RoomService(rooms,registry,guilds.get)
        def create(name,episode='ep',version='v',level=1):
            return service.create(player(name),episode,version,level == 2,level,1,(60,3,20))[0]['RoomId']
        public = create('public')
        private = create('private',level=2)
        guild = create('guild-host',level=3)
        create('wrong-event',episode='other')
        create('wrong-version',version='other')
        listed = service.discover('viewer',['ep'],'v')
        self.assertEqual({r['RoomId'] for r in listed},{public,guild})
        listed[0]['Players'].clear()
        self.assertEqual(len(rooms.rooms[public]['Players']),1)
        service.join_checked(public,player('guest'),'v',1,['ep'])
        self.assertEqual({r['RoomId'] for r in service.discover('viewer',['ep'],'v',2)},{guild})
        self.assertEqual({r['RoomId'] for r in service.discover('viewer',['ep'],'v',1)},{public,guild})
        guilds['viewer'] = 'other'
        self.assertEqual({r['RoomId'] for r in service.discover('viewer',['ep'],'v')},{public})
        with self.assertRaises(ValueError): service.discover('viewer',['ep'],'v',3)

    def test_checked_join_revalidates_event_route_and_current_host_guild(self):
        from prizm_rooms import RoomError
        rooms,registry = Rooms(3),SessionRegistry()
        service = RoomService(rooms,registry)
        room,tcp,udp = service.create(player(),'ep','v',False,3,1,(60,3,20))
        gid = room['RoomId']
        guilds = {'alice':'guild','bob':'guild'}
        service.guild_provider = guilds.get
        guest = player('bob',1,False)
        for route,episodes in [(1,['other']),(0,['ep'])]:
            with self.assertRaises(RoomError):
                service.join_checked(gid,guest,'v',route,episodes)
        guilds['bob'] = 'other'
        with self.assertRaises(RoomError):
            service.join_checked(gid,guest,'v',1,['ep'])
        self.assertNotIn('bob',rooms.memberships)
        guilds['bob'] = 'guild'
        service.join_checked(gid,guest,'v',1,['ep'])
        service.leave('alice',gid)
        guilds['bob'] = 'new-guild'
        guilds['celia'] = 'guild'
        with self.assertRaises(RoomError):
            service.join_checked(gid,player('celia'),'v',3,['ep'])
        self.assertNotIn('celia',rooms.memberships)
        self.assertEqual(len(rooms.rooms[gid]['Players']),1)

    def test_native_leave_command_uses_session_identity_and_has_no_reply(self):
        rooms,registry = Rooms(2),SessionRegistry()
        service = RoomService(rooms,registry)
        room,tcp,_ = service.create(player(),'ep','v',False,0,1,(60,3,20))
        _,bob_tcp,_ = service.join(room['RoomId'],player('bob',1,False),'v')
        alice,bob = Connection(registry,service),Connection(registry,service)
        alice.receive(hello_request(tcp))
        bob.receive(hello_request(bob_tcp))
        self.assertEqual(alice.receive(user_message(1000,command_message(3,msgpack.packb({})))),[])
        self.assertTrue(alice.closed)
        self.assertNotIn('alice',rooms.memberships)
        self.assertIn('bob',rooms.memberships)
        self.assertEqual(len(bob.notifications()),1)
        bob.close()

    def test_admission_failure_rolls_back_room_and_join_slot(self):
        rooms,registry = Rooms(2),SessionRegistry(limit=3)
        service = RoomService(rooms,registry)
        room,tcp,udp = service.create(player(),'ep','v',False,0,1,(60,3,20))
        room_id = room['RoomId']
        with self.assertRaises(SessionError):
            service.join(room_id,player('bob',1,False),'v')
        self.assertNotIn('bob',rooms.memberships)
        self.assertEqual(len(rooms.rooms[room_id]['Players']),1)
        with self.assertRaises(SessionError):
            service.create(player('celia'),'ep','v',False,0,1,(60,3,20))
        self.assertNotIn('celia',rooms.memberships)
        self.assertEqual(len(rooms.rooms),1)
        alice = registry.open(tcp)
        registry.fallback(alice.session_id,udp)
        joined,bob_tcp,bob_udp = service.join(room_id,player('bob',1,False),'v')
        self.assertEqual(joined['Players'][1]['Order'],2)
        bob = registry.open(bob_tcp)
        self.assertEqual(bob.admission.player_id,2)
        registry.fallback(bob.session_id,bob_udp)

    def test_departure_revokes_unused_admissions_without_connected_socket(self):
        rooms,registry = Rooms(2),SessionRegistry()
        service = RoomService(rooms,registry)
        room_id = rooms.create(player(),'ep','v',False,0,1,(60,3,20))['RoomId']
        rooms.join(room_id,player('bob',1,False),'v')
        tcp,udp = registry.issue('alice',room_id,1)
        bob_tcp,bob_udp = registry.issue('bob',room_id,2)
        bob = registry.open(bob_tcp)
        service.leave('alice',room_id)
        with self.assertRaises(SessionError): registry.open(tcp)
        with self.assertRaises(SessionError): registry.fallback(bob.session_id,udp)
        registry.fallback(bob.session_id,bob_udp)
        self.assertEqual(registry.get(bob.session_id).admission.account_id,'bob')
        self.assertEqual(len(registry.credentials),0)
        self.assertEqual(len(registry.sessions),1)

    def test_admission_departure_and_host_handover_notifications(self):
        rooms = Rooms(2)
        room_id = rooms.create(player(),'ep','v',False,0,1,(60,3,20))['RoomId']
        registry = SessionRegistry()
        service = RoomService(rooms,registry)
        clients = {}
        def connect(name,number):
            tcp,_ = registry.issue(name,room_id,number)
            connection = Connection(registry,service)
            connection.receive(hello_request(tcp))
            clients[name] = connection
        def notification(name):
            queued = clients[name].notifications()
            self.assertEqual(len(queued),1)
            _,body = read_user_message(FrameDecoder().feed(queued[0])[0][1])
            command,payload = read_command_message(body)
            return command,msgpack.unpackb(payload,raw=False,strict_map_key=False)
        connect('alice',1)
        joined = rooms.join(room_id,player('bob',1,False),'v')
        service.admitted(joined,'bob')
        command,body = notification('alice')
        self.assertEqual(command,2)
        self.assertEqual((body[1][1],body[1][8]),('bob',False))
        connect('bob',2)
        service.leave('alice',room_id)
        self.assertTrue(clients['alice'].closed)
        self.assertEqual(clients['alice'].notifications(),[])
        command,body = notification('bob')
        self.assertEqual((command,body[1]),(4,'alice'))
        self.assertEqual(len(body[2]),1)
        self.assertEqual((body[2][0][1],body[2][0][8]),('bob',True))
        self.assertIsNone(service.leave('bob',room_id))
        self.assertEqual(service.connections,{})

    def test_ready_broadcast_is_room_scoped_and_disconnect_unsubscribes(self):
        rooms = Rooms(2)
        room = rooms.create(player(),'ep','v',False,0,1,(60,3,20))['RoomId']
        rooms.join(room,player('bob',1,False),'v')
        other = rooms.create(player('celia'),'ep','v',False,0,1,(60,3,20))['RoomId']
        registry = SessionRegistry()
        service = RoomService(rooms,registry)
        connections = []
        for index,(name,gid) in enumerate([('alice',room),('bob',room),('celia',other)],1):
            tcp,_ = registry.issue(name,gid,index)
            connection = Connection(registry,service)
            connection.receive(hello_request(tcp))
            connections.append(connection)
        wire = user_message(1000,command_message(7,msgpack.packb({1:'bob',2:1})))
        self.assertEqual(connections[1].receive(wire),[])
        for connection in connections[:2]:
            framed = FrameDecoder().feed(connection.notifications()[0])[0][1]
            sid,body = read_user_message(framed)
            cmd,payload = read_command_message(body)
            self.assertEqual((sid,cmd),(1000,8))
            self.assertEqual(msgpack.unpackb(payload,raw=False,strict_map_key=False),{1:'bob',2:1})
        self.assertEqual(connections[2].notifications(),[])
        for connection in connections: connection.close()
        self.assertEqual(service.connections,{})

