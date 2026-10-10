import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_completion import completion_request,native_result_hash,native_playlog_hash,decode_pve_playlog
from prizm_room_service import RoomService
from prizm_rooms import Rooms,RoomError
from prizm_sessions import SessionRegistry
from test_prizm_lobby import player
from accounts import AccountStore
from pve_results import DurableCompletionProvider,JOURNAL


class CompletionTests(unittest.TestCase):
    def test_durable_room_retry_refreshes_inventory_without_resettling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'accounts.sqlite3'
            store = AccountStore(path)
            store.connection.execute('INSERT INTO accounts VALUES(?,?,?)',('alice','alice',0))
            store.write('alice','UserParameter.json',{'Gold':10})
            store.connection.commit();store.close()
            calls = []
            def settle(saves,room,request,retire):
                calls.append('settled')
                value = saves.read('UserParameter.json');value['Gold'] += 5
                saves.write('UserParameter.json',value)
                return {}
            def render(saves,artifact,retire):
                return dict(Result={},RankingScore=None,Rewards=[],SpecialDrops=[],
                    RewardResult={'UserParameter':saves.read('UserParameter.json')})
            provider = DurableCompletionProvider(path,settle,render)
            rooms = Rooms(1)
            service = RoomService(rooms,SessionRegistry(),completion_provider=provider)
            room = service.create(player(),'ep','v',False,1,1,(60,3,20))[0]
            live = rooms.rooms[room['RoomId']]
            live['PreparedBattle'] = {'alice':dict(EpisodeToken='token',BattleId='battle')}
            live['GameOver'] = {1:1}
            request = dict(EpisodeToken='token',Playlog=native_playlog_hash('{}','token')+',{}',
                           ResultHash=native_result_hash('battle',True))
            self.assertEqual(service.complete_http('alice',request)['RewardResult']['UserParameter']['Gold'],15)
            store = AccountStore(path)
            store.write('alice','UserParameter.json',{'Gold':25})
            journal = store.read('alice',JOURNAL)
            store.connection.commit();store.close()
            response = service.complete_http('alice',request)
            self.assertEqual(response['RewardResult']['UserParameter']['Gold'],25)
            self.assertEqual(calls,['settled'])
            store = AccountStore(path)
            self.assertEqual(store.read('alice',JOURNAL),journal)
            store.connection.execute('DELETE FROM saves WHERE account_id=? AND name=?',('alice',JOURNAL))
            store.connection.commit();store.close()
            with self.assertRaises(ValueError): service.complete_http('alice',request)
            self.assertEqual(calls,['settled'])
            store = AccountStore(path)
            self.assertEqual(store.read('alice','UserParameter.json')['Gold'],25)
            self.assertFalse(store.exists('alice',JOURNAL));store.close()

    def test_playlog_exact_byte_signature_and_strict_json(self):
        raw = '{"characters":[],"pveLog":{"damagePer":0.5},"label":"a,b"}'
        signed = native_playlog_hash(raw,'token')+','+raw
        self.assertEqual(decode_pve_playlog(signed,'token')['label'],'a,b')
        for payload,token in ((signed,'other'),(signed+' ','token'),(raw,'token')):
            with self.assertRaises(ValueError): decode_pve_playlog(payload,token)
        for raw in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e999}','[]',
                    '{"x":9223372036854775808}', '{"x":'+ '['*65+'0'+']'*65+'}'):
            with self.assertRaises(ValueError):
                decode_pve_playlog(native_playlog_hash(raw,'token')+','+raw,'token')

    def test_native_result_hash_vectors_and_strict_inputs(self):
        self.assertEqual(native_result_hash('battle',False),
            '1b3c0d701343ae691871fc4089a5255c6bed06acac0a9b03a81f371d09d8dcc0')
        self.assertEqual(native_result_hash('battle',True),
            'af6aeb608703a363af57424d64888192bb9cbe35a488881a3c36cde020e72546')
        self.assertEqual(native_result_hash('',True),'')
        for battle,win in ((None,True),('battle',1),('☺',True)):
            with self.assertRaises(ValueError): native_result_hash(battle,win)

    def test_account_token_outcome_and_idempotent_detached_result(self):
        rooms = Rooms(2)
        provider = Mock(return_value=dict(Result={},RankingScore=None,Rewards=[],
                                         RewardResult={},SpecialDrops=[]))
        service = RoomService(rooms,SessionRegistry(),completion_provider=provider)
        room = service.create(player(),'ep','v',False,1,1,(60,3,20))[0]
        rooms.join(room['RoomId'],player('bob',1,False),'v')
        live = rooms.rooms[room['RoomId']]
        live['PreparedBattle'] = {account:dict(EpisodeToken='token-'+account,BattleId='battle')
                                 for account in ('alice','bob')}
        playlog = native_playlog_hash('{}','token-alice')+',{}'
        request = dict(EpisodeToken='token-alice',Playlog=playlog,ResultHash=native_result_hash('battle',True))
        for account,data in [('outsider',request),('bob',request),
                             ('alice',request | {'EpisodeToken':'wrong'}),
                             ('alice',request | {'EpisodeToken':'unicode-☺'})]:
            with self.assertRaises(RoomError): service.complete_http(account,data)
        with self.assertRaises(RoomError): service.complete_http('alice',request)
        provider.assert_not_called()
        live['GameOver'] = {1:1}
        with self.assertRaises(RoomError):
            service.complete_http('alice',request | {'ResultHash':native_result_hash('battle',False)})
        provider.assert_not_called()
        response = service.complete_http('alice',request)
        response['Rewards'].append('caller edit')
        self.assertEqual(service.complete_http('alice',request)['Rewards'],[])
        provider.assert_called_once()
        self.assertEqual(provider.call_args[0][0],'alice')
        self.assertEqual(provider.call_args[0][1]['PreparedBattle']['alice']['BattleId'],'battle')
        for changed in (request | {'Playlog':'changed'},request | {'ResultHash':'changed'}):
            with self.assertRaises(RoomError): service.complete_http('alice',changed)
        with self.assertRaises(RoomError):
            service.complete_http('alice',dict(EpisodeToken='token-alice',Playlog='opaque'),True)
        self.assertNotIn('bob',live['Completions'])

    def test_retire_failure_and_bounded_contract_do_not_record_completion(self):
        rooms = Rooms(1)
        provider = Mock(side_effect=ValueError('Invalid playlog'))
        service = RoomService(rooms,SessionRegistry(),completion_provider=provider)
        room = service.create(player(),'ep','v',False,1,1,(60,3,20))[0]
        live = rooms.rooms[room['RoomId']]
        live['PreparedBattle'] = {'alice':dict(EpisodeToken='token',BattleId='battle')}
        request = dict(EpisodeToken='token',Playlog=native_playlog_hash('{}','token')+',{}')
        with self.assertRaises(ValueError): service.complete_http('alice',request,True)
        self.assertNotIn('Completions',live)
        provider.side_effect = None
        provider.return_value = {'Result':{}}
        self.assertEqual(service.complete_http('alice',request,True),{'Result':{}})
        for invalid in (request | {'extra':1},request | {'Playlog':None},
                        request | {'EpisodeToken':''},request | {'Playlog':'x'*(2*1024*1024+1)}):
            with self.assertRaises(ValueError): completion_request('alice',invalid,True)
