import sys
import base64
import unittest
import struct
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from prizm_connection import Connection
from prizm_sessions import SessionRegistry, SessionError
from prizm_protocol import (FrameDecoder, Opcode, ProtocolError, hello_request,
                            fallback_request, read_handshake_response,
                            user_message, read_user_message, frame)


class ConnectionTests(unittest.TestCase):
    def test_native_empty_fallback_requires_authenticated_connection(self):
        self.connection.receive(hello_request(self.tcp))
        reply = self.connection.receive(fallback_request(''))
        self.assertEqual(read_handshake_response(FrameDecoder().feed(reply[0])[0][1])[0], 0)
        self.assertTrue(self.connection.fallback_enabled)
        anonymous = Connection(self.registry, self.handler)
        with self.assertRaises(ProtocolError):
            anonymous.receive(fallback_request(''))
        self.assertTrue(anonymous.closed)
        empty_hello = Connection(self.registry, self.handler)
        response = empty_hello.receive(hello_request(''))
        self.assertEqual(read_handshake_response(FrameDecoder().feed(response[0])[0][1])[0], 1)
        self.assertTrue(empty_hello.closed)

    def test_native_reconnect_repeats_hello_and_fallback_after_socket_eof(self):
        registry = SessionRegistry(reconnect=True)
        tcp, udp = registry.issue('alice', 'room', 1)
        handler = Mock(return_value=[])
        first = Connection(registry, handler)
        first.receive(hello_request(tcp) + fallback_request(udp))
        duplicate = Connection(registry, handler)
        self.assertEqual(read_handshake_response(FrameDecoder().feed(
            duplicate.receive(hello_request(tcp))[0])[0][1])[0], 1)
        self.assertTrue(duplicate.closed)
        first.eof()
        second = Connection(registry, handler)
        responses = second.receive(hello_request(tcp) + fallback_request(udp))
        self.assertEqual([read_handshake_response(body)[0] for _, body in
                          FrameDecoder().feed(b''.join(responses))], [0, 0])
        second.receive(user_message(1000, b'rejoin'))
        self.assertEqual(handler.call_args.args[0].admission, first.session.admission)
        registry.revoke('alice', 'room')
        self.assertEqual(second.notifications(), [])
        self.assertTrue(second.closed)

    def test_notifications_cannot_bypass_revocation_or_extend_idle_expiry(self):
        for revoke in (False, True):
            now = [0]
            registry = SessionRegistry(clock=lambda: now[0], session_timeout=10)
            tcp, _ = registry.issue('alice', 'room', 1)
            connection = Connection(registry, lambda *args: [])
            connection.receive(hello_request(tcp))
            now[0] = 5
            connection.notify(1000, b'first')
            self.assertEqual(len(connection.notifications()), 1)
            connection.notify(1000, b'private room update')
            if revoke:
                registry.revoke('alice', 'room')
            else:
                now[0] = 11
            self.assertEqual(connection.notifications(), [])
            self.assertTrue(connection.closed)
            self.assertEqual(connection.pending, [])

    def test_authenticated_ping_echo_preserves_timestamp(self):
        self.connection.receive(hello_request(self.tcp))
        payload = struct.pack('<iQ',8,0x4000000000000001)
        wire = frame(Opcode.PING,payload)
        self.assertEqual(self.connection.receive(wire),[wire])
        self.handler.assert_not_called()
        with self.assertRaises(ProtocolError):
            self.connection.receive(frame(Opcode.PING,b''))
        self.assertTrue(self.connection.closed)

    def setUp(self):
        self.registry = SessionRegistry()
        self.tcp, self.udp = self.registry.issue('alice', 'room', 1)
        self.handler = Mock(return_value=[(1000, b'reply', True)])
        self.connection = Connection(self.registry, self.handler)

    def test_handshake_fallback_and_bound_service_identity(self):
        wire = hello_request(self.tcp) + fallback_request(self.udp) + user_message(1000, b'request')
        replies = []
        for byte in wire:
            replies.extend(self.connection.receive(bytes([byte])))
        decoded = FrameDecoder().feed(b''.join(replies))
        self.assertEqual([opcode for opcode, _ in decoded], [3, 9, 7])
        status, token, _ = read_handshake_response(decoded[0][1])
        self.assertEqual(status, 0)
        self.assertEqual(token['player_id'], 1)
        self.assertFalse(token['encryption'])
        self.assertEqual(len(base64.b64decode(token['mac_key'], validate=True)), 32)
        self.assertEqual(read_handshake_response(decoded[1][1])[1]['session_id'], token['session_id'])
        self.assertEqual(read_user_message(decoded[2][1]), (1000, b'reply'))
        session, service, body, reliable = self.handler.call_args.args
        self.assertEqual((session.admission.account_id, session.admission.room_id), ('alice', 'room'))
        self.assertEqual((service, body, reliable), (1000, b'request', True))
        self.connection.eof()
        with self.assertRaises(SessionError):
            self.registry.get(token['session_id'])

    def test_invalid_hello_returns_failure_and_never_dispatches(self):
        replies = self.connection.receive(hello_request('wrong') + user_message(1000, b'data'))
        self.assertEqual(read_handshake_response(FrameDecoder().feed(replies[0])[0][1])[0], 1)
        self.assertTrue(self.connection.closed)
        self.handler.assert_not_called()

    def test_unauthenticated_and_unnegotiated_fallback_traffic_rejected(self):
        with self.assertRaises(ProtocolError):
            self.connection.receive(user_message(1000, b'data'))
        self.handler.assert_not_called()
        self.connection = Connection(self.registry, self.handler)
        self.connection.receive(hello_request(self.tcp))
        with self.assertRaises(ProtocolError):
            self.connection.receive(user_message(1000, b'data', fallback=True))
        self.handler.assert_not_called()

    def test_other_room_fallback_rejected(self):
        _, udp = self.registry.issue('alice', 'other-room', 1)
        self.connection.receive(hello_request(self.tcp))
        reply = self.connection.receive(fallback_request(udp))[0]
        opcode, body = FrameDecoder().feed(reply)[0]
        self.assertEqual(opcode, Opcode.FALLBACK_RESPONSE)
        self.assertEqual(read_handshake_response(body)[0], 1)
        self.assertTrue(self.connection.closed)
