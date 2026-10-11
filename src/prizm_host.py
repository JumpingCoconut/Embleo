"""Synchronous Flask-process ownership of the raid event loop."""

import asyncio
from concurrent.futures import Future
import os
from pathlib import Path
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


def load_operator_config(app, path=None):
    """Load explicit private configuration; never start a listener."""
    path = path if path is not None else os.environ.get('EMBLEO_PVE_CONFIG')
    if path:
        app.config.from_pyfile(str(Path(path).resolve()))


def start_configured_runtime(app):
    """Explicit process startup, after configuration and before HTTP serving."""
    if app.config.get('PVE_HTTP') is not None or 'pve_runtime' in app.extensions:
        raise RuntimeError('PvE runtime is already attached.')
    factory = app.config.get('PVE_RUNTIME_FACTORY')
    if factory is None:
        if app.config.get('PVE_PUBLICATION') is not None:
            raise ValueError('Raid publication requires a configured runtime.')
        return None
    if not callable(factory):
        raise ValueError('PVE_RUNTIME_FACTORY must construct the configured runtime.')
    # Validate configuration before allocating the event-loop thread.
    host, port, tls = (app.config[key] for key in
                      ('PVE_BIND_HOST','PVE_BIND_PORT','PVE_TLS'))
    owner = RuntimeHost(factory)
    attach_runtime(app, owner, host, port, tls)
    return owner


def stop_configured_runtime(app):
    """Explicit worker shutdown; idempotent after complete cleanup."""
    owner = app.extensions.get('pve_runtime')
    if owner is None:
        return
    try:
        owner.stop()
    finally:
        app.config.pop('PVE_HTTP',None)
        app.extensions.pop('pve_runtime',None)


def start_wsgi_runtime(app, *, workers, preload_app, config_path=None):
    """Call in the owning WSGI worker, never in the pre-fork master.

    The caller supplies actual server settings, not assumed defaults. A private
    Gunicorn post_worker_init hook can call this and worker_exit can call
    stop_configured_runtime. Graceful overlapping worker reloads need a separate
    listener handover strategy; this in-process runtime has one owner.
    """
    load_operator_config(app, config_path)
    if app.config.get('PVE_RUNTIME_FACTORY') is not None:
        if type(workers) is not int or workers != 1 or preload_app is not False:
            raise ValueError('Raid runtime requires one worker without preloading.')
    return start_configured_runtime(app)


def run_http(app, **http_options):
    """Own the configured raid listener for the lifetime of Flask serving."""
    owner = start_configured_runtime(app)
    if owner is None:
        return app.run(**http_options)
    try:
        # The reloader forks/reimports the server; room state must have one owner.
        return app.run(**(http_options | {'use_reloader':False}))
    finally:
        stop_configured_runtime(app)
