import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_episode import RaidEpisodeLoader
from pve_events import EpisodeCatalog, ScheduledCatalog
from pve_preparation import InstalledBattleResponses
from pve_setup import installed_runtime_factory
from prizm_discovery import CatalogRoomViews
from prizm_room_service import RoomService
from prizm_rooms import Rooms, RoomError
from prizm_sessions import SessionRegistry
from test_prizm_lobby import player


EPISODE = 'PvE_Season001'


def catalog():
    now = datetime(2026,1,1,tzinfo=timezone.utc)
    links = [dict(EpisodePveEventId='link-'+str(index),EventId='event',EpisodeId=EPISODE,
                  RequiredPower=power,Difficulty=11+index,MinVerIOS='1.0.0',MinVerAndroid='1.0.0')
             for index,power in enumerate((0,3000,5000,10000))]
    return ScheduledCatalog(EpisodeCatalog(links,{EPISODE}),[
        dict(EventId='event',PublishStartAt=now,StartAt=now,EndAt=now+timedelta(days=1))],
        lambda:now)


class SharedArenaTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog()
        self.power = {}
        self.service = RoomService(Rooms(4),SessionRegistry(),event_catalog=self.catalog,
            eligibility_provider=lambda account:dict(Power=self.power.get(account,10000),
                Platform='android',ClientVersion='1.6.0'),
            room_settings_provider=lambda episode:dict(Mode=1,SuspendLimits=(60,3,20)))

    def test_four_links_preserve_canonical_wire_episode_and_distinct_difficulties(self):
        views = CatalogRoomViews(self.catalog,lambda *args:dict(IconUrl='',EmblemId='',
            IsFriend=False,IsGuild=False),lambda room:0)
        for index in range(4):
            room, _, _ = self.service.create_event(player('host-'+str(index)),
                                                  'link-'+str(index),'v',1)
            self.assertEqual(room['EpisodeId'],EPISODE)
            self.assertEqual(room['EpisodePveEventId'],'link-'+str(index))
            wire = views('viewer',room)
            self.assertEqual((wire['EpisodeId'],wire['Difficulty']),(EPISODE,11+index))
            found = self.service.discover('viewer',(EPISODE,),'v',event_context=('event',11+index))
            self.assertEqual([entry['RoomId'] for entry in found],[room['RoomId']])
        with self.assertRaises(ValueError):
            self.service.create_event(player('ambiguous'),EPISODE,'v',1)

    def test_weak_link_does_not_authorize_stronger_room_with_same_arena(self):
        hard, _, _ = self.service.create_event(player('host'),'link-3','v',1)
        self.power['guest'] = 0
        self.assertEqual(self.service.discover('guest',(EPISODE,),'v'),[])
        with self.assertRaises(RoomError):
            self.service.join_event(hard['RoomId'],player('guest'),'v',1,'event',14)
        with self.assertRaises(ValueError):
            self.service.create_event(player('guest'),'link-3','v',1)
        self.assertNotIn('guest',self.service.rooms.memberships)

    def test_start_retry_accepts_canonical_episode_but_rejects_another_binding(self):
        room, _, _ = self.service.create_event(player(),'link-1','v',1)
        current = self.service.rooms.rooms[room['RoomId']]
        current['PreparedBattle'] = {'alice':{'EpisodeToken':'unchanged-token'}}
        current['BattleRoster'] = {'alice':'pl001'}
        for identity in (EPISODE,'link-1'):
            self.assertEqual(self.service.start_http('alice',identity,'pl001',['alice'],['pl001']),
                             {'EpisodeToken':'unchanged-token'})
        with self.assertRaises(RoomError):
            self.service.start_http('alice','link-2','pl001',['alice'],['pl001'])
        self.assertEqual(current['PreparedBattle']['alice']['EpisodeToken'],'unchanged-token')

    def test_same_difficulty_weaker_duplicate_link_cannot_authorize_stronger_link(self):
        links = copy.deepcopy(self.catalog.episodes.links)
        links[3]['Difficulty'] = links[0]['Difficulty']
        episodes = EpisodeCatalog(links,{EPISODE})
        scheduled = ScheduledCatalog(episodes,[dict(EventId='event',PublishStartAt=self.catalog.clock(),
            StartAt=self.catalog.clock(),EndAt=self.catalog.clock()+timedelta(days=1))],self.catalog.clock)
        with self.assertRaises(ValueError):
            scheduled.eligible_link('link-3',0,'android','1.6.0')
        self.assertEqual(scheduled.eligible_event('link-0',0,'android','1.6.0'),('event',11))


class BindingLoaderTests(unittest.TestCase):
    def fixture(self, root):
        extracted = root/'extract/masterdata'
        extracted.mkdir(parents=True)
        (extracted/'EpisodeMasterDataObject.json').write_text(json.dumps({'Datas':[{'ID':EPISODE}]}))
        scenario = root/'masterdata/scenario'
        scenario.mkdir(parents=True)
        layout = root/'extract/masterdatadebug/episode/arena'
        layout.mkdir(parents=True)
        (layout/'EpisodeCheckPointMasterDataObject.json').write_text(
            json.dumps({'Datas':[dict(_startScenarioNo=0,PartyVisualIds=[''])]}))
        definitions = {}
        for index in range(4):
            scenario_id = 'difficulty-'+str(index)
            (scenario/(scenario_id+'.json')).write_text(json.dumps([
                dict(Id=scenario_id,ScenarioNo=1,ProgressType=1,Progress={'difficulty':index})]))
            definitions['link-'+str(index)] = dict(EpisodeId=EPISODE,ScenarioId=scenario_id,
                LayoutId='arena',EventDrops=[],EpisodeDetailUser={},LimitTime=300,BgmId='')
        return definitions

    def test_binding_selects_scenario_and_freezes_identity_without_replacing_native_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loader = RaidEpisodeLoader(root,self.fixture(root))
            builder = InstalledBattleResponses([],lambda identity:dict(settings=loader.visual_settings(identity),characters=[]),{},loader)
            prepared = SimpleNamespace(account_id='alice',save=lambda *args:[])
            with patch('pve_episode.fill_episode_layout_group_by_episode_id',return_value={'Enemies':[]}) as layout:
                for index in range(4):
                    room = dict(EpisodeId=EPISODE,EpisodePveEventId='link-'+str(index),BattleId='battle')
                    frozen = builder.for_room(room)
                    response = frozen(room,prepared,{})
                    self.assertEqual(response['EpisodeDetail']['Scenarios'][0]['EpisodeScenarioId'],
                                     'difficulty-'+str(index))
                    self.assertTrue(response['CharacterDetail']['baseVisual']['settings'][0]['Ids'])
                    with self.assertRaises(ValueError):
                        frozen(room | {'EpisodePveEventId':'link-'+str((index+1)%4)},prepared,{})
                self.assertTrue(all(call.args[0]==EPISODE for call in layout.call_args_list))

    def test_unknown_native_episode_fails_before_layout_or_client_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definitions = self.fixture(root)
            definitions['link-1']['EpisodeId'] = 'PvE_001_NORMAL'
            loader = RaidEpisodeLoader(root,definitions)
            with patch('pve_episode.fill_episode_layout_group_by_episode_id') as layout:
                with self.assertRaisesRegex(ValueError,'native EpisodeInfo'):
                    loader('link-1')
                layout.assert_not_called()
            with self.assertRaises(ValueError):
                loader.definition_key(dict(EpisodeId='wrong',EpisodePveEventId='link-0'))

    def test_factory_preflights_all_bindings_and_rejects_canonical_mismatch(self):
        scheduled = catalog()
        definitions = {'link-'+str(index):{'EpisodeId':EPISODE} for index in range(4)}
        assembler = SimpleNamespace(response_builder=Mock())
        reader = lambda *args:dict(Power=10000,Platform='android',ClientVersion='1.6.0')
        providers = dict(eligibility_provider=reader,room_settings_provider=reader,
            room_view_provider=reader,player_provider=reader,connection_provider=reader)
        with patch('pve_setup.installed_battle_assembler',return_value=assembler):
            installed_runtime_factory(4,'data','db',reader,definitions,{},scheduled,**providers)
            self.assertEqual(assembler.response_builder.for_room.call_count,4)
            for index,call in enumerate(assembler.response_builder.for_room.call_args_list):
                self.assertEqual(call.args[0],dict(EpisodeId=EPISODE,
                    EpisodePveEventId='link-'+str(index),BattleId='preflight'))
            prepared = SimpleNamespace(account_id='alice',character=lambda *args:dict(Power=10000))
            assembler.eligibility_validator(dict(EpisodeId=EPISODE,EpisodePveEventId='link-1',
                EventId='event',Difficulty=12),prepared,'pl001',None)
            with self.assertRaises(ValueError):
                assembler.eligibility_validator(dict(EpisodeId=EPISODE,EpisodePveEventId='link-1',
                    EventId='event',Difficulty=14),prepared,'pl001',None)
            definitions['link-1']['EpisodeId'] = 'unknown'
            with self.assertRaises(ValueError):
                installed_runtime_factory(4,'data','db',reader,definitions,{},scheduled,**providers)
            definitions['link-1'] = None
            with self.assertRaises(ValueError):
                installed_runtime_factory(4,'data','db',reader,definitions,{},scheduled,**providers)


if __name__ == '__main__':
    unittest.main()
