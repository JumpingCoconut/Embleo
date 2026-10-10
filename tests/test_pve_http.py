import asyncio
import sys
import unittest
from concurrent.futures import Future, TimeoutError
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pve_http import PveHttp
from pve_events import EpisodeCatalog, ScheduledCatalog
from prizm_runtime import Runtime
from prizm_discovery import room_view
from prizm_admission import admission_payload
from prizm_rooms import RoomError
from test_prizm_lobby import player


class HttpRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_is_scoped_to_current_membership_and_revoked_on_leave(self):
        runtime = Runtime(2)
        runtime.listener.start = AsyncMock(return_value=['socket'])
        await runtime.start('localhost',1234,None)
        try:
            room = (await asyncio.wrap_future(runtime.control.submit(
                'create',player(),'episode','v',False,1,1,(60,3,20))))[0]
            adapter = PveHttp(runtime.control)
            request = {'RoomId':room['RoomId']}
            self.assertEqual(await asyncio.to_thread(adapter.heart_beat,'alice',request),{})
            for account,data in (('outsider',request),('alice',{'RoomId':'unknown'})):
                with self.assertRaises(RoomError):
                    await asyncio.to_thread(adapter.heart_beat,account,data)
            for invalid in ({},{'RoomId':''},{'RoomId':1},dict(request,UserId='alice')):
                with self.assertRaises(ValueError): adapter.heart_beat('alice',invalid)
            self.assertEqual(runtime.rooms.memberships,{'alice':room['RoomId']})
            await asyncio.wrap_future(runtime.control.submit('leave','alice',room['RoomId']))
            with self.assertRaises(RoomError):
                await asyncio.to_thread(adapter.heart_beat,'alice',request)
        finally:
            await runtime.stop()

    async def test_threaded_http_discovery_runs_current_eligibility_and_visibility(self):
        start = datetime(2026,1,1,tzinfo=timezone.utc)
        now = [start]
        power = [100]
        link = dict(EpisodePveEventId='link',EventId='event',EpisodeId='episode',
                    RequiredPower=100,Difficulty=2,MinVerIOS='1.5.0',MinVerAndroid='1.5.0')
        catalog = ScheduledCatalog(EpisodeCatalog([link],{'episode'}),[
            dict(EventId='event',PublishStartAt=start,StartAt=start,
                 EndAt=start+timedelta(hours=1))],lambda:now[0])
        runtime = Runtime(2,event_catalog=catalog,
            eligibility_provider=lambda account:dict(Power=power[0],Platform='android',ClientVersion='1.6.0'),
            room_settings_provider=lambda episode:dict(Mode=1,SuspendLimits=(60,3,20)),
            room_view_provider=lambda viewer,room:room_view(room,100,2,'','',False,False,1234),
            player_provider=player,connection_provider=lambda room,tcp,udp:admission_payload(
                room['RoomId'],'1234567',tcp,udp,'localhost',1234,'localhost',1235))
        runtime.listener.start = AsyncMock(return_value=['socket'])
        await runtime.start('localhost',1234,None)
        try:
            public = await asyncio.wrap_future(runtime.control.submit(
                'create_event',player('host'),'episode','v',1))
            adapter = PveHttp(runtime.control)
            response = await asyncio.to_thread(adapter.create,'private',
                dict(EpisodeId='episode',PublicLevel=2,PveVersion='v'))
            admitted = response['Prizm']
            session = runtime.registry.open(admitted['JwtTcp'])
            self.assertEqual(session.admission.account_id,'private')
            runtime.registry.fallback(session.session_id,admitted['JwtUdp'])
            private = (runtime.rooms.rooms[admitted['RoomId']],)
            request = dict(EventId='event',Difficulty=2,PveVersion='v')
            listed = await asyncio.to_thread(adapter.room_list,'viewer',request)
            self.assertEqual([room['RoomId'] for room in listed['Rooms']],[public[0]['RoomId']])
            self.assertEqual(listed['Rooms'][0]['HostUserId'],'host')
            info = dict(EventId='event',RoomId=private[0]['RoomId'],PveVersion='v')
            self.assertEqual((await asyncio.to_thread(adapter.room_info,'viewer',info))['Room']['HostUserId'],'private')
            join_request = dict(RoomId=private[0]['RoomId'],JoinRoute=1,PveVersion='v')
            with self.assertRaises(RoomError):
                await asyncio.to_thread(adapter.join,'guest',join_request)
            self.assertNotIn('guest',runtime.rooms.memberships)
            join_request['JoinRoute'] = 3
            joined = (await asyncio.to_thread(adapter.join,'guest',join_request))['Prizm']
            guest = runtime.registry.open(joined['JwtTcp'])
            self.assertEqual(guest.admission.account_id,'guest')
            self.assertEqual(guest.admission.room_id,private[0]['RoomId'])
            with self.assertRaises(RoomError):
                await asyncio.to_thread(adapter.join,'overflow',join_request)
            self.assertNotIn('overflow',runtime.rooms.memberships)
            power[0] = 99
            self.assertEqual(await asyncio.to_thread(adapter.room_list,'viewer',request),{'Rooms':[]})
            retry = await asyncio.to_thread(adapter.matching,'matcher',dict(request,MaxPower='999999'))
            self.assertTrue(retry['RetryRequest'])
            self.assertIsNone(retry['Prizm'])
            self.assertNotIn('matcher',runtime.rooms.memberships)
            with self.assertRaises(RoomError): await asyncio.to_thread(adapter.room_info,'viewer',info)
            power[0] = 100
            matched = await asyncio.to_thread(adapter.matching,'matcher',request)
            self.assertFalse(matched['RetryRequest'])
            self.assertEqual(matched['Rooms'][0]['RoomId'],public[0]['RoomId'])
            matching_session = runtime.registry.open(matched['Prizm']['JwtTcp'])
            self.assertEqual(matching_session.admission.account_id,'matcher')
            self.assertEqual(matching_session.admission.room_id,public[0]['RoomId'])
            self.assertTrue((await asyncio.to_thread(adapter.matching,'another',request))['RetryRequest'])
            now[0] = start+timedelta(hours=1)
            self.assertEqual(await asyncio.to_thread(adapter.room_list,'viewer',request),{'Rooms':[]})
        finally:
            await runtime.stop()
        with self.assertRaises(RuntimeError): await asyncio.to_thread(adapter.room_list,'viewer',request)


class HttpAdapterTests(unittest.TestCase):
    def test_read_timeout_cancels_queued_request(self):
        control = Mock()
        future = Future()
        control.submit.return_value = future
        adapter = PveHttp(control,timeout=0.001)
        with self.assertRaises(TimeoutError):
            adapter.room_list('viewer',dict(EventId='event',Difficulty=2,PveVersion='v'))
        self.assertTrue(future.cancelled())

    def test_running_create_collects_result_after_wait_timeout(self):
        import threading
        control = Mock()
        future = Future()
        future.set_running_or_notify_cancel()
        control.submit.return_value = future
        timer = threading.Timer(0.02,lambda:future.set_result({'Prizm':{'RoomId':'created'}}))
        timer.start()
        try:
            self.assertEqual(PveHttp(control,timeout=0.001).create('host',
                dict(EpisodeId='ep',PublicLevel=1,PveVersion='v')),
                {'Prizm':{'RoomId':'created'}})
            self.assertFalse(future.cancelled())
        finally:
            timer.join()
