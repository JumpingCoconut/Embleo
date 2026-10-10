"""Opt-in TLS TCP listener. Not automatically started by the HTTP server."""

import asyncio
import ssl

from prizm_connection import Connection
from prizm_protocol import ProtocolError
from prizm_sessions import SessionError


class Listener:
    def __init__(self, registry, service_handler, max_connections=64,
                 idle_timeout=30, write_timeout=10):
        if (type(max_connections) is not int or max_connections < 1
                or idle_timeout <= 0 or write_timeout <= 0):
            raise ValueError('Invalid listener limits.')
        self.registry = registry
        self.service_handler = service_handler
        self.max_connections = max_connections
        self.idle_timeout = idle_timeout
        self.write_timeout = write_timeout
        self.tasks = set()
        self.server = None
        self.stopping = False

    async def start(self, host, port, tls):
        if self.server is not None:
            raise RuntimeError('Listener already started.')
        if not isinstance(tls, ssl.SSLContext) or tls.protocol != ssl.PROTOCOL_TLS_SERVER:
            raise ValueError('A server TLS context is required.')
        self.stopping = False
        self.server = await asyncio.start_server(
            self.handle, host, port, ssl=tls, ssl_handshake_timeout=10,
            limit=65536)
        return self.server.sockets

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        connection = None
        try:
            if self.stopping or len(self.tasks) >= self.max_connections:
                return
            self.tasks.add(task)
            connection = Connection(self.registry, self.service_handler)
            loop = asyncio.get_running_loop()
            last_read = loop.time()
            while not connection.closed:
                try:
                    data = await asyncio.wait_for(reader.read(65536), min(0.1,self.idle_timeout))
                except asyncio.TimeoutError:
                    if loop.time()-last_read >= self.idle_timeout:
                        break
                    for reply in connection.notifications():
                        writer.write(reply)
                        await asyncio.wait_for(writer.drain(),self.write_timeout)
                    continue
                if not data:
                    connection.eof()
                    break
                last_read = loop.time()
                for reply in connection.receive(data) + connection.notifications():
                    writer.write(reply)
                    await asyncio.wait_for(writer.drain(), self.write_timeout)
        except (ProtocolError, SessionError, ConnectionError, asyncio.TimeoutError):
            # Expected disconnects contain no credentials/profile data in logs.
            pass
        finally:
            if connection is not None:
                connection.close()
            self.tasks.discard(task)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), self.write_timeout)
            except (ConnectionError, asyncio.TimeoutError):
                pass

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
