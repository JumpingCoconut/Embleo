import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from prizm_sessions import SessionRegistry, SessionError


class SessionTests(unittest.TestCase):
    def test_reconnect_reuses_credentials_with_exclusive_live_identity(self):
        registry = SessionRegistry(reconnect=True)
        tcp, udp = registry.issue('alice', 'room', 1)
        first = registry.open(tcp)
        registry.fallback(first.session_id, udp)
        with self.assertRaises(SessionError):
            registry.open(tcp)
        registry.close(first.session_id)
        second = registry.open(tcp)
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertEqual(first.admission, second.admission)
        self.assertEqual(registry.fallback(second.session_id, udp), second)
        with self.assertRaises(SessionError):
            registry.get(first.session_id)

    def test_reconnect_window_tracks_inbound_activity_and_revocation(self):
        now = [0]
        registry = SessionRegistry(clock=lambda: now[0], session_timeout=10, reconnect=True)
        tcp, udp = registry.issue('alice', 'room', 1, ttl=2)
        session = registry.open(tcp)
        for instant in (5, 14, 23):
            now[0] = instant
            registry.get(session.session_id)
        registry.close(session.session_id)
        now[0] = 25
        session = registry.open(tcp)
        registry.fallback(session.session_id, udp)
        registry.revoke('alice', 'room')
        for credential in (tcp, udp):
            with self.assertRaises(SessionError):
                registry.open(credential)
        self.assertEqual(registry.credential_deadlines, {})

    def test_reconnect_inactive_credentials_expire_without_outbound_refresh(self):
        now = [0]
        registry = SessionRegistry(clock=lambda: now[0], session_timeout=10, reconnect=True)
        tcp, _ = registry.issue('alice', 'room', 1)
        session = registry.open(tcp)
        now[0] = 9
        registry.get(session.session_id, refresh=False)
        registry.close(session.session_id)
        now[0] = 10
        with self.assertRaises(SessionError):
            registry.open(tcp)
        self.assertEqual(registry.credential_deadlines, {})

    def test_reconnect_concurrent_replay_opens_only_one_session(self):
        registry = SessionRegistry(reconnect=True)
        tcp, _ = registry.issue('alice', 'room', 1)
        def attempt(_):
            try:
                return registry.open(tcp)
            except SessionError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(16)))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_single_use_credentials_and_room_bound_fallback(self):
        registry = SessionRegistry()
        tcp, udp = registry.issue('alice', 'room-one', 1)
        other_tcp, other_udp = registry.issue('alice', 'room-two', 1)
        session = registry.open(tcp)
        self.assertEqual(session.admission.room_id, 'room-one')
        for credential in (tcp, udp, 'unknown'):
            with self.assertRaises(SessionError):
                registry.open(credential)
        with self.assertRaises(SessionError):
            registry.fallback(session.session_id, other_udp)
        self.assertEqual(registry.fallback(session.session_id, udp), session)
        with self.assertRaises(SessionError):
            registry.fallback(session.session_id, udp)
        self.assertEqual(registry.open(other_tcp).admission.room_id, 'room-two')

    def test_expiry_and_revocation_preserve_unrelated_rooms(self):
        now = [100]
        registry = SessionRegistry(clock=lambda: now[0],session_timeout=5)
        tcp, udp = registry.issue('alice', 'room', 1, ttl=5)
        session = registry.open(tcp)
        now[0] = 105
        with self.assertRaises(SessionError):
            registry.get(session.session_id)
        with self.assertRaises(SessionError):
            registry.fallback(session.session_id, udp)
        tcp, _ = registry.issue('alice', 'room', 1)
        other, _ = registry.issue('bob', 'room', 2)
        registry.revoke('alice', 'room')
        with self.assertRaises(SessionError):
            registry.open(tcp)
        self.assertEqual(registry.open(other).admission.account_id, 'bob')

    def test_active_session_outlives_admission_and_idle_session_expires(self):
        now = [100]
        registry = SessionRegistry(clock=lambda: now[0],session_timeout=10)
        tcp, udp = registry.issue('alice','room',1,ttl=2)
        session = registry.open(tcp)
        for instant in (103,109,118,127):
            now[0] = instant
            self.assertEqual(registry.get(session.session_id).admission.account_id,'alice')
        with self.assertRaises(SessionError):
            registry.fallback(session.session_id,udp)
        now[0] = 137
        with self.assertRaises(SessionError):
            registry.get(session.session_id)

    def test_concurrent_replay_only_opens_one_session(self):
        registry = SessionRegistry()
        tcp, _ = registry.issue('alice', 'room', 1)
        def attempt(_):
            try:
                return registry.open(tcp)
            except SessionError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(16)))
        self.assertEqual(sum(value is not None for value in results), 1)
