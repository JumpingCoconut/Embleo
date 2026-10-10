"""Short-lived, room-bound transport credentials for the local raid service.

HTTP must issue these only after account authentication and room admission.
This registry is process-local: HTTP and transport must share its instance.
"""

from dataclasses import dataclass
import hashlib
import secrets
import threading
import time


class SessionError(ValueError):
    pass


@dataclass(frozen=True)
class Admission:
    account_id: str
    room_id: str
    player_id: int
    expires_at: float


@dataclass(frozen=True)
class Session:
    session_id: str
    admission: Admission
    expires_at: float


class SessionRegistry:
    def __init__(self, clock=time.monotonic, limit=4096, session_timeout=120,
                 reconnect=False):
        if (type(limit) is not int or limit < 2
                or type(session_timeout) not in (int, float)
                or not 0 < session_timeout <= 3600 or type(reconnect) is not bool):
            raise SessionError('Invalid session registry limits.')
        self.clock = clock
        self.limit = limit
        self.session_timeout = session_timeout
        self.reconnect = reconnect
        self.lock = threading.Lock()
        self.credentials = {}
        self.sessions = {}
        self.credential_deadlines = {}

    def _expire(self):
        now = self.clock()
        self.credentials = {key: value for key, value in self.credentials.items()
                            if self.credential_deadlines.get(key, value[0].expires_at) > now}
        self.credential_deadlines = {key: deadline for key, deadline in
                                    self.credential_deadlines.items() if key in self.credentials}
        self.sessions = {key: value for key, value in self.sessions.items()
                         if value.expires_at > now}

    @staticmethod
    def _key(token):
        if not isinstance(token, str) or not 1 <= len(token) <= 512:
            raise SessionError('Invalid transport credential.')
        return hashlib.sha256(token.encode('utf-8')).digest()

    def issue(self, account_id, room_id, player_id, ttl=120):
        if (not isinstance(account_id, str) or not account_id
                or not isinstance(room_id, str) or not room_id
                or type(player_id) is not int or not 0 < player_id < 2**31
                or type(ttl) not in (int, float) or not 0 < ttl <= 3600):
            raise SessionError('Invalid room admission.')
        with self.lock:
            self._expire()
            if len(self.credentials) + len(self.sessions) + 2 > self.limit:
                raise SessionError('Transport session capacity reached.')
            admission = Admission(account_id, room_id, player_id, self.clock() + ttl)
            tcp, udp = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.credentials[self._key(tcp)] = (admission, 'tcp')
            self.credentials[self._key(udp)] = (admission, 'udp')
            return tcp, udp

    def open(self, credential):
        key = self._key(credential)
        with self.lock:
            self._expire()
            entry = self.credentials.get(key)
            if entry is None or entry[1] != 'tcp':
                raise SessionError('Unknown or expired TCP credential.')
            if self.reconnect:
                if any((session.admission.account_id, session.admission.room_id) ==
                       (entry[0].account_id, entry[0].room_id)
                       for session in self.sessions.values()):
                    raise SessionError('Room member already has a transport session.')
                if len(self.credentials) + len(self.sessions) >= self.limit:
                    raise SessionError('Transport session capacity reached.')
            else:
                del self.credentials[key]
            session = Session(secrets.token_urlsafe(24), entry[0],
                              self.clock() + self.session_timeout)
            self.sessions[session.session_id] = session
            if self.reconnect:
                for credential_key, credential in self.credentials.items():
                    if credential[0] == session.admission:
                        self.credential_deadlines[credential_key] = session.expires_at
            return session

    def fallback(self, session_id, credential):
        key = self._key(credential)
        with self.lock:
            self._expire()
            session = self.sessions.get(session_id)
            entry = self.credentials.get(key)
            if (session is None or entry is None or entry[1] != 'udp'
                    or entry[0] != session.admission):
                raise SessionError('Fallback credential does not match the session.')
            if not self.reconnect:
                del self.credentials[key]
            return session

    def get(self, session_id, refresh=True):
        with self.lock:
            self._expire()
            session = self.sessions.get(session_id)
            if session is None:
                raise SessionError('Unknown or expired transport session.')
            if refresh:
                session = Session(session.session_id, session.admission,
                                  self.clock() + self.session_timeout)
                self.sessions[session_id] = session
                if self.reconnect:
                    # Native reconnect uses the original HTTP credentials.
                    # Only authenticated inbound activity extends their window.
                    for key, entry in self.credentials.items():
                        if entry[0] == session.admission:
                            self.credential_deadlines[key] = session.expires_at
            return session

    def revoke(self, account_id, room_id):
        with self.lock:
            self.credentials = {key: value for key, value in self.credentials.items()
                                if (value[0].account_id, value[0].room_id) != (account_id, room_id)}
            self.sessions = {key: value for key, value in self.sessions.items()
                             if (value.admission.account_id, value.admission.room_id) != (account_id, room_id)}
            self.credential_deadlines = {key: deadline for key, deadline in
                                        self.credential_deadlines.items() if key in self.credentials}

    def close(self, session_id):
        with self.lock:
            session = self.sessions.pop(session_id, None)
            if session is not None and not self.reconnect:
                self.credentials = {key: value for key, value in self.credentials.items()
                                    if value[0] != session.admission}
