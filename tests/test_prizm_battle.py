import sys
import unittest
from pathlib import Path
import msgpack
import json

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_battle import (BATTLE_SERVICE,load_status_request,load_status_notification,
                         create_player_request,create_player_reply,create_player_notification,
                         create_enemy_request,create_enemy_notification,
                         update_status_request,update_status_notification,
                         object_action_request,object_action_notification,
                         object_liveness_request,object_liveness_notification,
                         create_minion_request,create_minion_notification,
                         object_effect_request,object_effect_notification,
                         game_over_request,game_over_reply,game_over_notification,game_over_confirm_reply)
from prizm_protocol import command_message,rpc_request,read_command_message,ProtocolError
from test_prizm_lobby import player
from prizm_lobby import player_payload
from prizm_battle import character_data_payload, minion_recovery_parameters_match


class BattleTests(unittest.TestCase):
    def test_player_creation_preserves_unset_native_character_name(self):
        identity = player('alice')
        data = {1:'character',2:'master',3:None,4:1,5:0,6:100,7:0,
                8:['costume','weapon'],9:[],10:[]}
        request = {1:{1:bytes(range(16))},2:{},3:{4:1.0},
                   4:data,6:player_payload(identity)}
        for omit in (False, True):
            actual = dict(data)
            if omit:
                actual.pop(3)
            _, parsed = create_player_request(rpc_request(10,42,
                msgpack.packb(request | {4:actual},use_bin_type=True)), identity, data)
            self.assertIsNone(parsed[4][3])
        for replacement in ('Hero', '', False):
            with self.assertRaises(ProtocolError):
                create_player_request(rpc_request(10,42,msgpack.packb(
                    request | {4:data | {3:replacement}},use_bin_type=True)), identity, data)

    def test_decoy_recovery_updates_hp_but_freezes_spawn_parameters(self):
        original = dict(MaxHP=100, HP=100, Base_LoadPath='decoy', AddPrefabInfos=['visual'])
        encoded = json.dumps(original)
        self.assertTrue(minion_recovery_parameters_match(encoded,json.dumps(original | {'HP':40})))
        self.assertTrue(minion_recovery_parameters_match(encoded,json.dumps(original | {'HP':0})))
        for change in ({'HP':101},{'HP':-1},{'HP':True},{'MaxHP':200},
                       {'Base_LoadPath':'other'},{'AddPrefabInfos':['other']},{'unknown':1}):
            self.assertFalse(minion_recovery_parameters_match(encoded,json.dumps(original | change)))
        self.assertFalse(minion_recovery_parameters_match(encoded,encoded[:-1]+',"HP":40}'))
        self.assertFalse(minion_recovery_parameters_match('opaque','different'))
        self.assertTrue(minion_recovery_parameters_match('opaque','opaque'))

    def test_authoritative_character_snapshot_native_ranges_and_detachment(self):
        data = {1:'character',2:'master',3:'name',4:1,5:2**40,6:100,7:0,
                8:['equipment'],9:[],10:[]}
        detached = character_data_payload(data)
        detached[8].append('other')
        self.assertEqual(data[8],['equipment'])
        for altered in (data | {4:True},data | {5:2**63},data | {6:2**31},
                        data | {8:[1]},data | {9:['item']*33},data | {3:'x'*513}):
            with self.assertRaises(ProtocolError): character_data_payload(altered)

    def test_game_over_rpc_native_defaults_reply_and_confirmation(self):
        report = {1:1,2:[{1:'alice',2:100}],3:'',4:0}
        self.assertEqual(game_over_request(rpc_request(0,42,msgpack.packb(report))),(0,42,report))
        self.assertEqual(msgpack.unpackb(game_over_reply(report),strict_map_key=False),{1:report[2],2:0})
        self.assertEqual(read_command_message(game_over_notification(report))[0],1)
        self.assertEqual(msgpack.unpackb(game_over_confirm_reply(report),strict_map_key=False),{1:1,2:report})
        self.assertEqual(msgpack.unpackb(game_over_confirm_reply(None),strict_map_key=False),{1:0,2:None})
        self.assertEqual(game_over_request(rpc_request(26,43,msgpack.packb({}))),(26,43,None))
        for altered in (report | {1:True},report | {2:[{1:'alice',2:True}]},
                        report | {2:[{1:'alice'},{1:'alice'}]},report | {4:2**63}):
            with self.assertRaises(ProtocolError): game_over_request(rpc_request(0,42,msgpack.packb(altered)))
    def test_status_action_and_buff_native_translation_and_types(self):
        guid = {1:bytes(range(16))}
        requests = [(20,{1:guid,2:1,3:2**32-1,10:1.0,20:-1,30:True,31:False}),
                    (29,{1:guid,2:1,3:-1,4:1,5:[1,-1],6:0,7:1,8:1,9:1.0,10:{1:1.0},100:'bob'}),
                    (31,{1:guid,2:-1,100:'bob'}),
                    (33,{1:guid,2:-1,3:1,4:b'payload',5:'data',100:'bob'})]
        for command,request in requests:
            parsed,body,recipient = object_effect_request(command_message(command,msgpack.packb(request)))
            self.assertEqual((parsed,body),(command,request))
            self.assertEqual(recipient,'bob' if command in (29,31,33) else None)
            peer,payload = read_command_message(object_effect_notification(command,request))
            self.assertEqual(peer,command+1)
            self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),request)
        for command,request in [(20,{1:guid,3:True}),(20,{1:guid,10:float('inf')}),
                                (20,{1:guid,30:1}),(20,{1:guid,20:True}),(20,{1:guid,4:1.0}),
                                (29,{1:guid,5:[False]}),(29,{1:guid,2:2**63}),
                                (29,{1:guid,10:{1:float('nan')}}),
                                (31,{1:guid,3:'bob'}),(33,{1:guid,4:[]}),
                                (29,{1:guid,11:'bob'}),(33,{1:guid,6:'bob'}),
                                (31,{1:guid,100:False})]:
            with self.assertRaises(ProtocolError):
                object_effect_request(command_message(command,msgpack.packb(request)))
    def test_minion_native_owner_guid_and_translation(self):
        request = {1:{1:bytes(range(16))},2:{1:bytes(range(1,17))},3:{},4:{4:1.0},5:'minion',100:'bob'}
        parsed = create_minion_request(command_message(27,msgpack.packb(request)))
        self.assertEqual(parsed,request | {6:''})
        command,payload = read_command_message(create_minion_notification(parsed))
        self.assertEqual(command,28)
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),parsed)
        for altered in (request | {2:request[1]},request | {5:''},request | {6:False},
                        request | {3:{1:float('inf')}},request | {7:'bob'},request | {100:False}):
            with self.assertRaises(ProtocolError):
                create_minion_request(command_message(27,msgpack.packb(altered)))
    def test_object_liveness_sender_translation_and_defaults(self):
        for command,request in [(22,{1:'alice',2:{1:bytes(range(16))}}),
                                (24,{1:'alice',2:'bob',3:{1:bytes(range(16))}})]:
            self.assertEqual(object_liveness_request(command_message(command,msgpack.packb(request)),'alice'),
                             (command,request))
            peer,payload = read_command_message(object_liveness_notification(command,request))
            self.assertEqual(peer,command+1)
            with self.assertRaises(ProtocolError):
                object_liveness_request(command_message(command,msgpack.packb(request)),'bob')
    def test_destroy_object_native_translation(self):
        request = {1:{1:bytes(range(16))},2:'bob'}
        self.assertEqual(object_action_request(command_message(14,msgpack.packb(request))),(14,request))
        command,payload = read_command_message(object_action_notification(14,request))
        self.assertEqual(command,15)
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),request)
        with self.assertRaises(ProtocolError):
            object_action_request(command_message(14,msgpack.packb(request | {2:False})))
    def test_reflection_native_translation_and_damage_credit_types(self):
        request = {1:{1:bytes(range(16))},2:{1:{1:bytes(range(16))}},
                   3:{1:{1:bytes(range(1,17))},2:'part'},4:{},5:{1:'alice',2:100}}
        self.assertEqual(object_action_request(command_message(16,msgpack.packb(request))),(16,request))
        command,payload = read_command_message(object_action_notification(16,request))
        self.assertEqual(command,17)
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),request)
        empty = request | {2:{1:{}},3:{1:{1:None}}}
        self.assertEqual(object_action_request(command_message(16,msgpack.packb(empty))),(16,empty))
        for altered in (request | {5:{1:'alice',2:True}},request | {5:{2:2**31}},
                        request | {3:{1:{1:b'bad'}}},request | {4:[]}):
            with self.assertRaises(ProtocolError):
                object_action_request(command_message(16,msgpack.packb(altered)))
    def test_battle_action_native_translation_and_move_sequence(self):
        request = {1:{1:bytes(range(16))},2:{},3:{1:1.0},4:{4:1.0},5:{},6:{},7:{},8:2**32-1}
        self.assertEqual(object_action_request(command_message(4,msgpack.packb(request))),(4,request))
        command,payload = read_command_message(object_action_notification(4,request))
        self.assertEqual(command,5)
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),request)
        for altered in (request | {8:True},request | {8:2**32},request | {2:[]},
                        request | {3:{1:float('nan')}}):
            with self.assertRaises(ProtocolError):
                object_action_request(command_message(4,msgpack.packb(altered)))
    def test_movement_and_attack_native_action_translation(self):
        for command,request in [(6,{1:{1:bytes(range(16))},2:1,3:{1:2.0},4:{}}),
                                (8,{1:{1:bytes(range(16))},2:{},3:['attack']})]:
            self.assertEqual(object_action_request(command_message(command,msgpack.packb(request))),
                             (command,request))
            peer,payload = read_command_message(object_action_notification(command,request))
            self.assertEqual(peer,command+1)
            self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),request)
        for command,request in [(6,{1:{1:bytes(range(16))},2:True}),
                                (6,{1:{1:bytes(range(16))},3:{1:float('inf')}}),
                                (8,{1:{1:bytes(range(16))},3:[False]}),
                                (8,{1:{1:bytes(range(16))},2:[]})]:
            with self.assertRaises(ProtocolError):
                object_action_request(command_message(command,msgpack.packb(request)))
    def test_object_status_native_unreliable_translation_and_sequences(self):
        status = {1:{1:bytes(range(16))},2:{1:1.0},3:{4:1.0},9:2**32-1,10:0,11:1}
        self.assertEqual(update_status_request(command_message(2,msgpack.packb(status))),status)
        command,payload = read_command_message(update_status_notification(status))
        self.assertEqual(command,3)
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),status)
        for altered in (status | {9:2**32},status | {10:True},status | {11:-1},
                        status | {7:2**63},status | {4:[]},status | {2:{1:float('nan')}}):
            with self.assertRaises(ProtocolError):
                update_status_request(command_message(2,msgpack.packb(altered)))
    def test_enemy_creation_native_one_way_translation(self):
        request = {1:{1:bytes(range(16))},2:{1:1.0},3:{4:1.0},4:'spawn'}
        parsed = create_enemy_request(command_message(12,msgpack.packb(request)))
        self.assertEqual(parsed,request | {100:''})
        command,payload = read_command_message(create_enemy_notification(parsed))
        self.assertEqual(command,13)
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),parsed)
        for altered in (request | {1:{1:b'bad'}},request | {2:{1:float('inf')}},
                        request | {4:''},request | {5:'bob'},request | {100:False},request | {6:1}):
            with self.assertRaises(ProtocolError):
                create_enemy_request(command_message(12,msgpack.packb(altered)))
    def test_create_player_rpc_reply_and_peer_notification(self):
        authoritative = player('alice')
        character = {1:'pl001',2:'master',3:'Alice',4:1,5:0,6:100,7:10,8:[],9:[],10:[]}
        request = {1:{1:bytes(range(16))},2:{1:1.0},3:{4:1.0},
                   4:{key:value for key,value in character.items() if value},
                   6:player_payload(authoritative),100:'bob'}
        req_id,result = create_player_request(rpc_request(10,42,msgpack.packb(request)),authoritative,character)
        self.assertEqual(req_id,42)
        self.assertEqual(result[4],character)
        self.assertEqual(result[6],player_payload(authoritative))
        for native in (request | {6:None},{key:value for key,value in request.items() if key != 6}):
            _,normalized = create_player_request(rpc_request(10,42,msgpack.packb(native)),
                                                authoritative,character)
            self.assertEqual(normalized[6],player_payload(authoritative))
        self.assertEqual(msgpack.unpackb(create_player_reply(authoritative),strict_map_key=False),
                         {1:player_payload(authoritative)})
        command,payload = read_command_message(create_player_notification(result))
        self.assertEqual(command,11)
        self.assertEqual(msgpack.unpackb(payload,strict_map_key=False),result)
        import copy
        for key,value in [(1,{1:bytes(16)}),(2,{1:float('nan')}),
                          (4,character | {6:999}),
                          (6,player_payload(player('bob'))),(6,{}),(6,False),
                          (5,True),(100,False),(7,'bob')]:
            forged = copy.deepcopy(request)
            forged[key] = value
            with self.subTest(key=key),self.assertRaises(ProtocolError):
                create_player_request(rpc_request(10,42,msgpack.packb(forged)),authoritative,character)
    def test_load_status_native_command_translation_and_default(self):
        self.assertEqual(BATTLE_SERVICE,2000)
        self.assertEqual(load_status_request(bytes.fromhex('1200 8201a1610201'),'a'),1)
        self.assertEqual(load_status_notification('a',1),bytes.fromhex('1300 8201a1610201'))
        self.assertEqual(load_status_request(command_message(18,msgpack.packb({1:'a'})),'a'),0)

    def test_cannot_report_loading_for_another_player_or_wrong_command(self):
        for command,body in [(18,{1:'bob',2:1}),(19,{1:'alice',2:1}),
                             (18,{1:'alice',2:True}),(18,{1:'alice',2:2**31}),
                             (18,{1:'alice',3:1}),(18,[1,2])]:
            with self.subTest(body=body),self.assertRaises(ProtocolError):
                load_status_request(command_message(command,msgpack.packb(body)),'alice')
