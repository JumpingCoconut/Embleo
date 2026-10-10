import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from accounts import AccountStore
from pve_results import DurableCompletionProvider,NativeCompletionRenderer,JOURNAL


class DurableResultsTests(unittest.TestCase):
    def test_render_failure_rolls_back_saves_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'accounts.sqlite3'
            store = AccountStore(path)
            store.connection.execute('INSERT INTO accounts VALUES(?,?,?)',('alice','alice',0))
            store.write('alice','UserParameter.json',{'Gold':10})
            store.connection.commit();store.close()
            room = {'PreparedBattle':{'alice':dict(EpisodeToken='token',BattleId='battle')}}
            request = dict(EpisodeToken='token',Playlog='opaque',ResultHash='hash')
            def settle(saves,room,request,retire):
                value = saves.read('UserParameter.json');value['Gold'] += 5
                saves.write('UserParameter.json',value)
                return {'Outcome':1}
            def forbidden_render(saves,artifact,retire):
                saves.write('UserParameter.json',{'Gold':999})
            def malformed_render(saves,artifact,retire):
                return {'Result':{}}
            for render in (forbidden_render,malformed_render):
                with self.assertRaises(ValueError):
                    DurableCompletionProvider(path,settle,render)('alice',room,request,False)
                store = AccountStore(path)
                self.assertEqual(store.read('alice','UserParameter.json')['Gold'],10)
                self.assertFalse(store.exists('alice',JOURNAL));store.close()
            def render(saves,artifact,retire):
                return dict(Result=artifact,RankingScore=None,Rewards=[],SpecialDrops=[],RewardResult={})
            DurableCompletionProvider(path,settle,render)('alice',room,request,False)
            store = AccountStore(path)
            self.assertEqual(store.read('alice','UserParameter.json')['Gold'],15)
            self.assertIn('battle',store.read('alice',JOURNAL)['Battles']);store.close()

    def test_atomic_settlement_replay_concurrency_and_other_account_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'accounts.sqlite3'
            store = AccountStore(path)
            for account,gold in (('alice',10),('bob',20)):
                store.connection.execute('INSERT INTO accounts VALUES(?,?,?)',(account,account,0))
                store.write(account,'UserParameter.json',{'Gold':gold,'unknown':{'keep':True}})
            store.connection.commit();store.close()
            calls = []
            def settle(saves,room,request,retire):
                calls.append('settled')
                value = saves.read('UserParameter.json');value['Gold'] += 5
                saves.write('UserParameter.json',value)
                return dict(Outcome=1,RankingScore=None,Rewards=[],SpecialDrops=[])
            def projection(saves):
                return dict(User={'id':'alice'},UserParameter=saves.read('UserParameter.json'),
                    HcBalance={},UserPresents=[],UserItems=[],UserEquipments=[],UserTickets=[],
                    UserStampBadge=[],UserCharacters=[],UserEventSkits=[],UserPanelMissions=[])
            render = NativeCompletionRenderer(projection)
            room = {'PreparedBattle':{'alice':dict(EpisodeToken='token',BattleId='battle')}}
            request = dict(EpisodeToken='token',Playlog='opaque',ResultHash='hash')
            provider = DurableCompletionProvider(path,settle,render)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda unused:provider('alice',room,request,False),range(2)))
            self.assertEqual(len(calls),1)
            self.assertEqual(results[0],results[1])
            restarted = DurableCompletionProvider(path,settle,render)
            self.assertEqual(restarted('alice',room,request,False),results[0])
            self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError): restarted('alice',room,request | {'Playlog':'different'},False)
            store = AccountStore(path)
            self.assertEqual(store.read('alice','UserParameter.json'),{'Gold':15,'unknown':{'keep':True}})
            self.assertEqual(store.read('bob','UserParameter.json'),{'Gold':20,'unknown':{'keep':True}})
            self.assertNotIn('opaque',json.dumps(store.read('alice',JOURNAL)))
            self.assertFalse(store.exists('bob',JOURNAL));store.close()
            def fail(saves,room,request,retire):
                value = saves.read('UserParameter.json');value['Gold'] = 999
                saves.write('UserParameter.json',value)
                raise ValueError('Invalid completion')
            fresh = {'PreparedBattle':{'alice':dict(EpisodeToken='token',BattleId='next')}}
            with self.assertRaises(ValueError):
                DurableCompletionProvider(path,fail,render)('alice',fresh,request,False)
            store = AccountStore(path)
            self.assertEqual(store.read('alice','UserParameter.json')['Gold'],15)
            self.assertNotIn('next',store.read('alice',JOURNAL)['Battles'])
            # Another completed action changes inventory before the old battle retries.
            value = store.read('alice','UserParameter.json');value['Gold'] = 25
            store.write('alice','UserParameter.json',value)
            store.connection.commit();store.close()
            replay = restarted('alice',room,request,False)
            self.assertEqual(replay['Result']['Parameter']['Gold'],25)
            self.assertEqual(replay['RewardResult']['UserParameter']['Gold'],25)
            self.assertEqual(len(calls),1)
            replay['Result']['Reward']['UserParameter']['Gold'] = 999
            self.assertEqual(replay['RewardResult']['UserParameter']['Gold'],25)
