import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from accounts import AccountStore
from pve_results import DurableCompletionProvider, JOURNAL
from pve_detached import archive, load, MAX_CONTEXT_BYTES
from prizm_room_service import RoomService
from prizm_rooms import Rooms, RoomError
from prizm_sessions import SessionRegistry
from pve_completion import native_result_hash
from test_prizm_lobby import player


class DetachedBattleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'accounts.sqlite3'
        store = AccountStore(self.path)
        for account in ('alice', 'bob'):
            store.connection.execute('INSERT INTO accounts VALUES(?,?,?)', (account, account, 0))
            store.write(account, 'UserParameter.json', {'Gold': 10})
        store.connection.commit()
        store.close()
        self.settlements = []
        def settle(saves, room, request, retire):
            self.settlements.append((room['PreparedBattle']['alice']['BattleId'], retire))
            return {}
        self.provider = DurableCompletionProvider(self.path, settle,
                                                  lambda saves, artifact, retire: {'Result': {}})

    def context(self, account, token):
        return {'PreparedBattle': {account: {'EpisodeToken': token, 'BattleId': token}},
                'BackHomeUsers': {account}, 'GameOver': ('alice', 1),
                'ExampleNativeMap': {1: (b'bytes', None, [1, 2])}}

    def test_repeated_crashes_spill_without_lockout_and_late_retire_is_durable(self):
        rooms = Rooms(1)
        service = RoomService(rooms, SessionRegistry(), completion_provider=self.provider)
        for index in range(20):
            room = service.create(player(), 'ep', 'v', False, 1, 1, (60, 3, 20))[0]
            rooms.rooms[room['RoomId']].update(self.context('alice', 'token' + str(index)))
            # An unresolved crash has no outcome; fresh admission is not retirement.
            rooms.rooms[room['RoomId']].pop('GameOver')
            service.release_abandoned_member('alice', fresh_admission=True)
            self.assertNotIn('alice', rooms.memberships)
            self.assertLessEqual(len(service.abandoned_battles['alice']), 8)
        self.assertEqual(self.settlements, [])
        store = AccountStore(self.path)
        self.assertFalse(store.exists('alice', JOURNAL))
        self.assertEqual(store.read('alice', 'UserParameter.json'), {'Gold': 10})
        self.assertEqual(store.read('bob', 'UserParameter.json'), {'Gold': 10})
        store.close()
        restarted = RoomService(Rooms(1), SessionRegistry(), completion_provider=self.provider)
        request = {'EpisodeToken': 'token0', 'Playlog': ''}
        for _ in range(2):
            self.assertEqual(restarted.complete_http('alice', request, True), {'Result': {}})
        self.assertEqual(self.settlements, [('token0', True)])
        with self.assertRaises(RoomError):
            restarted.complete_http('bob', request, True)
        self.assertIsNone(load(self.path, 'bob', 'token0'))

    def test_global_overflow_preserves_other_accounts_unresolved_context(self):
        rooms = Rooms(1)
        service = RoomService(rooms, SessionRegistry(), completion_provider=self.provider)
        service.abandoned_battles['bob'] = [self.context('bob', 'bob' + str(i)) for i in range(128)]
        old = service.abandoned_battles['bob'][0]
        room = service.create(player(), 'ep', 'v', False, 1, 1, (60, 3, 20))[0]
        rooms.rooms[room['RoomId']].update(self.context('alice', 'new'))
        service.release_abandoned_member('alice', fresh_admission=True)
        self.assertNotIn('alice', rooms.memberships)
        self.assertEqual(sum(map(len, service.abandoned_battles.values())), 128)
        self.assertEqual(load(self.path, 'bob', 'bob0'), old)
        self.assertEqual(self.settlements, [])

    def test_archive_failure_preserves_membership_contexts_and_saves(self):
        rooms = Rooms(1)
        service = RoomService(rooms, SessionRegistry(), completion_provider=self.provider)
        service.abandoned_battles['alice'] = [self.context('alice', str(i)) for i in range(8)]
        service.abandoned_battles['alice'][0]['TooLarge'] = 'x' * MAX_CONTEXT_BYTES
        room = service.create(player(), 'ep', 'v', False, 1, 1, (60, 3, 20))[0]
        rooms.rooms[room['RoomId']].update(self.context('alice', 'current'))
        with self.assertRaises(ValueError):
            service.release_abandoned_member('alice', fresh_admission=True)
        self.assertEqual(rooms.memberships['alice'], room['RoomId'])
        self.assertEqual(len(service.abandoned_battles['alice']), 8)
        self.assertIsNone(load(self.path, 'alice', '0'))
        self.assertEqual(self.settlements, [])

    def test_archive_roundtrip_conflict_and_missing_database(self):
        room = self.context('alice', 'token')
        archive(self.path, 'alice', room)
        archive(self.path, 'alice', room)
        self.assertEqual(load(self.path, 'alice', 'token'), room)
        with self.assertRaises(ValueError):
            archive(self.path, 'alice', room | {'GameOver': ('alice', 2)})
        self.assertEqual(load(self.path, 'alice', 'token'), room)
        self.path.unlink()
        with self.assertRaises(ValueError):
            self.provider.archive_detached('alice', room)
        self.assertFalse(self.path.exists())

    def test_archived_victory_requires_original_outcome_hash_and_replays_once(self):
        room = self.context('alice', 'victory')
        archive(self.path, 'alice', room)
        self.provider.render = lambda saves, artifact, retire: dict(
            Result={}, RankingScore=None, Rewards=[], SpecialDrops=[], RewardResult={})
        service = RoomService(Rooms(1), SessionRegistry(), completion_provider=self.provider)
        request = dict(EpisodeToken='victory', Playlog='',
                       ResultHash=native_result_hash('victory', True))
        with self.assertRaises(RoomError):
            service.complete_http('alice', request | {'ResultHash': native_result_hash('victory', False)})
        first = service.complete_http('alice', request)
        self.assertEqual(service.complete_http('alice', request), first)
        self.assertEqual(self.settlements, [('victory', False)])
        with self.assertRaises(ValueError):
            service.complete_http('alice', dict(EpisodeToken='victory', Playlog=''), True)
        self.assertEqual(self.settlements, [('victory', False)])


if __name__ == '__main__':
    unittest.main()
