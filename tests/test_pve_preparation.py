import sys
import unittest
from pathlib import Path
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pve_preparation import BattleAssembler, InstalledBattleResponses, prepared_enemy_spawns, PreparedEnemySpawns
from pve_stats import PreparedCombatStats, PartyCharacterPresentation


class AssemblyTests(unittest.TestCase):
    def test_external_enemy_definitions_with_null_children_keep_spawn_authorization(self):
        room = dict(Players=[dict(UserId='alice',IsHost=True)],
            PreparedBattle={'alice':dict(EpisodeDetail={'LayoutGroup':{'Enemies':[
                dict(EpisodeEnemyId='generator',EnemyId='boss',Child={'Ids':[]}),
                dict(EpisodeEnemyId='Ext.generator.minion',EnemyId='minion',Child=None)]}},
                MasterGroup={'enemyIndividuals':[dict(Index='boss'),dict(Index='minion')]})})
        policy = PreparedEnemySpawns()
        self.assertTrue(policy.authorize('alice',room,'generator'))
        self.assertTrue(policy.authorize('alice',room,'Ext.generator.minion'))
        self.assertFalse(policy.authorize('alice',room,'Ext.generator.unknown'))
        self.assertFalse(policy.authorize('alice',room,'Ext.Ext.generator.minion.minion'))

    def test_dynamic_enemy_identity_requires_declared_links_and_host(self):
        policy = PreparedEnemySpawns()
        individuals = [dict(Index='boss',TransformConditions=1,TransformId='phase2',
                            SummonEnemyIndividualIds=['minion']),
                       dict(Index='phase2',TransformConditions=0,TransformId='',
                            SummonEnemyIndividualIds=['minion']),
                       dict(Index='minion',TransformConditions=0,TransformId='',
                            SummonEnemyIndividualIds=[]), dict(Index='unrelated')]
        room = dict(Players=[dict(UserId='alice',IsHost=True),dict(UserId='bob',IsHost=False)],
            PreparedBattle={'alice':dict(EpisodeDetail={'LayoutGroup':{'Enemies':[
                dict(EpisodeEnemyId='spawn',EnemyId='boss',Child={'Ids':['minion']})]}},
                MasterGroup={'enemyIndividuals':individuals})})
        for identity in ('spawn','Ext.spawn/phase2','Ext.spawn+minion',
                         'Ext.Ext.spawn/phase2+minion','Ext.spawn.minion',
                         'Ext.Ext.spawn/phase2.minion'):
            self.assertTrue(policy.authorize('alice',room,identity),identity)
            self.assertFalse(policy.authorize('bob',room,identity))
        for identity in ('boss','Ext.spawn/unrelated','Ext.spawn+unrelated',
                         'Ext.spawn/minion','Ext.Ext.spawn+minion/phase2',
                         'Ext.unknown+minion','Ext.spawn+','Ext.spawn.unrelated',
                         'Ext.Ext.spawn.minion.minion','Ext.'*40+'spawn/phase2'):
            self.assertFalse(policy.authorize('alice',room,identity),identity)
        individuals[0]['TransformConditions'] = 0
        self.assertFalse(policy.authorize('alice',room,'Ext.spawn/phase2'))

    def test_enemy_spawns_use_frozen_layout_identity_and_host_authority(self):
        layout = [dict(EpisodeEnemyId='spawn',EnemyId='master')]
        room = dict(Players=[dict(UserId='alice',IsHost=True),dict(UserId='bob',IsHost=False)],
                    PreparedBattle={'alice':{'EpisodeDetail':{'LayoutGroup':{'Enemies':layout}}}})
        self.assertEqual(prepared_enemy_spawns('alice',room),frozenset({'spawn'}))
        self.assertEqual(prepared_enemy_spawns('bob',room),frozenset())
        self.assertEqual(prepared_enemy_spawns('outsider',room),frozenset())
        allowed = prepared_enemy_spawns('alice',room)
        layout.append(dict(EpisodeEnemyId='later',EnemyId='another'))
        self.assertEqual(allowed,frozenset({'spawn'}))
        layout.append(dict(EpisodeEnemyId='spawn'))
        with self.assertRaises(ValueError): prepared_enemy_spawns('alice',room)

    def test_costume_replacement_uses_cloned_owned_row_and_preserves_saved_identity(self):
        saved = dict(CharacterId='base', Level=2, Exp=42,
                     VisualEquipment=['costume', 'weapon'])
        class Calculator:
            def character(self, character, rows, equipment, ordering, overrides):
                assert character == 'replacement'
                alias = next(row for row in rows if row['CharacterId'] == character)
                assert alias['BaseCharacterId'] == 'base'
                return {'Hp':(overrides or {}).get(character, alias['Level']) * 100,
                        'Attack':20, 'Defense':10}
        class Snapshots:
            def prepare(self, account):
                return PreparedCombatStats(Calculator(), account,
                    {'UserCharacter.json':[saved], 'UserEquipment.json':[]}, [])
        presentation = PartyCharacterPresentation(
            [dict(CharacterId=key, UniqueParamData='{}') for key in ('base','replacement')],
            ['costume','weapon'], [dict(EquipmentId='costume',ReplaceCharacterId='replacement')])
        def response(room, prepared, play):
            self.assertEqual(prepared.save('alice','UserCharacter.json'),[saved])
            return {'EpisodeDetailUser':{}}
        room = {'Players':[dict(UserId='alice',CharacterId='base')]}
        assembler = BattleAssembler(Snapshots(),presentation,response,
                                    lambda room, prepared:{'base':3})
        checked = []
        assembler.eligibility_validator = lambda room,prepared,character,overrides: checked.append(
            (prepared.account_id,character,overrides['replacement']))
        result = assembler(room)
        self.assertEqual(checked,[('alice','replacement',3)])
        character = result.characters['alice']
        self.assertEqual((character[1],character[2],character[4],character[5],character[6]),
                         ('replacement','replacement',3,42,300))
        self.assertEqual(result.identities,{'alice':('base','replacement')})
        self.assertEqual(result.responses['alice']['EpisodeDetailUser']['playCharacters'][0]['characterId'],
                         'replacement')
        self.assertEqual(saved['CharacterId'],'base')

    def test_installed_responses_keep_user_data_scoped_and_tokens_distinct(self):
        definition = dict(EnemyDetail={'Enemies':[]}, EpisodeDetail={'Scenarios':[]},
                          EpisodeDetailUser={'status':0}, LimitTime=300, BgmId='raid')
        builder = InstalledBattleResponses([], {'settings':[], 'characters':[]}, {},
                                           lambda episode:definition)
        class Prepared:
            def __init__(self, account): self.account_id = account
            def save(self, account, name):
                self_account = self.account_id
                if account != self_account: raise ValueError('Wrong account')
                return [dict(owner=account, document=name)]
        room = {'EpisodeId':'raid', 'BattleId':'shared'}
        bound = builder.for_room(room)
        definition['BgmId'] = 'changed-after-preparation'
        responses = [bound(room,Prepared(account),{'characterId':'hero'})
                     for account in ('alice','bob')]
        self.assertEqual([r['BgmId'] for r in responses], ['raid','raid'])
        with self.assertRaises(ValueError):
            bound(room | {'BattleId':'another'},Prepared('alice'),{'characterId':'hero'})
        self.assertEqual([r['BattleId'] for r in responses], ['shared','shared'])
        self.assertNotEqual(responses[0]['EpisodeToken'],responses[1]['EpisodeToken'])
        for account,response in zip(('alice','bob'),responses):
            for key in ('userCharacters','userEquipments','userItems'):
                self.assertEqual(response['CharacterDetail'][key][0]['owner'],account)
        responses[0]['EpisodeDetail']['Scenarios'].append('changed')
        self.assertEqual(responses[1]['EpisodeDetail']['Scenarios'],[])
        self.assertEqual(definition['EpisodeDetailUser'],{'status':0})

    def test_http_and_transport_share_one_frozen_snapshot_per_account(self):
        class Calculator:
            def character(self, character, rows, equipment, ordering, overrides):
                return {'Hp':rows[0]['Level'] * 100, 'Attack':20, 'Defense':10}
        class Snapshots:
            calls = []
            def prepare(self, account):
                self.calls.append(account)
                return PreparedCombatStats(Calculator(), account,
                    {'UserCharacter.json':[dict(CharacterId='hero', Level=2, Exp=42)],
                     'UserEquipment.json':[]}, [])
        class Presentation:
            def character(self, character):
                return dict(MasterDataId=character, CharacterName=None,
                            VisualEquipments=['costume','weapon'])
        snapshots = Snapshots()
        def response(room, prepared, play):
            # A response builder can read further fields from the same snapshot.
            self.assertEqual(prepared.save(prepared.account_id,'UserCharacter.json')[0]['Exp'],42)
            play['hp'] = -1
            return {'EpisodeDetailUser':{'playCharacters':[], 'startScenarioNo':1}}
        room = {'Players':[dict(UserId=name, CharacterId='hero') for name in ('alice','bob')]}
        original = deepcopy(room)
        result = BattleAssembler(snapshots, Presentation(), response)(room)
        self.assertEqual(snapshots.calls, ['alice','bob'])
        self.assertEqual(room, original)
        for account in ('alice','bob'):
            play = result.responses[account]['EpisodeDetailUser']['playCharacters'][0]
            character = result.characters[account]
            self.assertEqual((play['hp'], play['sp'], play['level'], play['exp']),
                             (character[6], character[7], character[4], character[5]))
            self.assertEqual(play['hp'],200)
        result.characters['alice'][8].clear()
        self.assertEqual(result.characters['bob'][8], ['costume','weapon'])


if __name__ == '__main__':
    unittest.main()
