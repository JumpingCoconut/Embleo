"""Prizm connection state machine for the TCP-first local prototype.

The listener must supply TLS. This module does not bind public ports or enable
HTTP raid discovery. Service handlers receive validated session identity.
"""

import base64
import secrets
import struct

from prizm_diagnostics import rejection_reason

from prizm_protocol import (FrameDecoder, Opcode, ProtocolError,
                            read_hello_request, read_fallback_request,
                            handshake_response, read_user_message, user_message, ping_reply)
from prizm_sessions import SessionError
from prizm_rooms import RoomError


class Connection:
    # Four dispatch turns of small messages. The byte cap also bounds large
    # messages, independently of the existing notification-count limit.
    MAX_PENDING_FRAMES = 128
    MAX_PENDING_BYTES = 4 * 1024 * 1024

    def __init__(self, registry, service_handler):
        self.registry = registry
        self.service_handler = service_handler
        self.decoder = FrameDecoder()
        self.session = None
        self.fallback_enabled = False
        self.closed = False
        self.pending = []
        self.pending_keys = []
        self.rejection_context = "transport"
        self.pending_bytes = 0
        self.outbound_ready = None
        self.close_observer = None

    def notify(self, service, body, reliable=True, coalesce=None):
        if self.closed or self.session is None:
            return
        if not reliable and not self.fallback_enabled:
            return
        outgoing = user_message(service,body,fallback=not reliable)
        if coalesce is not None and coalesce in self.pending_keys:
            index = self.pending_keys.index(coalesce)
            if self.pending_bytes - len(self.pending[index]) + len(outgoing) > self.MAX_PENDING_BYTES:
                self.close('queue_overflow')
                return
            self.pending_bytes -= len(self.pending[index])
            self.pending.pop(index)
            self.pending_keys.pop(index)
            self.pending.append(outgoing)
            self.pending_keys.append(coalesce)
            self.pending_bytes += len(outgoing)
            if self.outbound_ready is not None:
                self.outbound_ready.set()
            return
        if (len(self.pending) >= self.MAX_PENDING_FRAMES
                or self.pending_bytes + len(outgoing) > self.MAX_PENDING_BYTES):
            self.close('queue_overflow')
            return
        self.pending.append(outgoing)
        self.pending_keys.append(coalesce)
        self.pending_bytes += len(outgoing)
        if self.outbound_ready is not None:
            self.outbound_ready.set()

    def notifications(self):
        if self.closed:
            self.pending.clear()
            self.pending_keys.clear()
            self.pending_bytes = 0
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
        self.pending_bytes = 0
        return result

    def close(self, reason=None):
        if self.closed:
            return
        self.closed = True
        if reason is not None and self.close_observer is not None:
            self.close_observer(reason, len(self.pending), self.pending_bytes)
        if self.outbound_ready is not None:
            self.outbound_ready.set()
        self.pending.clear()
        self.pending_keys.clear()
        self.pending_bytes = 0
        if self.session is not None:
            if hasattr(self.service_handler,'disconnected'):
                self.service_handler.disconnected(self)
            self.registry.close(self.session.session_id)

    def receive(self, data):
        return self.receive_frames(self.decoder.iter_feed(data))

    def receive_frames(self, frames):
        if self.closed:
            raise ProtocolError('Connection is closed.')
        output = []
        operation = "transport"
        try:
            for opcode, payload in frames:
                operation = "transport"
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
                        'encryption': False,
                        # Native UdpEncryption initializes both MACs even with
                        # encryption disabled (constructor RVA 0x1B1F294).
                        # TCP fallback stays inside the authenticated TLS stream.
                        'mac_key': base64.b64encode(secrets.token_bytes(32)).decode('ascii')}))
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
                        credential = read_fallback_request(payload)
                        # Native TCP-only clients send a zero-length fallback
                        # credential on their already authenticated TLS stream.
                        # A supplied credential must still match this admission.
                        if credential:
                            self.registry.fallback(self.session.session_id, credential)
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
                    if service in (1000, 2000) and len(body) >= 2:
                        command = struct.unpack_from("<h", body)[0]
                        if 0 <= command <= 36:
                            operation = "service_%d_command_%d" % (service, command)
                    replies = self.service_handler(self.session, service, body, reliable)
                    for reply_service, reply_body, reply_reliable in replies:
                        if not reply_reliable and not self.fallback_enabled:
                            raise ProtocolError('Cannot send unreliable traffic before fallback.')
                        output.append(user_message(reply_service, reply_body, fallback=not reply_reliable))
                else:
                    # Alert handling still needs its native semantics.
                    raise ProtocolError('Unsupported opcode for connection state.')
        except (ProtocolError, SessionError, RoomError) as error:
            self.rejection_context = operation + "_reason_" + rejection_reason(error)
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
