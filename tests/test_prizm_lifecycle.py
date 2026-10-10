import asyncio
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from prizm_connection import Connection
from prizm_protocol import FrameDecoder, hello_request, read_command_message, read_user_message
from prizm_room_service import RoomService
from prizm_rooms import RoomError, Rooms
from prizm_runtime import Runtime
from prizm_sessions import SessionError, SessionRegistry
from test_prizm_lobby import player


class LobbyExpiryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.registry = SessionRegistry(clock=lambda: self.now,
                                        session_timeout=10, reconnect=True)
        self.rooms = Rooms(4)
        self.service = RoomService(self.rooms, self.registry)

    def create(self, account='alice'):
        return self.service.create(player(account), 'ep', 'v', False, 1, 1, (60, 3, 20))

    def connect(self, tcp):
        connection = Connection(self.registry, self.service)
        connection.receive(hello_request(tcp))
        return connection

    def test_expired_socket_loss_frees_membership_before_new_create(self):
        old, tcp, _ = self.create()
        self.connect(tcp).close()
        self.now = 10
        new, _, _ = self.create()
        self.assertNotEqual(new['RoomId'], old['RoomId'])
        self.assertNotIn(old['RoomId'], self.rooms.rooms)
        self.assertNotIn(old['SearchId'], self.rooms.search_ids)
        with self.assertRaises(SessionError):
            self.registry.open(tcp)

    def test_unused_http_admission_expires_without_opening_socket(self):
        old, _, _ = self.create()
        self.now = 120
        self.service.expire_lobbies()
        self.assertEqual(self.rooms.memberships, {})
        self.assertNotIn(old['RoomId'], self.rooms.rooms)
        self.assertEqual(self.service.admissions, set())

    def test_reconnect_inside_grace_retains_same_room_and_membership(self):
        room, tcp, _ = self.create()
        first = self.connect(tcp)
        first.close()
        self.now = 9
        self.service.expire_lobbies()
        with self.assertRaises(RoomError):
            self.create()
        second = self.connect(tcp)
        self.assertEqual(second.session.admission.room_id, room['RoomId'])
        self.now = 10
        self.service.expire_lobbies()
        self.assertEqual(self.rooms.memberships['alice'], room['RoomId'])
        self.assertFalse(second.closed)

    def test_expired_host_hands_room_to_active_peer_and_notifies(self):
        room, tcp, _ = self.create()
        host = self.connect(tcp)
        _, other_tcp, _ = self.service.join(room['RoomId'], player('bob'), 'v')
        peer = self.connect(other_tcp)
        host.notifications()
        host.close()
        self.now = 9
        self.registry.get(peer.session.session_id)
        self.now = 10
        self.service.expire_lobbies()
        current = self.rooms.rooms[room['RoomId']]
        self.assertEqual([entry['UserId'] for entry in current['Players']], ['bob'])
        self.assertTrue(current['Players'][0]['IsHost'])
        self.assertFalse(peer.closed)
        frames = FrameDecoder().feed(peer.notifications()[0])
        service, body = read_user_message(frames[0][1])
        command, _ = read_command_message(body)
        self.assertEqual((service, command), (1000, 4))

    def test_active_inbound_session_outlives_original_http_admission(self):
        room, tcp, _ = self.create()
        connection = self.connect(tcp)
        for instant in range(9, 136, 9):
            self.now = instant
            self.registry.get(connection.session.session_id)
            self.service.expire_lobbies()
        self.assertEqual(self.rooms.memberships['alice'], room['RoomId'])
        self.assertFalse(connection.closed)

    def test_outbound_notifications_do_not_extend_reconnect_window(self):
        room, tcp, _ = self.create()
        connection = self.connect(tcp)
        self.now = 9
        connection.notifications()
        connection.close()
        self.now = 10
        self.service.expire_lobbies()
        self.assertNotIn(room['RoomId'], self.rooms.rooms)

    def test_old_connection_close_cannot_expire_replacement_session(self):
        room, tcp, _ = self.create()
        old = self.connect(tcp)
        replacement_tcp, _ = self.registry.issue('alice', room['RoomId'], 1)
        self.now = 10
        replacement = self.connect(replacement_tcp)
        old.close()
        self.service.expire_lobbies()
        self.assertEqual(self.rooms.memberships['alice'], room['RoomId'])
        self.assertFalse(replacement.closed)
        self.assertIn(replacement.session.session_id, self.service.connections)

    def test_prepared_battle_roster_and_completion_state_are_never_expired(self):
        room, tcp, _ = self.create()
        self.connect(tcp).close()
        current = self.rooms.rooms[room['RoomId']]
        current.update(PreparedBattle={'alice': {'EpisodeToken': 'prepared'}},
                       BattleRoster={'alice': 'character'},
                       Completions={'alice': ('durable-result', {'reward': 'retained'})})
        before = copy.deepcopy(current)
        self.now = 1000
        self.service.expire_lobbies()
        self.assertEqual(current, before)
        self.assertEqual(self.rooms.memberships['alice'], room['RoomId'])
        with self.assertRaises(RoomError):
            self.create()

    def test_udp_only_credential_does_not_keep_single_use_admission_alive(self):
        registry = SessionRegistry(clock=lambda: self.now, session_timeout=10)
        tcp, _ = registry.issue('alice', 'room', 1)
        session = registry.open(tcp)
        self.now = 10
        self.assertNotIn(('alice', 'room'), registry.active_admissions())
        with self.assertRaises(SessionError):
            registry.get(session.session_id)

    def test_expired_membership_is_released_before_joining_another_room(self):
        old, tcp, _ = self.create()
        self.connect(tcp).close()
        other, other_tcp, _ = self.create('bob')
        peer = self.connect(other_tcp)
        self.now = 9
        self.registry.get(peer.session.session_id)
        self.now = 10
        joined, _, _ = self.service.join(other['RoomId'], player('alice'), 'v')
        self.assertEqual(joined['RoomId'], other['RoomId'])
        self.assertNotIn(old['RoomId'], self.rooms.rooms)


class RuntimeLobbyExpiryTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_sweeps_unused_admissions_and_cancels_cleanup_on_stop(self):
        runtime = Runtime(4)
        now = [0]
        runtime.registry.clock = lambda: now[0]
        room, _, _ = runtime.service.create(player(), 'ep', 'v', False, 1, 1, (60, 3, 20))
        now[0] = 120
        swept = asyncio.Event()
        original = runtime.service.expire_lobbies

        def expire():
            original()
            swept.set()

        runtime.service.expire_lobbies = expire
        runtime.listener.start = AsyncMock(return_value=['socket'])
        runtime.listener.stop = AsyncMock()
        await runtime.start('localhost', 1234, None)
        await swept.wait()
        self.assertNotIn(room['RoomId'], runtime.rooms.rooms)
        task = runtime.cleanup_task
        await runtime.stop()
        self.assertTrue(task.cancelled())
        self.assertTrue(runtime.control.closed)
        self.assertEqual(runtime.service.admissions, set())


if __name__ == '__main__':
    unittest.main()
