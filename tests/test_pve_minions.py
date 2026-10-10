import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pve_minions import PreparedBitSummons, PreparedDecoyRelay, decoy_max_hp


class BitSummonTests(unittest.TestCase):
    def test_native_decoy_rounding_and_additive_multipliers(self):
        self.assertEqual(decoy_max_hp(101, 0.5), 51)
        self.assertEqual(decoy_max_hp(1000, 0.5, [1.25]), 625)
        self.assertEqual(decoy_max_hp(1000, 0.5, [1.25, 1.5]), 875)
        self.assertEqual(decoy_max_hp(1000, 0), 500)
        self.assertEqual(decoy_max_hp(1000, -1), 500)
        # Native int-to-single rounding precedes multiplication and ceiling.
        self.assertEqual(decoy_max_hp(100000001, 0.5), 50000000)
        self.assertEqual(decoy_max_hp(100, 0.5, [-1]), 0)
        for hp, rate, effects in ((True, 0.5, []), (-1, 0.5, []),
                                  (2**31, 0.5, []), (100, float('nan'), []),
                                  (100, 0.5, [float('inf')]),
                                  (100, 0.5, [True]), (100, 1e100, []),
                                  (2**30, 4, [])):
            with self.assertRaises(ValueError):
                decoy_max_hp(hp, rate, effects)

    def fixture(self):
        parent = b'p' * 16
        request = {1: {1: b'n' * 16}, 2: {1: parent}, 3: {}, 4: {},
                   5: 'Bit', 6: '', 7: ''}
        master = dict(CharacterId='pl021', UniqueParamData=json.dumps(
            {'m_Param_Int': [{'Key': 'MaxMinionCount', 'Value': 5}]}))
        room = dict(BattleCharacters={'alice': {1: 'pl021', 2: 'pl021'}},
                    PlayerObjects={parent: ('alice', {})},
                    PreparedBattle={'alice': {'MasterGroup': {'characters': [master]}}},
                    MinionObjects={})
        return room, request

    def test_limit_recovery_and_destroyed_slot(self):
        room, request = self.fixture()
        policy = PreparedBitSummons()
        original = deepcopy(room)
        self.assertTrue(policy('alice', room, request))
        self.assertEqual(room, original)
        for i in range(5):
            item = deepcopy(request)
            item[1][1] = bytes([i + 1]) * 16
            room['MinionObjects'][item[1][1]] = ('alice', item)
        self.assertFalse(policy('alice', room, request))
        second_parent = b'q' * 16
        room['PlayerObjects'][second_parent] = ('alice', {})
        self.assertFalse(policy('alice', room, request | {2: {1: second_parent}}))
        existing = next(iter(room['MinionObjects'].values()))[1]
        self.assertTrue(policy('alice', room, existing | {7: 'bob'}))
        del room['MinionObjects'][existing[1][1]]
        self.assertTrue(policy('alice', room, request))

    def test_character_parent_and_payload_scope(self):
        room, request = self.fixture()
        policy = PreparedBitSummons()
        self.assertFalse(policy('bob', room, request))
        for change in ({5: 'EnemyBit'}, {5: 'MagicDecoy'}, {6: '{}'},
                       {2: {1: b'x' * 16}}):
            self.assertFalse(policy('alice', room, request | change))
        room['PlayerObjects'][request[2][1]] = ('bob', {})
        self.assertFalse(policy('alice', room, request))
        room['PlayerObjects'][request[2][1]] = ('alice', {})
        for key in (1, 2):
            room['BattleCharacters']['alice'][key] = 'pl001'
            self.assertFalse(policy('alice', room, request))
            room['BattleCharacters']['alice'][key] = 'pl021'

    def test_decoy_equipped_binding_bounds_and_scope(self):
        room, request = self.fixture()
        room['BattleCharacters']['alice'][10] = ['weapon']
        response = room['PreparedBattle']['alice']
        response['CharacterDetail'] = {'userEquipments': [{'EquipmentId': 'weapon'}]}
        response['MasterGroup']['equipments'] = [{'EquipmentId': 'weapon', 'SpellId': 'spell'}]
        policy = PreparedDecoyRelay({'spell': ('prefab', ('effect',))}, 1)
        params = dict(MaxHP=625, HP=625, Base_LoadPath='prefab', AddPrefabInfos=['effect'])
        request |= {5: 'MagicDecoy', 6: json.dumps(params)}
        self.assertTrue(policy('alice', room, request))
        self.assertFalse(policy('bob', room, request))
        for change in ({'MaxHP': True}, {'HP': -1}, {'HP': 626}, {'MaxHP': 2**31},
                       {'Base_LoadPath': 'other'}, {'AddPrefabInfos': ['other']}):
            self.assertFalse(policy('alice', room, request | {6: json.dumps(params | change)}))
        self.assertFalse(policy('alice', room, request | {6: request[6][:-1] + ',"HP":0}'}))
        room['BattleCharacters']['alice'][10] = []
        self.assertFalse(policy('alice', room, request))
        room['BattleCharacters']['alice'][10] = ['weapon']
        response['CharacterDetail']['userEquipments'] = []
        self.assertFalse(policy('alice', room, request))
        response['CharacterDetail']['userEquipments'] = [{'EquipmentId': 'weapon'}]
        room['BattleCharacters']['alice'][10] = ['spell']
        self.assertFalse(policy('alice', room, request))
        room['BattleCharacters']['alice'][10] = ['weapon']
        room['MinionObjects'][request[1][1]] = ('alice', request)
        self.assertFalse(policy('alice', room, request | {1: {1: b'z' * 16}}))
        self.assertTrue(policy('alice', room, request | {6: json.dumps(params | {'HP': 20})}))

    def test_invalid_frozen_limits_reject(self):
        room, request = self.fixture()
        policy = PreparedBitSummons()
        row = room['PreparedBattle']['alice']['MasterGroup']['characters'][0]
        for value in (True, 0, -1, 33, 5.0, '5'):
            row['UniqueParamData'] = json.dumps(
                {'m_Param_Int': [{'Key': 'MaxMinionCount', 'Value': value}]})
            with self.assertRaises(ValueError):
                policy('alice', room, request)
        row['UniqueParamData'] = '{"m_Param_Int":[],"m_Param_Int":[]}'
        with self.assertRaises(ValueError):
            policy('alice', room, request)

    def test_room_dispatch_enforces_limit_and_peer_creation(self):
        import msgpack
        from prizm_rooms import Rooms, RoomError
        from prizm_sessions import SessionRegistry
        from prizm_connection import Connection
        from prizm_room_service import RoomService
        from prizm_protocol import (hello_request, command_message, FrameDecoder,
                                    read_user_message, read_command_message)
        from test_prizm_lobby import player
        rooms, registry = Rooms(2), SessionRegistry()
        service = RoomService(rooms, registry, battle_minion_provider=PreparedBitSummons())
        created = service.create(player(), 'ep', 'v', False, 1, 1, (60, 3, 20))[0]
        rooms.join(created['RoomId'], player('bob', 1, False), 'v')
        clients = []
        for number, account in enumerate(('alice', 'bob'), 1):
            tcp, _ = registry.issue(account, created['RoomId'], number)
            client = Connection(registry, service)
            client.receive(hello_request(tcp))
            clients.append(client)
        fixture, request = self.fixture()
        current = rooms.rooms[created['RoomId']]
        current.update(fixture)
        for i in range(5):
            item = deepcopy(request)
            item[1][1] = bytes([i + 1]) * 16
            service(clients[0].session, 2000, command_message(27, msgpack.packb(item)), True)
            sid, body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
            command, payload = read_command_message(body)
            self.assertEqual((sid, command), (2000, 28))
            self.assertEqual(msgpack.unpackb(payload, strict_map_key=False), item)
        with self.assertRaises(RoomError):
            service(clients[0].session, 2000, command_message(27, msgpack.packb(request)), True)
        self.assertEqual(len(current['MinionObjects']), 5)
        self.assertEqual(clients[1].notifications(), [])
        service.battle_minion_provider = PreparedDecoyRelay({'spell': ('prefab', ('effect',))}, 1)
        current['BattleCharacters']['alice'][10] = ['weapon']
        current['PreparedBattle']['alice']['CharacterDetail'] = {
            'userEquipments': [{'EquipmentId': 'weapon'}]}
        current['PreparedBattle']['alice']['MasterGroup']['equipments'] = [
            {'EquipmentId': 'weapon', 'SpellId': 'spell'}]
        params = dict(MaxHP=625, HP=625, Base_LoadPath='prefab', AddPrefabInfos=['effect'])
        decoy = request | {5: 'MagicDecoy', 6: json.dumps(params)}
        service(clients[0].session, 2000, command_message(27, msgpack.packb(decoy)), True)
        self.assertEqual(len(clients[1].notifications()), 1)
        forged = decoy | {6: json.dumps(params | {'MaxHP': 999})}
        with self.assertRaises(RoomError):
            service(clients[0].session, 2000, command_message(27, msgpack.packb(forged)), True)
        recovered = decoy | {6: json.dumps(params | {'HP': 20}), 7: 'bob'}
        service(clients[0].session, 2000, command_message(27, msgpack.packb(recovered)), True)
        _, body = read_user_message(FrameDecoder().feed(clients[1].notifications()[0])[0][1])
        _, payload = read_command_message(body)
        self.assertEqual(json.loads(msgpack.unpackb(payload, strict_map_key=False)[6])['HP'], 20)


if __name__ == '__main__':
    unittest.main()
