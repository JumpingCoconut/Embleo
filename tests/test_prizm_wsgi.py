"""Explicit WSGI ownership without import-time listener startup."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from flask import Flask
from prizm_control import RoomControl
from prizm_host import (load_operator_config, start_configured_runtime,
                        start_wsgi_runtime, stop_configured_runtime)


class WsgiTests(unittest.TestCase):
    def app(self, runtime=None):
        app = Flask(__name__)
        if runtime is not None:
            app.config.update(PVE_RUNTIME_FACTORY=lambda:runtime,
                              PVE_BIND_HOST='localhost',PVE_BIND_PORT=0,PVE_TLS=None)
        return app

    def test_config_load_does_not_create_transport(self):
        app = self.app()
        with patch.dict(os.environ,{'EMBLEO_PVE_CONFIG':'private-raid-config.py'}):
            with patch.object(app.config,'from_pyfile') as loader:
                with patch('prizm_host.RuntimeHost') as constructor:
                    load_operator_config(app)
        loader.assert_called_once_with(str(Path('private-raid-config.py').resolve()))
        constructor.assert_not_called()
        self.assertNotIn('PVE_HTTP',app.config)

    def test_nonraid_wsgi_needs_no_listener_or_single_worker(self):
        app = self.app()
        with patch.dict(os.environ,{},clear=True):
            self.assertIsNone(start_wsgi_runtime(app,workers=4,preload_app=True))
        stop_configured_runtime(app)
        self.assertNotIn('PVE_HTTP',app.config)

    def test_publication_without_transport_fails_startup(self):
        app = self.app()
        app.config['PVE_PUBLICATION'] = object()
        with self.assertRaisesRegex(ValueError,'publication requires'):
            start_configured_runtime(app)

    def test_invalid_process_model_rejects_before_listener_start(self):
        for workers,preload in ((2,False),(1,True),(True,False)):
            with self.subTest(workers=workers,preload=preload):
                app = self.app(object())
                with patch.dict(os.environ,{},clear=True):
                    with patch('prizm_host.RuntimeHost') as constructor:
                        with self.assertRaisesRegex(ValueError,'one worker'):
                            start_wsgi_runtime(app,workers=workers,preload_app=preload)
                constructor.assert_not_called()

    def test_worker_lifetime_attaches_live_bridge_and_stops_once(self):
        class Runtime:
            stops = 0
            async def start(self,*args): self.control = RoomControl(object())
            async def stop(self):
                self.stops += 1
                self.control.close()
        runtime = Runtime()
        app = self.app(runtime)
        with patch.dict(os.environ,{},clear=True):
            owner = start_wsgi_runtime(app,workers=1,preload_app=False)
        try:
            self.assertIs(app.extensions['pve_runtime'],owner)
            self.assertFalse(app.config['PVE_HTTP'].control.closed)
            with self.assertRaisesRegex(RuntimeError,'already attached'):
                start_configured_runtime(app)
        finally:
            stop_configured_runtime(app)
        stop_configured_runtime(app)
        self.assertEqual(runtime.stops,1)
        self.assertFalse(owner.thread.is_alive())
        self.assertNotIn('PVE_HTTP',app.config)
        self.assertNotIn('pve_runtime',app.extensions)

    def test_failed_worker_start_exposes_no_adapter(self):
        class Runtime:
            stopped = False
            async def start(self,*args): raise OSError('Listener unavailable')
            async def stop(self): self.stopped = True
        runtime = Runtime()
        app = self.app(runtime)
        with self.assertRaisesRegex(OSError,'Listener unavailable'):
            start_configured_runtime(app)
        self.assertTrue(runtime.stopped)
        self.assertNotIn('PVE_HTTP',app.config)
        self.assertNotIn('pve_runtime',app.extensions)


if __name__ == '__main__': unittest.main()
