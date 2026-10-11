import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_diagnostics import Diagnostics
from prizm_control import RoomControl
from prizm_listener import Listener
from prizm_protocol import ProtocolError
from prizm_sessions import SessionRegistry


class DiagnosticsTests(unittest.TestCase):
    def test_rate_limit_retains_counts_and_bounds_cardinality(self):
        diagnostics = Diagnostics('test')
        with patch('prizm_diagnostics.time.monotonic',side_effect=[0,1,30]):
            with self.assertLogs('embleo.raid.test',level='WARNING') as logs:
                for _ in range(3): diagnostics.record('protocol_rejected')
        self.assertEqual(len(logs.output),2)
        self.assertIn('count=3',logs.output[-1])
        with patch.object(diagnostics.logger,'warning'):
            for index in range(100): diagnostics.record('fixed-' + str(index))
        self.assertEqual(len(diagnostics.counts),64)


class SafeFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_error_never_logs_arguments_or_exception_text(self):
        class Service:
            def create(self, value): raise ValueError(value)
        control = RoomControl(Service())
        with self.assertLogs('embleo.raid.control',level='WARNING') as logs:
            future = control.submit('create','private-token-user-save')
            await asyncio.sleep(0)
        with self.assertRaises(ValueError): future.result()
        self.assertNotIn('private-token-user-save',' '.join(logs.output))
        self.assertIn('operation=create',' '.join(logs.output))
        control.close()

    async def test_protocol_error_never_logs_exception_text_or_peer_data(self):
        class Reader:
            async def read(self, size): raise ProtocolError('private-payload')
        class Writer:
            def close(self): pass
            async def wait_closed(self): pass
        listener = Listener(SessionRegistry(),object())
        with self.assertLogs('embleo.raid.listener',level='WARNING') as logs:
            await listener.handle(Reader(),Writer())
        self.assertIn('reason=protocol_rejected',' '.join(logs.output))
        self.assertNotIn('private-payload',' '.join(logs.output))
        self.assertEqual(listener.tasks,set())
