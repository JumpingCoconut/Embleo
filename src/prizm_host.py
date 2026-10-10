"""Synchronous Flask-process ownership of the raid event loop."""

import asyncio
from concurrent.futures import Future
import threading
from pve_http import PveHttp


class RuntimeHost:
    def __init__(self, factory):
        self.factory = factory
        self.ready = Future()
        self.loop = None
        self.task = None
        self.thread = None
        self.runtime = None
        self.stopping = threading.Event()
        self.closed = Future()
        self.cancel_requested = False

    def start(self, host, port, tls, timeout=10):
        if self.thread is not None:
            raise RuntimeError('Raid runtime host cannot be restarted.')
        self.thread = threading.Thread(target=self._run, args=(host,port,tls),
                                       name='embleo-raid', daemon=True)
        self.thread.start()
        try:
            return self.ready.result(timeout)
        except BaseException:
            self.stop(timeout)
            raise

    def _run(self, host, port, tls):
        async def own():
            self.loop = asyncio.get_running_loop()
            self.task = asyncio.current_task()
            try:
                if self.stopping.is_set():
                    raise RuntimeError('Raid runtime startup was cancelled.')
                self.runtime = self.factory()
                await self.runtime.start(host,port,tls)
                if self.stopping.is_set():
                    raise RuntimeError('Raid runtime startup was cancelled.')
                self.ready.set_result(PveHttp(self.runtime.control))
                await asyncio.Future()
            except BaseException as error:
                if not self.ready.done():
                    self.ready.set_exception(error)
            finally:
                if self.runtime is not None:
                    await self.runtime.stop()
        try:
            asyncio.run(own())
        except BaseException as error:
            self.closed.set_exception(error)
        else:
            self.closed.set_result(None)

    def stop(self, timeout=10):
        self.stopping.set()
        if self.loop is not None and self.loop.is_running() and self.task is not None:
            try:
                def cancel_once():
                    # Keep the guard on the owning loop. Task.cancelling()
                    # is unavailable on the supported Python 3.10 runtime.
                    if not self.task.done() and not self.cancel_requested:
                        self.cancel_requested = True
                        self.task.cancel()
                self.loop.call_soon_threadsafe(cancel_once)
            except RuntimeError:
                pass
        if self.thread is not None:
            self.thread.join(timeout)
            if self.thread.is_alive():
                raise RuntimeError('Raid runtime shutdown did not finish.')
            self.closed.result()


def attach_runtime(app, owner, host, port, tls):
    """Called explicitly at process startup, before serving HTTP requests."""
    if app.config.get('PVE_HTTP') is not None:
        raise RuntimeError('PvE runtime is already attached.')
    app.config['PVE_HTTP'] = owner.start(host,port,tls)
    app.extensions['pve_runtime'] = owner


def run_http(app, **http_options):
    """Own the configured raid listener for the lifetime of Flask serving."""
    factory = app.config.get('PVE_RUNTIME_FACTORY')
    if factory is None:
        return app.run(**http_options)
    if not callable(factory):
        raise ValueError('PVE_RUNTIME_FACTORY must construct the configured runtime.')
    owner = RuntimeHost(factory)
    attach_runtime(app, owner, app.config['PVE_BIND_HOST'],
                   app.config['PVE_BIND_PORT'], app.config['PVE_TLS'])
    try:
        # The reloader forks/reimports the server; room state must have one owner.
        return app.run(**(http_options | {'use_reloader':False}))
    finally:
        app.config.pop('PVE_HTTP',None)
        app.extensions.pop('pve_runtime',None)
        owner.stop()
