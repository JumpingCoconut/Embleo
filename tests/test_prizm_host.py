import asyncio
from pathlib import Path
import sys
import unittest
import os
import ssl
import socket
import subprocess
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_host import RuntimeHost, run_http
from prizm_control import RoomControl
from prizm_runtime import Runtime


class HostTests(unittest.TestCase):
    def test_stop_cancels_once_without_python311_task_api(self):
        class Task:
            count = 0
            def done(self): return False
            def cancel(self): self.count += 1
        class Loop:
            def is_running(self): return True
            def call_soon_threadsafe(self, callback): callback()
        owner = RuntimeHost(lambda:None)
        owner.task, owner.loop = Task(), Loop()
        owner.stop()
        owner.stop()
        self.assertEqual(owner.task.count, 1)

    def test_http_lifetime_owns_configured_runtime_without_reloader(self):
        class Runtime:
            closed = False
            async def start(self,*args): self.control = RoomControl(object())
            async def stop(self):
                self.closed = True
                self.control.close()
        runtime = Runtime()
        class App:
            config = dict(PVE_RUNTIME_FACTORY=lambda:runtime,PVE_BIND_HOST='localhost',
                          PVE_BIND_PORT=0,PVE_TLS=None)
            extensions = {}
            def run(self,**options):
                self.options = options
                if self.config['PVE_HTTP'].control.closed:
                    raise AssertionError('Control must be live while serving')
                raise ValueError('HTTP stopped')
        app = App()
        with self.assertRaisesRegex(ValueError,'HTTP stopped'):
            run_http(app,debug=True,use_reloader=True)
        self.assertFalse(app.options['use_reloader'])
        self.assertTrue(runtime.closed)
        self.assertNotIn('PVE_HTTP',app.config)
        self.assertNotIn('pve_runtime',app.extensions)

    def test_real_runtime_host_accepts_verified_tls_and_closes_socket(self):
        openssl = os.environ.get('EMBLEO_TEST_OPENSSL')
        if not openssl:
            self.skipTest('Set EMBLEO_TEST_OPENSSL for real runtime host TLS.')
        with tempfile.TemporaryDirectory() as directory:
            key,cert = Path(directory)/'key.pem',Path(directory)/'cert.pem'
            subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes',
                '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost',
                '-addext','subjectAltName=DNS:localhost'],check=True,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(cert,key)
            trusted = ssl.create_default_context(cafile=str(cert))
            owner = RuntimeHost(lambda:Runtime(2))
            adapter = owner.start('127.0.0.1',0,tls)
            try:
                address = owner.runtime.listener.server.sockets[0].getsockname()
                with socket.create_connection(address,timeout=2) as raw:
                    with trusted.wrap_socket(raw,server_hostname='localhost') as client:
                        self.assertTrue(client.getpeercert())
            finally:
                owner.stop()
            self.assertTrue(adapter.control.closed)
            self.assertIsNone(owner.runtime.listener.server)
            self.assertFalse(owner.thread.is_alive())

    def test_start_timeout_cancels_listener_and_finishes_cleanup(self):
        class Runtime:
            closed = False
            async def start(self,*args): await asyncio.Future()
            async def stop(self): self.closed = True
        owner = RuntimeHost(Runtime)
        with self.assertRaises(TimeoutError): owner.start('localhost',0,None,timeout=0.1)
        self.assertFalse(owner.thread.is_alive())
        if owner.runtime is not None:
            self.assertTrue(owner.runtime.closed)

    def test_shutdown_failure_is_reported_to_process_owner(self):
        class Runtime:
            async def start(self,*args): self.control = RoomControl(object())
            async def stop(self):
                self.control.close()
                raise RuntimeError('Cleanup failed')
        owner = RuntimeHost(Runtime)
        owner.start('localhost',0,None)
        with self.assertRaisesRegex(RuntimeError,'Cleanup failed'): owner.stop()
        self.assertFalse(owner.thread.is_alive())

    def test_http_bridge_runs_on_owned_loop_and_shutdown_closes_it(self):
        class Service:
            def discover(self): return asyncio.get_running_loop()
        class Runtime:
            async def start(self,*args):
                self.loop = asyncio.get_running_loop()
                self.control = RoomControl(Service())
            async def stop(self): self.control.close()
        owner = RuntimeHost(Runtime)
        adapter = owner.start('localhost',0,None)
        try:
            self.assertIs(adapter.control.submit('discover').result(2),owner.runtime.loop)
        finally:
            owner.stop()
        self.assertFalse(owner.thread.is_alive())
        with self.assertRaises(RuntimeError): adapter.control.submit('discover')

    def test_failed_start_never_returns_adapter_and_cleans_up(self):
        class Runtime:
            closed = False
            async def start(self,*args): raise ValueError('Invalid TLS')
            async def stop(self): self.closed = True
        owner = RuntimeHost(Runtime)
        with self.assertRaises(ValueError): owner.start('localhost',0,None)
        self.assertTrue(owner.runtime.closed)
        self.assertFalse(owner.thread.is_alive())


if __name__ == '__main__': unittest.main()
