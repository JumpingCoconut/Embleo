import sys
import unittest
from pathlib import Path
import msgpack

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from prizm_lobby import player_payload, join_reply, room_info_reply, LobbyService, ready_notification, in_game_start_notification
from prizm_connection import Connection
from prizm_sessions import SessionRegistry
from prizm_protocol import (hello_request, user_message, rpc_request,
                            FrameDecoder, read_user_message, read_rpc_response)


def player(name='alice', order=1, host=True):
    return dict(UserId=name, Name=name.title(), CharacterId='pl001',
                CharacterLevel=10, CharacterPower=100, VisualEquipments=[],
                Order=order, IsHost=host, CliVersion='1.6.0', Ready=0,
                CostumeSpells=[], WeaponSpells=[], CharacterHp=1000,
                CharacterAttack=20, CharacterDefense=30, MissionRank=1)


class LobbyPayloadTests(unittest.TestCase):
    def test_native_battle_start_notification_vector(self):
        self.assertEqual(in_game_start_notification('a'),bytes.fromhex('0a00 8101a161'))
        for value in ('',None,1):
            with self.assertRaises(ValueError): in_game_start_notification(value)

    def test_ready_notification_uses_distinct_command(self):
        self.assertEqual(ready_notification('a',1),bytes.fromhex('0800 8201a1610201'))
    def test_join_and_info_through_authenticated_framing(self):
        people = [player(), player('bob',2,False)]
        room = dict(RoomId='room', Players=people, LimitSuspendTime=60,
                    LimitSuspendCount=3, OnetimeLimitSuspendTime=20,
                    IsPrivate=False, Mode=1, Status=0, PublicLevel=0)
        registry = SessionRegistry()
        service = LobbyService(lambda session, command, rejoin: room)
        for name, player_id in [('alice',1), ('bob',2)]:
            tcp, _ = registry.issue(name,'room',player_id)
            connection = Connection(registry,service)
            connection.receive(hello_request(tcp))
            for command, request in [(1,{1:False}),(12,{})]:
                wire = user_message(1000,rpc_request(command,42,msgpack.packb(request)))
                reply = connection.receive(wire)[0]
                _, framed = FrameDecoder().feed(reply)[0]
                service_id, body = read_user_message(framed)
                cmd, status, request_id, payload = read_rpc_response(body)
                self.assertEqual((service_id,cmd,status,request_id),(1000,command,1,42))
                decoded = msgpack.unpackb(payload,raw=False,strict_map_key=False)
                self.assertEqual([entry[1] for entry in decoded[1]],['alice','bob'])
            connection.close()

    def test_room_identity_and_request_validation(self):
        registry = SessionRegistry()
        tcp, _ = registry.issue('alice','room',1)
        session = registry.open(tcp)
        service = LobbyService(lambda *args: {'RoomId':'other','Players':[player()]})
        for command, request in [(1,{1:True}),(1,{1:1}),(12,{1:False}),(12,{})]:
            _, response, reliable = service(session,1000,rpc_request(command,2,msgpack.packb(request)),True)[0]
            self.assertEqual(read_rpc_response(response)[1],2)
            self.assertTrue(reliable)

    def test_native_field_mapping(self):
        payload = player_payload(player())
        self.assertEqual(payload, {1:'alice',2:'Alice',3:'pl001',4:10,5:100,
                              6:[],7:1,8:True,9:'1.6.0',10:0,11:[],12:[],
                                  13:1000,14:20,15:30,16:1})
        people = [player(), player('bob',2,False)]
        joined = msgpack.unpackb(join_reply(people,60,3,20),raw=False,strict_map_key=False)
        self.assertEqual([entry[1] for entry in joined[1]], ['alice','bob'])
        self.assertEqual([joined[key] for key in (2,3,4)], [60,3,20])
        info = msgpack.unpackb(room_info_reply(people,'room',False,1,0,0),
                               raw=False,strict_map_key=False)
        self.assertEqual(info[1],joined[1])
        self.assertEqual({key:info[key] for key in range(2,7)}, {2:'room',3:False,4:1,5:0,6:0})

    def test_missing_stats_and_invalid_role_or_order_rejected(self):
        incomplete = player()
        del incomplete['CharacterHp']
        with self.assertRaises(ValueError):
            player_payload(incomplete)
        for people in ([player(),player()], [player(),player('bob',1,True)],
                       [player(host=False)], [player(),player('bob',0,False)]):
            with self.assertRaises(ValueError):
                join_reply(people,60,3,20)
        invalid = player()
        invalid['CharacterHp'] = True
        with self.assertRaises(ValueError):
            player_payload(invalid)
