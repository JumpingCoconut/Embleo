import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_discovery import room_view, room_access, CatalogRoomViews
from prizm_rooms import Rooms
from test_prizm_lobby import player


class DiscoveryTests(unittest.TestCase):
    def test_reused_episode_uses_active_event_not_historical_difficulty(self):
        from datetime import datetime, timezone, timedelta
        from pve_events import EpisodeCatalog, ScheduledCatalog
        start = datetime(2026,1,1,tzinfo=timezone.utc)
        now = [start]
        links = [dict(EpisodePveEventId=event,EventId=event,EpisodeId='ep',
            RequiredPower=power,Difficulty=difficulty,MinVerIOS='1.0.0',MinVerAndroid='1.0.0')
            for event,power,difficulty in [('old',100,1),('new',200,2)]]
        catalog = ScheduledCatalog(EpisodeCatalog(links,{'ep'}),[
            dict(EventId='old',PublishStartAt=start-timedelta(days=2),
                StartAt=start-timedelta(days=1),EndAt=start),
            dict(EventId='new',PublishStartAt=start,StartAt=start,EndAt=start+timedelta(days=1))],
            lambda:now[0])
        views = CatalogRoomViews(catalog,lambda *args:dict(
            IconUrl='',EmblemId='',IsFriend=False,IsGuild=False),lambda room:1234)
        room = Rooms(2).create(player(),'ep','v',False,1,1,(60,3,20))
        self.assertEqual(catalog.published_event_ids(),('old','new'))
        self.assertEqual(catalog.active_event_ids(),('new',))
        self.assertEqual(views('alice',room)['Difficulty'],2)
        self.assertEqual(views('alice',room)['RequiredPower'],200)
        now[0] = start-timedelta(seconds=1)
        self.assertEqual(views('alice',room)['Difficulty'],1)
        now[0] = start+timedelta(days=1)
        with self.assertRaises(ValueError): views('alice',room)

    def test_catalog_view_resolves_current_host_and_unselected_character(self):
        from types import SimpleNamespace
        catalog = SimpleNamespace(episodes=SimpleNamespace(links=[
            dict(EpisodeId='ep',RequiredPower=100,Difficulty=2)]))
        reads = []
        def display(viewer,host,character):
            reads.append((viewer,host,character))
            return dict(IconUrl='icon',EmblemId='emblem',IsFriend=False,IsGuild=False)
        views = CatalogRoomViews(catalog,display,lambda room:1234)
        room = Rooms(2).create(player(),'ep','v',False,1,1,(60,3,20))
        result = views('bob',room)
        self.assertEqual((result['RequiredPower'],result['Difficulty'],result['HostCharacterId']),
                         (100,2,'pl001'))
        room['Players'][0].update(CharacterId='',CharacterLevel=0)
        self.assertEqual(views('bob',room)['HostCharacterId'],'')
        self.assertEqual(reads[-1],('bob','alice',''))
        catalog.episodes.links.clear()
        self.assertEqual(views('bob',room)['Difficulty'],2)
        with self.assertRaises(ValueError): views('bob',room | {'EpisodeId':'unknown'})

    def test_visibility_policy_uses_route_and_server_resolved_guilds(self):
        for route in (1,2,3):
            self.assertTrue(room_access({'PublicLevel':1},route,None,None))
            self.assertEqual(room_access({'PublicLevel':2},route,None,None),route == 3)
            self.assertTrue(room_access({'PublicLevel':3},route,'guild','guild'))
            for viewer,host in [(None,None),('',''),('a','b'),('guild',None)]:
                self.assertFalse(room_access({'PublicLevel':3},route,viewer,host))
        for level,route in [(0,1),(4,1),(True,1),(1,True),(1,0),(1,4)]:
            self.assertFalse(room_access({'PublicLevel':level},route,None,None))

    def test_http_view_tracks_authoritative_host_handover_and_count(self):
        rooms = Rooms(2)
        room = rooms.create(player(),'ep','v',False,0,1,(60,3,20))
        room_id = room['RoomId']
        room = rooms.join(room_id,player('bob',1,False),'v')
        def view(snapshot):
            return room_view(snapshot,100,2,'icon','emblem',False,True,1234)
        self.assertEqual(view(room),dict(RoomId=room_id,EpisodeId='ep',RequiredPower=100,
            Difficulty=2,HostUserId='alice',HostCharacterId='pl001',HostName='Alice',
            HostLevel=10,IconUrl='icon',EmblemId='emblem',Count=2,IsFriend=False,
            IsGuild=True,ExpireAt=1234))
        remaining = rooms.leave('alice',room_id)
        result = view(remaining)
        self.assertEqual((result['HostUserId'],result['Count']),('bob',1))
        self.assertNotIn('Players',result)
        self.assertNotIn('PveVersion',result)

    def test_requires_valid_event_and_profile_metadata(self):
        room = Rooms(2).create(player(),'ep','v',False,0,1,(60,3,20))
        values = [100,2,'icon','emblem',False,False,1234]
        for index,bad in [(0,True),(1,-1),(2,None),(4,1),(6,1.5),(6,2**63)]:
            args = values.copy()
            args[index] = bad
            with self.subTest(index=index),self.assertRaises(ValueError): room_view(room,*args)
        room['Players'][0]['IsHost'] = False
        with self.assertRaises(ValueError): room_view(room,*values)
