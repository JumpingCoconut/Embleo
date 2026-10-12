"""Account-scoped durable overflow for frozen, unresolved raid contexts."""

import base64
import hashlib
import secrets
import zlib
import msgpack
from accounts import AccountStore

PREFIX = 'PveDetached-'
MAX_CONTEXT_BYTES = 4 * 1024 * 1024


def _name(token):
    if type(token) is not str or not token or len(token) > 4096:
        raise ValueError('Invalid detached battle token.')
    return PREFIX + hashlib.sha256(token.encode('utf-8')).hexdigest() + '.json'


def _pack(value):
    def extension(entry):
        if type(entry) is tuple:
            return msgpack.ExtType(1, _pack(list(entry)))
        if type(entry) is set:
            return msgpack.ExtType(2, _pack(list(entry)))
        raise ValueError('Unsupported detached context value.')
    return msgpack.packb(value, use_bin_type=True, strict_types=True, default=extension)


def _unpack(raw, depth=0):
    if depth > 64:
        raise ValueError('Detached context exceeds nesting limit.')
    def extension(code, data):
        entries = _unpack(data, depth + 1)
        if type(entries) is not list or code not in (1, 2):
            raise ValueError('Invalid detached context extension.')
        return tuple(entries) if code == 1 else set(entries)
    return msgpack.unpackb(raw, raw=False, strict_map_key=False, ext_hook=extension)


def archive(database, account, room):
    """Commit before membership changes; never settle or overwrite a token."""
    prepared = room.get('PreparedBattle', {}).get(account)
    if type(prepared) is not dict:
        raise ValueError('Prepared detached account required.')
    name = _name(prepared.get('EpisodeToken'))
    raw = _pack(room)
    if len(raw) > MAX_CONTEXT_BYTES:
        raise ValueError('Detached context exceeds storage limit.')
    record = dict(Version=1, Content=base64.b64encode(zlib.compress(raw)).decode('ascii'))
    store = AccountStore(database)
    try:
        if not store.connection.execute('SELECT 1 FROM accounts WHERE id=?', (account,)).fetchone():
            raise ValueError('Unknown detached account.')
        if store.exists(account, name):
            if store.read(account, name) != record:
                raise ValueError('Conflicting detached context.')
        else:
            store.write(account, name, record)
        store.connection.commit()
    finally:
        store.close()


def load(database, account, token):
    name = _name(token)
    store = AccountStore(database)
    try:
        if not store.exists(account, name):
            return None
        record = store.read(account, name)
    finally:
        store.close()
    if (type(record) is not dict or record.get('Version') != 1
            or type(record.get('Content')) is not str
            or len(record['Content']) > 2 * MAX_CONTEXT_BYTES):
        raise ValueError('Invalid detached context record.')
    compressed = base64.b64decode(record['Content'], validate=True)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, MAX_CONTEXT_BYTES + 1)
    if len(raw) > MAX_CONTEXT_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid detached context size.')
    room = _unpack(raw)
    prepared = room.get('PreparedBattle', {}).get(account) if type(room) is dict else None
    if (type(prepared) is not dict or type(prepared.get('EpisodeToken')) is not str
            or not secrets.compare_digest(prepared['EpisodeToken'].encode('utf-8'), token.encode('utf-8'))):
        raise ValueError('Detached context account/token mismatch.')
    return room
