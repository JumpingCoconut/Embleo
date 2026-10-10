"""Prizm connection state machine for the TCP-first local prototype.

The listener must supply TLS. This module does not bind public ports or enable
HTTP raid discovery. Service handlers receive validated session identity.
"""

from prizm_protocol import (FrameDecoder, Opcode, ProtocolError,
                            read_hello_request, read_fallback_request,
                            handshake_response, read_user_message, user_message, ping_reply)
from prizm_sessions import SessionError


class Connection:
    def __init__(self, registry, service_handler):
        self.registry = registry
        self.service_handler = service_handler
        self.decoder = FrameDecoder()
        self.session = None
        self.fallback_enabled = False
        self.closed = False
        self.pending = []
        self.pending_keys = []

    def notify(self, service, body, reliable=True, coalesce=None):
        if self.closed or self.session is None:
            return
        if not reliable and not self.fallback_enabled:
            return
        outgoing = user_message(service,body,fallback=not reliable)
        if coalesce is not None and coalesce in self.pending_keys:
            index = self.pending_keys.index(coalesce)
            self.pending.pop(index)
            self.pending_keys.pop(index)
            self.pending.append(outgoing)
            self.pending_keys.append(coalesce)
            return
        if len(self.pending) >= 128:
            self.close()
            return
        self.pending.append(outgoing)
        self.pending_keys.append(coalesce)

    def notifications(self):
        if self.closed:
            self.pending.clear()
            self.pending_keys.clear()
            return []
        if self.session is not None:
            try:
                # Outbound traffic must neither bypass revocation nor keep an
                # inactive client alive merely because other players are active.
                self.registry.get(self.session.session_id, refresh=False)
            except SessionError:
                self.close()
                return []
        result, self.pending = self.pending, []
        self.pending_keys.clear()
        return result

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.pending.clear()
        self.pending_keys.clear()
        if self.session is not None:
            if hasattr(self.service_handler,'disconnected'):
                self.service_handler.disconnected(self)
            self.registry.close(self.session.session_id)

    def receive(self, data):
        if self.closed:
            raise ProtocolError('Connection is closed.')
        output = []
        try:
            for opcode, payload in self.decoder.feed(data):
                if self.session is None:
                    if opcode != Opcode.HELLO_REQUEST:
                        raise ProtocolError('Hello required before service traffic.')
                    try:
                        self.session = self.registry.open(read_hello_request(payload))
                    except (SessionError, ProtocolError):
                        output.append(handshake_response(None, 'Authentication failed.', failed=True))
                        self.close()
                        break
                    output.append(handshake_response({
                        'session_id': self.session.session_id,
                        'player_id': self.session.admission.player_id,
                        'encryption': False}))
                    if hasattr(self.service_handler,'connected'):
                        self.service_handler.connected(self)
                    continue
                self.session = self.registry.get(self.session.session_id)
                if opcode == Opcode.PING:
                    output.append(ping_reply(payload))
                elif opcode == Opcode.FALLBACK_REQUEST:
                    if self.fallback_enabled:
                        raise ProtocolError('Fallback already negotiated.')
                    try:
                        self.registry.fallback(self.session.session_id, read_fallback_request(payload))
                    except (SessionError, ProtocolError):
                        output.append(handshake_response(None, 'Authentication failed.', failed=True, fallback=True))
                        self.close()
                        break
                    self.fallback_enabled = True
                    output.append(handshake_response({
                        'session_id': self.session.session_id,
                        'player_id': self.session.admission.player_id}, fallback=True))
                elif opcode in (Opcode.USER_MESSAGE, Opcode.FALLBACK_MESSAGE):
                    reliable = opcode == Opcode.USER_MESSAGE
                    if not reliable and not self.fallback_enabled:
                        raise ProtocolError('Fallback was not negotiated.')
                    service, body = read_user_message(payload)
                    replies = self.service_handler(self.session, service, body, reliable)
                    for reply_service, reply_body, reply_reliable in replies:
                        if not reply_reliable and not self.fallback_enabled:
                            raise ProtocolError('Cannot send unreliable traffic before fallback.')
                        output.append(user_message(reply_service, reply_body, fallback=not reply_reliable))
                else:
                    # Alert handling still needs its native semantics.
                    raise ProtocolError('Unsupported opcode for connection state.')
        except (ProtocolError, SessionError):
            self.close()
            raise
        except Exception:
            self.close()
            raise
        return output

    def eof(self):
        try:
            self.decoder.eof()
        finally:
            self.close()
