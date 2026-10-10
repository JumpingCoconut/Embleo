import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_runtime import Runtime
from prizm_sessions import SessionError
from test_prizm_lobby import player


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_installed_battle_provider_carries_its_enemy_policy_into_runtime(self):
        from pve_preparation import BattleAssembler
        assembler = BattleAssembler(None,None,None)
        runtime = Runtime(2,battle_provider=assembler)
        self.assertIs(runtime.service.battle_provider,assembler)
        self.assertIs(runtime.service.battle_enemy_provider,assembler.enemy_spawns)
        await runtime.stop()
        explicit = lambda account,room:set()
        runtime = Runtime(2,battle_provider=assembler,battle_enemy_provider=explicit)
        self.assertIs(runtime.service.battle_enemy_provider,explicit)
        await runtime.stop()

    async def test_stop_waits_for_inflight_start_and_closes_result(self):
        runtime = Runtime(2)
        entered,released = asyncio.Event(),asyncio.Event()
        async def delayed_start(*args):
            entered.set()
            await released.wait()
            return ['socket']
        runtime.listener.start = AsyncMock(side_effect=delayed_start)
        runtime.listener.stop = AsyncMock()
        starting = asyncio.create_task(runtime.start('localhost',1234,None))
        await entered.wait()
        stopping = asyncio.create_task(runtime.stop())
        await asyncio.sleep(0)
        self.assertFalse(stopping.done())
        released.set()
        self.assertEqual(await starting,['socket'])
        await stopping
        self.assertTrue(runtime.closed)
        self.assertTrue(runtime.control.closed)
        runtime.listener.stop.assert_awaited_once()
        with self.assertRaises(RuntimeError):
            await runtime.start('localhost',1234,None)

    async def test_shutdown_revokes_unused_admissions_and_queued_http_work(self):
        runtime = Runtime(2)
        runtime.listener.start = AsyncMock(return_value=['socket'])
        self.assertEqual(await runtime.start('localhost',1234,None),['socket'])
        room,tcp,udp = runtime.service.create(player(),'ep','v',False,0,1,(60,3,20))
        queued = runtime.control.submit('join',room['RoomId'],player('bob',1,False),'v')
        await runtime.stop()
        self.assertTrue(queued.cancelled())
        self.assertEqual(runtime.rooms.rooms,{})
        self.assertEqual(runtime.rooms.memberships,{})
        self.assertEqual(runtime.registry.credentials,{})
        with self.assertRaises(SessionError): runtime.registry.open(tcp)
        with self.assertRaises(RuntimeError): runtime.control.submit('leave','alice',room['RoomId'])
        with self.assertRaises(RuntimeError): await runtime.start('localhost',1234,None)
        await runtime.stop()

    async def test_failed_listener_start_never_exposes_control_bridge(self):
        runtime = Runtime(2)
        with self.assertRaises(ValueError): await runtime.start('localhost',1234,None)
        self.assertIsNone(runtime.control)
        self.assertIsNone(runtime.listener.server)
        await runtime.stop()
