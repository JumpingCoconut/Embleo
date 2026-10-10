import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
from pve_episode import RaidEpisodeLoader, raid_enemy_detail


class EpisodeLoaderTests(unittest.TestCase):
    def test_visual_timeline_uses_selected_layout_and_rejects_empty_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = root / 'extract/masterdatadebug/episode/layout'
            layout.mkdir(parents=True)
            source = layout / 'EpisodeCheckPointMasterDataObject.json'
            source.write_text(json.dumps({'Datas':[
                dict(_startScenarioNo=20,PartyVisualIds=['later']),
                dict(_startScenarioNo=0,PartyVisualIds=['','',''])]}),encoding='utf-8')
            loader = RaidEpisodeLoader(root,{'raid':dict(LayoutId='layout')})
            self.assertEqual(loader.visual_settings('raid'),[
                dict(ScenarioNo=0,Ids=['','','']),dict(ScenarioNo=20,Ids=['later'])])
            source.write_text('{"Datas":[]}',encoding='utf-8')
            with self.assertRaises(ValueError):
                loader.visual_settings('raid')

    def test_difficulty_individual_override_preserves_spawn_and_updates_enemy_detail(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = root/'masterdata/scenario'
            scenario.mkdir(parents=True)
            (scenario/'scenario.json').write_text(json.dumps([dict(Id='cp',ScenarioNo=1,
                ProgressType=1,Progress={})]),encoding='utf-8')
            (root/'masterdata/EnemyIndividualMasterData.json').write_text(
                json.dumps([{'Index':'easy'},{'Index':'hard'}]),encoding='utf-8')
            original = {'Enemies':[dict(EpisodeEnemyId='spawn',EnemyId='easy',Child={'Ids':['child']})]}
            definition = dict(ScenarioId='scenario',LayoutId='layout',EventDrops=[],
                EpisodeDetailUser={},LimitTime=300,BgmId='',EnemyIndividuals={'spawn':'hard'})
            with patch('pve_episode.fill_episode_layout_group_by_episode_id',return_value=original):
                result = RaidEpisodeLoader(root,{'raid':definition})('raid')
                self.assertEqual(result['EpisodeDetail']['LayoutGroup']['Enemies'][0]['EpisodeEnemyId'],'spawn')
                self.assertEqual(result['EnemyDetail']['Enemies'],[{'EnemyId':'hard'},{'EnemyId':'child'}])
                self.assertEqual(original['Enemies'][0]['EnemyId'],'easy')
                for overrides in ({'missing':'hard'},{'spawn':'unknown'},{'spawn':True},[]):
                    with self.assertRaises(ValueError):
                        RaidEpisodeLoader(root,{'raid':definition | {'EnemyIndividuals':overrides}})('raid')

    def test_location_master_identity_is_distinct_from_playable_episode_and_layout(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = root/'masterdata/scenario'
            scenario.mkdir(parents=True)
            (scenario/'scenario.json').write_text(json.dumps([dict(Id='cp',ScenarioNo=1,
                ProgressType=1,Progress={})]),encoding='utf-8')
            definition = dict(ScenarioId='scenario',LayoutId='layout',LocationEpisodeId='location-master',
                EventDrops=[],EpisodeDetailUser={},LimitTime=300,BgmId='')
            with patch('pve_episode.fill_episode_layout_group_by_episode_id',
                       return_value={'Enemies':[]}) as layout:
                RaidEpisodeLoader(root,{'playable':definition})('playable')
                layout.assert_called_once_with('playable',data_root=root.resolve(),
                    layout_id='layout',location_episode_id='location-master')
            for invalid in ('',None,True):
                with self.assertRaises(ValueError):
                    RaidEpisodeLoader(root,{'playable':definition | {'LocationEpisodeId':invalid}})('playable')

    def test_gimmick_dependencies_use_explicit_data_root(self):
        from scripts.adapt.episode_data.gimmicks import adapt_gimmicks_for_episode_layout
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extracted = root / 'extract/masterdata'
            extracted.mkdir(parents=True)
            (root / 'masterdata').mkdir()
            for filename in ('EpisodeMasterDataObject.json','StageLocationMasterDataObject.json'):
                (extracted / filename).write_text(json.dumps({'Datas':[]}),encoding='utf-8')
            (root / 'masterdata/StageOptionGimmickMasterData.json').write_text('{"Datas":[]}',encoding='utf-8')
            self.assertEqual(adapt_gimmicks_for_episode_layout({'Datas':[]},'raid',data_root=root),[])

    def test_enemy_detail_includes_children_without_empty_or_duplicate_ids(self):
        layout = {'Enemies':[{'EnemyId':'boss','Child':{'Ids':['child','', 'boss']},
                              'SummonRule':{'EpisodeEnemyId':'summon-only'}},
                              {'EnemyId':'child','Child':None,'SummonRule':None}]}
        self.assertEqual(raid_enemy_detail(layout),
                         {'Enemies':[{'EnemyId':'boss'},{'EnemyId':'child'},{'EnemyId':'summon-only'}]})
        with self.assertRaises(ValueError):
            raid_enemy_detail({'Enemies':[{'EnemyId':True}]})
        with self.assertRaises(ValueError):
            raid_enemy_detail({'Enemies':[{'EnemyId':'boss','SummonRule':{'EpisodeEnemyId':True}}]})

    def test_distinct_scenario_and_layout_mapping_preserves_combat_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = root / 'masterdata/scenario'
            scenario.mkdir(parents=True)
            layout = root / 'extract/masterdatadebug/episode/layout'
            layout.mkdir(parents=True)
            entries = [dict(Id='fight',ScenarioNo=2,ProgressType=3,
                            Progress={'ProgressKillId':'fight'}),
                       dict(Id='checkpoint',ScenarioNo=1,ProgressType=1,
                            Progress={'RequestSave':True})]
            file = scenario / 'scenario.json'
            file.write_text(json.dumps(entries),encoding='utf-8')
            definition = dict(ScenarioId='scenario',LayoutId='layout',EventDrops=[],
                              EnemyDetail={'Enemies':[]},EpisodeDetailUser={'status':0},
                              LimitTime=300,BgmId='music')
            loader = RaidEpisodeLoader(root,{'raid':definition})
            result = loader('raid')
            detail = result['EpisodeDetail']
            self.assertEqual([row['ScenarioNo'] for row in detail['Scenarios']],[2,1])
            self.assertEqual(detail['ScenarioGroup']['Kills'],[entries[0]['Progress']])
            result['EpisodeDetailUser']['status'] = 99
            self.assertEqual(loader('raid')['EpisodeDetailUser']['status'],0)
            self.assertEqual(definition['EpisodeDetailUser']['status'],0)
            with self.assertRaises(ValueError): loader('unknown')
            for key,value in (('ScenarioId','../outside'),('LayoutId','../outside')):
                bad = RaidEpisodeLoader(root,{'raid':definition | {key:value}})
                with self.assertRaises(ValueError): bad('raid')
            for invalid in ([], entries + [entries[0]], [entries[0] | {'ProgressType':True}],
                            [entries[0] | {'ScenarioNo':True}], [entries[0] | {'Progress':[]} ]):
                file.write_text(json.dumps(invalid),encoding='utf-8')
                with self.assertRaises(ValueError): loader('raid')


if __name__ == '__main__':
    unittest.main()
