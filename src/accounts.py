"""Persistent accounts using the client's existing bearer-token protocol.

The request owns a SQLite transaction. Existing JSON-shaped saves are retained
verbatim, but keyed by account rather than shared filesystem paths.
"""

import base64
import binascii
import hashlib
import json
import secrets
import sqlite3
import struct
import time
import zlib
from pathlib import Path


class AccountError(ValueError):
    pass


def default_saves():
    # Generate player state from master data, never clone the live shared save.
    from scripts.generate.generate_save_file import (
        ALL_EQUIPMENT, generateUserCharacter, generateUserEquipment,
        generateUserEpisode, generateUserItem,
    )
    return {
        "UserCharacter.json": generateUserCharacter(),
        "UserEquipment.json": generateUserEquipment(ALL_EQUIPMENT),
        "UserEpisode.json": generateUserEpisode(),
        "UserItems.json": generateUserItem(),
        "UserParameter.json": {
            "Gold": 10000, "Coin": 10000, "NobleCoin": 9, "MissionRank": 1,
            "MissionExp": 0, "FollowCount": 0, "FollowerCount": 0,
            "BlockCount": 0, "Flags": [], "MissionNextExp": 3,
            "Word": "Hello, hello, it's nice to meet you.",
            "FavoriteChrId": "pl001", "EmblemId": "emblem_sh001_001",
            "NobleStartAtUnix": 0, "NobleEndAtUnix": 0,
        },
        "HcBalance.json": {"PaidBalance": 3000, "FreeBalance": 3000,
                           "PaidBefore": 500, "FreeBefore": 500},
        "PieUserSetting.json": {"BirthYear": 0, "BirthMonth": 0,
            "HasBirthday": False, "HasStopper": False, "HasParentalpass": False,
            "Banned": False},
        "Presents.json": {"userPresents": [], "UserPresents": []},
        "PresentHistory.json": {"UserPresents": []},
        "checkpoint.txt": {},
    }


def save_key(path):
    """Only the old player paths are redirected; master data stays shared."""
    path = str(path).replace("\\", "/").removeprefix("./")
    if path == "checkpoint.txt":
        return path
    prefix = "data/user/"
    if path.startswith(prefix):
        name = path[len(prefix):]
        if "/" not in name and name.endswith(".json"):
            return name
    return None


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY, player_code TEXT UNIQUE NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tokens (
                hash TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(id)
            );
            CREATE TABLE IF NOT EXISTS saves (
                account_id TEXT NOT NULL REFERENCES accounts(id),
                name TEXT NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY (account_id, name)
            );
            CREATE TABLE IF NOT EXISTS icons (
                account_id TEXT PRIMARY KEY REFERENCES accounts(id),
                revision TEXT NOT NULL, png BLOB NOT NULL
            );
        """)
        self.connection.execute("BEGIN IMMEDIATE")

    def authenticate(self, token):
        row = self.connection.execute(
            "SELECT account_id FROM tokens WHERE hash=?", (token_hash(token),)
        ).fetchone()
        return row[0] if row else None

    def create(self, name, saves):
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 64:
            raise AccountError("Nickname must contain 2 to 64 characters.")
        account_id = secrets.token_hex(16)
        player_code = secrets.token_hex(8)
        user = {"id": account_id, "name": name, "idHash": account_id,
                "playerCode": player_code}
        self.connection.execute("INSERT INTO accounts VALUES (?, ?, ?)",
                                (account_id, player_code, int(time.time())))
        for key, value in saves.items():
            self.write(account_id, key, value)
        self.write(account_id, "User.json", user)
        if not self.exists(account_id, "checkpoint.txt"):
            self.write(account_id, "checkpoint.txt", {})
        token = secrets.token_urlsafe(32)
        self.connection.execute("INSERT INTO tokens VALUES (?, ?)",
                                (token_hash(token), account_id))
        return account_id, token

    def read(self, account_id, name):
        row = self.connection.execute(
            "SELECT value FROM saves WHERE account_id=? AND name=?",
            (account_id, name)).fetchone()
        if row is None:
            raise AccountError("Missing account save: " + name)
        return json.loads(row[0])

    def exists(self, account_id, name):
        return self.connection.execute(
            "SELECT 1 FROM saves WHERE account_id=? AND name=?",
            (account_id, name)).fetchone() is not None

    def write(self, account_id, name, value):
        self.connection.execute("""INSERT INTO saves VALUES (?, ?, ?)
            ON CONFLICT(account_id, name) DO UPDATE SET value=excluded.value""",
            (account_id, name, json.dumps(value, ensure_ascii=False)))

    def put_icon(self, account_id, png):
        revision = hashlib.sha256(png).hexdigest()
        self.connection.execute("""INSERT INTO icons VALUES (?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                revision=excluded.revision, png=excluded.png""",
            (account_id, revision, png))
        return revision

    def get_icon(self, account_id, revision):
        row = self.connection.execute(
            "SELECT png FROM icons WHERE account_id=? AND revision=?",
            (account_id, revision)).fetchone()
        return row[0] if row else None

    def icon_revision(self, account_id):
        row = self.connection.execute("SELECT revision FROM icons WHERE account_id=?",
                                      (account_id,)).fetchone()
        return row[0] if row else None

    def find_account(self, identifier):
        row = self.connection.execute(
            "SELECT id FROM accounts WHERE id=? OR player_code=?",
            (identifier, identifier)).fetchone()
        return row[0] if row else None

    def close(self):
        self.connection.close()


def decode_icon(encoded):
    """Validate a bounded PNG without resizing the character capture."""
    if not isinstance(encoded, str) or len(encoded) > 2_800_000:
        raise AccountError("Invalid icon upload.")
    try:
        png = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AccountError("Icon must be base64 PNG data.") from exc
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise AccountError("Icon must be PNG data.")
    offset, chunks, data = 8, [], bytearray()
    width = height = 0
    while offset + 12 <= len(png):
        size = struct.unpack_from(">I", png, offset)[0]
        end = offset + 12 + size
        if end > len(png):
            raise AccountError("Truncated PNG.")
        kind = png[offset + 4:offset + 8]
        body = png[offset + 8:end - 4]
        crc = struct.unpack_from(">I", png, end - 4)[0]
        if zlib.crc32(kind + body) != crc:
            raise AccountError("Invalid PNG checksum.")
        if not chunks:
            if kind != b"IHDR" or size != 13:
                raise AccountError("Invalid PNG header.")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", body)
            if (not 1 <= width <= 1024 or not 1 <= height <= 1024
                    or depth != 8 or color not in (2, 6)
                    or compression or filtering or interlace):
                raise AccountError("Unsupported icon PNG format.")
        if kind == b"IDAT":
            data.extend(body)
        chunks.append(kind)
        offset = end
        if kind == b"IEND":
            if size or offset != len(png):
                raise AccountError("Invalid PNG end.")
            break
    if not chunks or chunks[-1] != b"IEND" or not data:
        raise AccountError("Incomplete PNG.")
    expected = height * (1 + width * (4 if color == 6 else 3))
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(data), expected + 1)
        if len(pixels) != expected or not decoder.eof or decoder.unused_data:
            raise AccountError("Invalid PNG image data.")
    except zlib.error as exc:
        raise AccountError("Invalid PNG image data.") from exc
    stride = expected // height
    if any(pixels[i] > 4 for i in range(0, expected, stride)):
        raise AccountError("Invalid PNG filter.")
    return png
