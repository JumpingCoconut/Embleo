"""Bounded thread-to-listener room control. Callers authenticate before submit.

Construct and close on the listener's event loop. HTTP threads submit detached
server-owned values, then wait on the returned concurrent Future. Cancellation
before execution prevents a timed-out request from later admitting a player.
"""

import asyncio
import concurrent.futures
import copy
import threading


class RoomControl:
    METHODS = frozenset({'create','create_event','create_http','join','join_checked','match_checked','match_event',
                         'join_event','join_http','matching_http','start_http','complete_http','heartbeat_http','discover','discover_event','info_event','leave'})

    def __init__(self, service, limit=64):
        if type(limit) is not int or limit < 1:
            raise ValueError('Invalid room control capacity.')
        self.loop = asyncio.get_running_loop()
        self.service = service
        self.limit = limit
        self.lock = threading.Lock()
        self.pending = set()
        self.closed = False

    def submit(self, operation, *args, **kwargs):
        if operation not in self.METHODS:
            raise ValueError('Unsupported room operation.')
        # Never pass Flask request objects or database connections to this loop.
        args,kwargs = copy.deepcopy((args,kwargs))
        future = concurrent.futures.Future()
        with self.lock:
            if self.closed or not self.loop.is_running():
                raise RuntimeError('Room control is stopped.')
            if len(self.pending) >= self.limit:
                raise RuntimeError('Room control capacity reached.')
            self.pending.add(future)
        try:
            self.loop.call_soon_threadsafe(self._execute,future,operation,args,kwargs)
        except RuntimeError:
            with self.lock:
                self.pending.discard(future)
            future.cancel()
            raise
        return future

    def _execute(self, future, operation, args, kwargs):
        try:
            if not future.set_running_or_notify_cancel():
                return
            try:
                result = getattr(self.service,operation)(*args,**kwargs)
            except Exception as error:
                future.set_exception(error)
            else:
                future.set_result(result)
        finally:
            with self.lock:
                self.pending.discard(future)

    def close(self):
        if asyncio.get_running_loop() is not self.loop:
            raise RuntimeError('Close room control on its listener loop.')
        with self.lock:
            self.closed = True
            pending = list(self.pending)
        for future in pending:
            future.cancel()
