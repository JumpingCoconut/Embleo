"""Opt-in TLS TCP listener. Not automatically started by the HTTP server."""

import asyncio
import ssl
from itertools import islice

from prizm_connection import Connection
from prizm_protocol import ProtocolError
from prizm_sessions import SessionError
from prizm_diagnostics import Diagnostics


class Listener:
    def __init__(self, registry, service_handler, max_connections=64,
                 idle_timeout=30, write_timeout=10, trusted_tls_proxy=False):
        if (type(max_connections) is not int or max_connections < 1
                or idle_timeout <= 0 or write_timeout <= 0):
            raise ValueError('Invalid listener limits.')
        if type(trusted_tls_proxy) is not bool:
            raise ValueError('trusted_tls_proxy must be a boolean.')
        self.registry = registry
        self.service_handler = service_handler
        self.max_connections = max_connections
        self.idle_timeout = idle_timeout
        self.write_timeout = write_timeout
        self.trusted_tls_proxy = trusted_tls_proxy
        self.tasks = set()
        self.server = None
        self.stopping = False
        self.diagnostics = Diagnostics('listener')

    async def start(self, host, port, tls):
        if self.server is not None:
            raise RuntimeError('Listener already started.')
        if self.trusted_tls_proxy:
            if tls is not None:
                raise ValueError('Trusted TLS proxy mode requires no backend TLS context.')
        elif not isinstance(tls, ssl.SSLContext) or tls.protocol != ssl.PROTOCOL_TLS_SERVER:
            raise ValueError('A server TLS context is required.')
        self.stopping = False
        options = {} if self.trusted_tls_proxy else {'ssl':tls, 'ssl_handshake_timeout':10}
        self.server = await asyncio.start_server(
            self.handle, host, port, limit=65536, **options)
        return self.server.sockets

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        connection = None
        read_task = wake_task = None
        try:
            if self.stopping or len(self.tasks) >= self.max_connections:
                self.diagnostics.record('stopping' if self.stopping else 'capacity')
                return
            self.tasks.add(task)
            connection = Connection(self.registry, self.service_handler)
            ready = asyncio.Event()
            connection.outbound_ready = ready
            connection.close_observer = lambda reason, frames, size: self.diagnostics.record(
                reason, queue_frames=frames, queue_bytes=size)
            loop = asyncio.get_running_loop()
            last_read = loop.time()

            async def write(replies):
                # This handler is the sole socket writer. Detach at most one
                # bounded queue; drain before taking another, including RPCs.
                for reply in replies:
                    writer.write(reply)
                if replies:
                    try:
                        await asyncio.wait_for(writer.drain(), self.write_timeout)
                    except asyncio.TimeoutError:
                        connection.close('write_timeout')
                        raise

            while not connection.closed:
                if read_task is None:
                    read_task = asyncio.create_task(reader.read(65536))
                ready.clear()
                await write(connection.notifications())
                if connection.closed:
                    break
                wake_task = asyncio.create_task(ready.wait())
                done, _ = await asyncio.wait((read_task, wake_task),
                    timeout=min(0.1, self.idle_timeout),
                    return_when=asyncio.FIRST_COMPLETED)
                wake_task.cancel()
                await asyncio.gather(wake_task, return_exceptions=True)
                wake_task = None
                if read_task not in done:
                    if loop.time()-last_read >= self.idle_timeout:
                        self.diagnostics.record('idle_timeout')
                        break
                    continue
                completed_read = read_task
                read_task = None
                data = completed_read.result()
                if not data:
                    self.diagnostics.record('peer_eof')
                    connection.eof()
                    break
                last_read = loop.time()
                frames = connection.decoder.iter_feed(data)
                while not connection.closed:
                    batch = list(islice(frames, 32))
                    if not batch:
                        break
                    await write(connection.receive_frames(batch) + connection.notifications())
                    # Even send-only coalesced reads must yield to recipients.
                    await asyncio.sleep(0)
        except ProtocolError:
            self.diagnostics.record('protocol_rejected', connection.rejection_context
                                    if connection is not None else 'transport')
        except SessionError:
            self.diagnostics.record('session_rejected')
        except ConnectionError:
            self.diagnostics.record('connection_lost')
        except asyncio.TimeoutError:
            # Recorded before connection cleanup by the sole write path.
            pass
        finally:
            pending_tasks = [item for item in (read_task, wake_task) if item is not None]
            for item in pending_tasks:
                item.cancel()
            task_results = []
            if pending_tasks:
                task_results = await asyncio.gather(*pending_tasks, return_exceptions=True)
            if connection is not None:
                connection.close()
            self.tasks.discard(task)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), self.write_timeout)
            except (ConnectionError, asyncio.TimeoutError):
                pass
            # A read that failed concurrently with closure must not turn an
            # unexpected programming error into silent task cleanup.
            for result in task_results:
                if isinstance(result, Exception) and not isinstance(result, ConnectionError):
                    raise result

    async def stop(self):
        self.stopping = True
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
