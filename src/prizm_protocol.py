"""Verified Prizm framing primitives; no listener or public raid enablement.

Outer UserMessage layout is established by native Write/Read at 0x1B197D0
and 0x1B1A224. RPC headers are established by RpcClient.Request and
OnReceiveCommand. Payload schemas are deliberately left to their services.
"""

import json
import struct
from enum import IntEnum


class Opcode(IntEnum):
    PING = 1
    HELLO_REQUEST = 2
    HELLO_RESPONSE = 3
    UDP_HELLO_REQUEST = 4
    UDP_HELLO_RESPONSE = 5
    ALERT = 6
    USER_MESSAGE = 7
    FALLBACK_REQUEST = 8
    FALLBACK_RESPONSE = 9
    FALLBACK_MESSAGE = 10


class ProtocolError(ValueError):
    pass


MAX_FRAME_SIZE = 1024 * 1024
FRAME_HEADER = struct.Struct('<Bi')
USER_HEADER = struct.Struct('<hi')
RPC_REQUEST = struct.Struct('<hh')
COMMAND = struct.Struct('<h')
RPC_RESPONSE = struct.Struct('<hhh')


def frame(opcode, payload):
    try:
        opcode = Opcode(opcode)
    except ValueError as error:
        raise ProtocolError('Unknown opcode.') from error
    if len(payload) > MAX_FRAME_SIZE:
        raise ProtocolError('Frame exceeds size limit.')
    return FRAME_HEADER.pack(opcode, len(payload)) + payload


class FrameDecoder:
    """Decode fragmented/coalesced TCP reads, bounding buffered frame data."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        # Consume incrementally so one read containing many frames does not
        # require retaining the entire batch in the decoder.
        output = []
        position = 0
        while position < len(data):
            needed = FRAME_HEADER.size
            if len(self.buffer) >= FRAME_HEADER.size:
                opcode, length = FRAME_HEADER.unpack_from(self.buffer)
                if length < 0 or length > MAX_FRAME_SIZE:
                    raise ProtocolError('Invalid frame length.')
                try:
                    Opcode(opcode)
                except ValueError as error:
                    raise ProtocolError('Unknown opcode.') from error
                needed += length
            take = min(needed - len(self.buffer), len(data) - position)
            self.buffer.extend(data[position:position + take])
            position += take
            if len(self.buffer) < FRAME_HEADER.size:
                continue
            opcode, length = FRAME_HEADER.unpack_from(self.buffer)
            if length < 0 or length > MAX_FRAME_SIZE:
                raise ProtocolError('Invalid frame length.')
            try:
                opcode = Opcode(opcode)
            except ValueError as error:
                raise ProtocolError('Unknown opcode.') from error
            if len(self.buffer) == FRAME_HEADER.size + length:
                output.append((opcode, bytes(self.buffer[FRAME_HEADER.size:])))
                self.buffer.clear()
        return output

    def eof(self):
        if self.buffer:
            raise ProtocolError('Truncated frame at EOF.')


def user_message(service, payload, fallback=False):
    body = USER_HEADER.pack(service, len(payload)) + payload
    return frame(Opcode.FALLBACK_MESSAGE if fallback else Opcode.USER_MESSAGE, body)


def read_user_message(payload):
    if len(payload) < USER_HEADER.size:
        raise ProtocolError('Truncated service header.')
    service, length = USER_HEADER.unpack_from(payload)
    if length < 0 or length != len(payload) - USER_HEADER.size:
        raise ProtocolError('Invalid service payload length.')
    return service, payload[USER_HEADER.size:]


def rpc_request(command, request_id, payload):
    return RPC_REQUEST.pack(command, request_id) + payload


def command_message(command, payload):
    # RpcClient.Send writes a command, then MessagePack; no request ID.
    return COMMAND.pack(command) + payload


def read_command_message(payload):
    if len(payload) < COMMAND.size:
        raise ProtocolError('Truncated command message.')
    return COMMAND.unpack_from(payload)[0], payload[COMMAND.size:]


def read_rpc_request(payload):
    if len(payload) < RPC_REQUEST.size:
        raise ProtocolError('Truncated RPC request.')
    return (*RPC_REQUEST.unpack_from(payload), payload[RPC_REQUEST.size:])


def rpc_response(command, request_id, payload, status=1):
    return RPC_RESPONSE.pack(command, status, request_id) + payload


def read_rpc_response(payload):
    if len(payload) < RPC_RESPONSE.size:
        raise ProtocolError('Truncated RPC response.')
    return (*RPC_RESPONSE.unpack_from(payload), payload[RPC_RESPONSE.size:])


def _short_bytes(value):
    if len(value) > 32767:
        raise ProtocolError('Handshake field exceeds signed-short limit.')
    return struct.pack('<h', len(value)) + value


def _read_short_bytes(payload, offset):
    if offset + 2 > len(payload):
        raise ProtocolError('Truncated handshake length.')
    length = struct.unpack_from('<h', payload, offset)[0]
    offset += 2
    if length < 0 or offset + length > len(payload):
        raise ProtocolError('Invalid handshake field length.')
    return payload[offset:offset + length], offset + length


def hello_request(credential):
    return frame(Opcode.HELLO_REQUEST, b'\x01' + _short_bytes(credential.encode('utf-8')))


def read_hello_request(payload):
    if not payload or payload[0] != 1:
        raise ProtocolError('Unsupported protocol version.')
    credential = read_fallback_request(payload[1:])
    if not credential:
        raise ProtocolError('Hello requires a credential.')
    return credential


def fallback_request(credential):
    return frame(Opcode.FALLBACK_REQUEST, _short_bytes(credential.encode('utf-8')))


def read_fallback_request(payload):
    credential, end = _read_short_bytes(payload, 0)
    if end != len(payload):
        raise ProtocolError('Invalid credential payload.')
    try:
        return credential.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ProtocolError('Credential must be UTF-8.') from error


def handshake_response(session, message='', failed=False, fallback=False):
    # Handshake success is zero, unlike RPC success (one).
    token = b'' if session is None else json.dumps(
        session, separators=(',', ':'), allow_nan=False).encode('utf-8')
    payload = bytes([int(failed)]) + _short_bytes(token) + _short_bytes(message.encode('utf-8'))
    return frame(Opcode.FALLBACK_RESPONSE if fallback else Opcode.HELLO_RESPONSE, payload)


def read_handshake_response(payload):
    if not payload or payload[0] not in (0, 1):
        raise ProtocolError('Invalid handshake status.')
    token, offset = _read_short_bytes(payload, 1)
    message, offset = _read_short_bytes(payload, offset)
    if offset != len(payload):
        raise ProtocolError('Trailing handshake data.')
    try:
        session = json.loads(token.decode('utf-8')) if token else None
        message = message.decode('utf-8')
    except (UnicodeDecodeError, ValueError) as error:
        raise ProtocolError('Invalid handshake JSON or text.') from error
    if session is not None and not isinstance(session, dict):
        raise ProtocolError('Session token must be an object.')
    return payload[0], session, message


def ping_reply(payload):
    # PingFrame.Write: int32 length (8), followed by DateTime.ToBinary's
    # int64 value. Echo the opaque timestamp so the client computes its RTT.
    # Native client HandleFrame only records RTT; it does not echo our reply.
    if len(payload) != 12 or struct.unpack_from('<i', payload)[0] != 8:
        raise ProtocolError('Invalid ping payload.')
    return frame(Opcode.PING, payload)
