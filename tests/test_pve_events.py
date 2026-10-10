import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_events import EpisodeCatalog, ScheduledCatalog
from datetime import datetime, timezone, timedelta


class EventTests(unittest.TestCase):
    def test_event_rollover_does_not_reassign_existing_rooms(self):
        from prizm_room_service import RoomService
        from prizm_rooms import Rooms, RoomError
        from prizm_sessions import SessionRegistry
        from test_prizm_lobby import player
        start = datetime(2026,1,1,tzinfo=timezone.utc)
        now = [start]
        links = [self.link() | dict(EventId=event,EpisodePveEventId=event)
                 for event in ('old','new')]
        catalog = ScheduledCatalog(EpisodeCatalog(links,{'episode'}),[
            dict(EventId=event,PublishStartAt=start,StartAt=start+timedelta(hours=index),
                 EndAt=start+timedelta(hours=index+1))
            for index,event in enumerate(('old','new'))],lambda:now[0])
        service = RoomService(Rooms(2),SessionRegistry(),event_catalog=catalog,
            eligibility_provider=lambda account:dict(Power=100,Platform='android',ClientVersion='1.6.0'),
            room_settings_provider=lambda episode:dict(Mode=1,SuspendLimits=(60,3,20)),
            room_view_provider=lambda account,room:room)
        old = service.create_event(player('old-host'),'episode','v',1)[0]
        self.assertEqual((old['EventId'],old['Difficulty']),('old',2))
        now[0] = start+timedelta(hours=1)
        self.assertEqual(service.discover_event('viewer','new',2,'v'),[])
        with self.assertRaises(RoomError): service.info_event('viewer','new',old['RoomId'],'v')
        with self.assertRaises(RoomError):
            service.join_event(old['RoomId'],player('guest'),'v',3,'new',2)
        self.assertNotIn('guest',service.rooms.memberships)
        new = service.create_event(player('new-host'),'episode','v',1)[0]
        self.assertEqual([room['RoomId'] for room in service.discover_event('viewer','new',2,'v')],
                         [new['RoomId']])
        matched = service.match_event(player('guest'),'v','new',2)[0]
        self.assertEqual(matched['RoomId'],new['RoomId'])
        self.assertEqual(service.rooms.rooms[old['RoomId']]['EventId'],'old')

    def link(self):
        return dict(EpisodePveEventId='link',EventId='event',EpisodeId='episode',
                    RequiredPower=100,Difficulty=2,MinVerIOS='1.6.0',MinVerAndroid='1.5.0')

    def test_runtime_admission_rechecks_current_schedule_and_server_owned_power(self):
        from prizm_room_service import RoomService
        from prizm_rooms import Rooms, RoomError
        from prizm_sessions import SessionRegistry
        from test_prizm_lobby import player
        start = datetime(2026,1,1,tzinfo=timezone.utc)
        now = [start-timedelta(seconds=1)]
        catalog = ScheduledCatalog(EpisodeCatalog([self.link()],{'episode'}),[
            dict(EventId='event',PublishStartAt=start,StartAt=start,EndAt=start+timedelta(hours=1))],lambda:now[0])
        eligibility = dict(Power=99,Platform='android',ClientVersion='1.5.0')
        rooms = Rooms(3)
        service = RoomService(rooms,SessionRegistry(),event_catalog=catalog,
                              eligibility_provider=lambda account:dict(eligibility),
                              room_settings_provider=lambda episode:dict(Mode=1,SuspendLimits=(60,3,20)))
        room = service.create(player('host'),'episode','v',False,1,1,(60,3,20))[0]
        with self.assertRaises(RoomError): service.match_event(player('bob'),'v','event',2)
        now[0] = start
        with self.assertRaises(RoomError): service.match_event(player('bob'),'v','event',2)
        with self.assertRaises(ValueError): service.create_event(player('new-host'),'episode','v',1)
        eligibility['Power'] = 100
        service.player_provider = player
        service.connection_provider = lambda room,tcp,udp:dict(RoomId='wrong',JwtTcp=tcp,JwtUdp=udp,SearchId='search',Tcp='localhost:1234',Udp='localhost:1235')
        with self.assertRaises(RoomError): service.create_http('failed-host','episode','v',1)
        self.assertNotIn('failed-host',rooms.memberships)
        self.assertFalse(any(value[0].account_id == 'failed-host' for value in service.registry.credentials.values()))
        service.connection_provider = lambda room,tcp,udp:dict(RoomId=room['RoomId'],JwtTcp=tcp,JwtUdp=udp,SearchId='search',Tcp='localhost:1234',Udp='localhost:1235')
        response = service.create_http('http-host','episode','v',1)['Prizm']
        self.assertEqual(service.registry.open(response['JwtTcp']).admission.account_id,'http-host')
        created = service.create_event(player('new-host'),'episode','v',2)[0]
        self.assertTrue(created['IsPrivate'])
        with self.assertRaises(RoomError): service.create_event(player('guild-host'),'episode','v',3)
        service.room_view_provider = lambda viewer,snapshot:dict(RoomId=snapshot['RoomId'],
            HostUserId=next(p['UserId'] for p in snapshot['Players'] if p['IsHost']))
        self.assertEqual(service.info_event('bob','event',room['RoomId'],'v')['HostUserId'],'host')
        with self.assertRaises(RoomError): service.info_event('bob','other',room['RoomId'],'v')
        with self.assertRaises(RoomError): service.info_event('bob','event',room['RoomId'],'other')
        admitted = service.match_event(player('bob'),'v','event',2)
        self.assertEqual(admitted[0]['RoomId'],room['RoomId'])
        now[0] = start+timedelta(hours=1)
        with self.assertRaises(RoomError):
            service.join_event(room['RoomId'],player('celia'),'v',3,'event',2)
        self.assertNotIn('celia',rooms.memberships)
        with self.assertRaises(RoomError): service.info_event('bob','event',room['RoomId'],'v')
        with self.assertRaises(ValueError): service.create_event(player('late-host'),'episode','v',1)
        self.assertNotIn('late-host',rooms.memberships)

    def test_publication_and_battle_windows_have_distinct_boundaries(self):
        start = datetime(2026,1,1,tzinfo=timezone.utc)
        now = [start-timedelta(hours=2)]
        event = dict(EventId='event',PublishStartAt=start-timedelta(hours=1),
                     StartAt=start,EndAt=start+timedelta(hours=1))
        catalog = ScheduledCatalog(EpisodeCatalog([self.link()],{'episode'}),[event],lambda:now[0])
        self.assertEqual(catalog.published_event_ids(),())
        now[0] = event['PublishStartAt']
        self.assertEqual(catalog.published_event_ids(),('event',))
        self.assertEqual(catalog.episode_scope('event',2,100,'android','1.5.0'),())
        now[0] = start
        self.assertEqual(catalog.episode_scope('event',2,100,'android','1.5.0'),('episode',))
        now[0] = event['EndAt']
        self.assertEqual(catalog.episode_scope('event',2,100,'android','1.5.0'),())
        self.assertEqual(catalog.published_event_ids(),('event',))
        event['EndAt'] = start+timedelta(days=100)
        self.assertEqual(catalog.episode_scope('event',2,100,'android','1.5.0'),())

    def test_scope_filters_event_difficulty_power_and_platform_version(self):
        row = self.link()
        catalog = EpisodeCatalog([row],{'episode'})
        row['RequiredPower'] = 0
        self.assertEqual(catalog.episode_scope('event',2,100,'android','1.5.0'),('episode',))
        for event,difficulty,power,platform,version in [
                ('other',2,100,'android','1.5.0'),('event',1,100,'android','1.5.0'),
                ('event',2,99,'android','1.5.0'),('event',2,100,'ios','1.5.0')]:
            self.assertEqual(catalog.episode_scope(event,difficulty,power,platform,version),())

    def test_uninstalled_or_duplicate_links_and_invalid_versions_rejected(self):
        with self.assertRaises(ValueError): EpisodeCatalog([self.link()],set())
        with self.assertRaises(ValueError): EpisodeCatalog([self.link(),self.link()],{'episode'})
        catalog = EpisodeCatalog([self.link()],{'episode'})
        with self.assertRaises(ValueError): catalog.episode_scope('event',2,100,'android','bad')
