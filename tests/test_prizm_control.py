import asyncio
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_control import RoomControl
from prizm_rooms import Rooms
from prizm_room_service import RoomService
from prizm_sessions import SessionRegistry
from test_prizm_lobby import player


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_thread_admission_runs_on_listener_loop(self):
        rooms,registry = Rooms(2),SessionRegistry()
        service = RoomService(rooms,registry)
        control = RoomControl(service)
        expected_thread = threading.get_ident()
        original = service.create
        def create(*args):
            self.assertEqual(threading.get_ident(),expected_thread)
            return original(*args)
        service.create = create
        def http_request():
            return control.submit('create',player(),'ep','v',False,0,1,(60,3,20)).result(3)
        room,tcp,udp = await asyncio.to_thread(http_request)
        self.assertEqual(registry.open(tcp).admission.room_id,room['RoomId'])
        self.assertTrue(udp)
        self.assertEqual(control.pending,set())
        control.close()
        with self.assertRaises(RuntimeError): control.submit('leave','alice',room['RoomId'])

    async def test_cancelled_or_shutdown_admission_never_runs(self):
        rooms,registry = Rooms(2),SessionRegistry()
        control = RoomControl(RoomService(rooms,registry),limit=1)
        profile = player()
        future = control.submit('create',profile,'ep','v',False,0,1,(60,3,20))
        profile['UserId'] = 'forged'
        with self.assertRaises(RuntimeError):
            control.submit('create',player('bob'),'ep','v',False,0,1,(60,3,20))
        future.cancel()
        await asyncio.sleep(0)
        self.assertEqual(rooms.rooms,{})
        future = control.submit('create',profile,'ep','v',False,0,1,(60,3,20))
        control.close()
        await asyncio.sleep(0)
        self.assertTrue(future.cancelled())
        self.assertEqual(rooms.rooms,{})
        self.assertEqual(registry.credentials,{})
