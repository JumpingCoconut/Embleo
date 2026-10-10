import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from prizm_protocol import (FrameDecoder, Opcode, ProtocolError, MAX_FRAME_SIZE,
                            frame, user_message, read_user_message, rpc_request,
                            read_rpc_request, rpc_response, read_rpc_response)
from prizm_protocol import (hello_request, read_hello_request, fallback_request,
                            read_fallback_request, handshake_response,
                            read_handshake_response)
from prizm_protocol import command_message, read_command_message


class PrizmProtocolTests(unittest.TestCase):
    def test_send_message_has_no_request_id(self):
        payload = bytes.fromhex('8201a1610201')
        wire = bytes.fromhex('0700') + payload
        self.assertEqual(command_message(7,payload),wire)
        self.assertEqual(read_command_message(wire),(7,payload))
    def test_hello_and_fallback_wire_vectors(self):
        self.assertEqual(hello_request('abc'), bytes.fromhex('02 06000000 01 0300 616263'))
        self.assertEqual(read_hello_request(bytes.fromhex('01 0300 616263')), 'abc')
        self.assertEqual(fallback_request('abc'), bytes.fromhex('08 05000000 0300 616263'))
        self.assertEqual(read_fallback_request(bytes.fromhex('0300 616263')), 'abc')
        response = bytes.fromhex('03 0a000000 00 0200 7b7d 0300 6f6b21')
        self.assertEqual(handshake_response({}, 'ok!'), response)
        self.assertEqual(read_handshake_response(response[5:]), (0, {}, 'ok!'))
        self.assertEqual(handshake_response(None, failed=True, fallback=True),
                         bytes.fromhex('09 05000000 01 0000 0000'))

    def test_handshake_rejects_malformed_or_oversized_fields(self):
        for payload in (b'', b'\x02\x00\x00', b'\x01\xff\xff',
                        b'\x01\x02\x00a', b'\x01\x01\x00\xff',
                        b'\x01\x01\x00ab', b'\x01\x00\x00'):
            with self.assertRaises(ProtocolError):
                read_hello_request(payload)
        for payload in (b'', b'\x02\x00\x00\x00\x00',
                        b'\x00\x01\x00[\x00\x00',
                        b'\x00\x02\x00[]\x00\x00',
                        b'\x00\x00\x00\x00\x00x'):
            with self.assertRaises(ProtocolError):
                read_handshake_response(payload)
        with self.assertRaises(ProtocolError):
            hello_request('x' * 32768)

    def test_independent_wire_vector_and_every_tcp_split(self):
        # service 1000, command 1, request 42, numeric map {1: False}.
        wire = bytes.fromhex('07 0d000000 e803 07000000 0100 2a00 8101c2')
        request = rpc_request(1, 42, bytes.fromhex('8101c2'))
        self.assertEqual(user_message(1000, request), wire)
        for split in range(len(wire) + 1):
            decoder = FrameDecoder()
            decoded = decoder.feed(wire[:split]) + decoder.feed(wire[split:])
            self.assertEqual(decoded, [(Opcode.USER_MESSAGE, wire[5:])])
            service, body = read_user_message(decoded[0][1])
            self.assertEqual(service, 1000)
            self.assertEqual(read_rpc_request(body), (1, 42, bytes.fromhex('8101c2')))
            decoder.eof()

    def test_coalesced_zero_length_and_fragmented_frames(self):
        wire = frame(Opcode.PING, b'') + frame(Opcode.ALERT, b'ab')
        decoder = FrameDecoder()
        received = []
        for byte in wire:
            received.extend(decoder.feed(bytes([byte])))
        self.assertEqual(received, [(Opcode.PING, b''), (Opcode.ALERT, b'ab')])
        self.assertEqual(FrameDecoder().feed(wire), received)

    def test_response_status_and_request_id_order(self):
        wire = bytes.fromhex('0c00 0100 ff7f 80')
        self.assertEqual(rpc_response(12, 32767, b'\x80'), wire)
        self.assertEqual(read_rpc_response(wire), (12, 1, 32767, b'\x80'))
        self.assertEqual(user_message(1000, wire, fallback=True)[0], 10)

    def test_invalid_lengths_opcodes_and_truncation(self):
        for header in (struct.pack('<Bi', 7, -1),
                       struct.pack('<Bi', 7, MAX_FRAME_SIZE + 1),
                       struct.pack('<Bi', 255, 0)):
            with self.assertRaises(ProtocolError):
                FrameDecoder().feed(header)
        decoder = FrameDecoder()
        decoder.feed(frame(7, b'abc')[:-1])
        with self.assertRaises(ProtocolError):
            decoder.eof()
        for payload in (b'', struct.pack('<hi', 1000, -1),
                        struct.pack('<hi', 1000, 2) + b'a'):
            with self.assertRaises(ProtocolError):
                read_user_message(payload)
        for parser, size in ((read_rpc_request, 4), (read_rpc_response, 6)):
            for length in range(size):
                with self.assertRaises(ProtocolError):
                    parser(bytes(length))
