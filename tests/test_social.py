from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
import unittest

import test_accounts as account_tests
from accounts import AccountStore, ACTIVITY_SCHEMA, INITIAL_SCHEMA, SCHEMA_VERSION
import server


class SocialTests(unittest.TestCase):
    setUp = account_tests.AccountTests.setUp
    post = account_tests.AccountTests.post
    unpack = account_tests.AccountTests.unpack
    register = account_tests.AccountTests.register
    saved = account_tests.AccountTests.saved

    def setUp(self):
        account_tests.AccountTests.setUp(self)
        self.alice, self.at = self.register('Alice')
        self.bob, self.bt = self.register('Bob')
        self.celia, self.ct = self.register('Celia')

    def change(self, action, token, *targets):
        return self.post('/api/friend/' + action, {'targetUserIds': list(targets)}, token=token)

    def listing(self, token):
        return self.unpack(self.post('/api/friend/list', token=token))

    def test_follow_is_directed_idempotent_and_survives_new_connections(self):
        response = self.unpack(self.change('follow', self.at, self.bob['id'], self.bob['id']))
        self.assertEqual(response['UserParameter']['FollowCount'], 1)
        self.assertTrue(response['Results'][0]['IsFollow'])
        self.assertFalse(response['Results'][0]['IsFollower'])
        self.assertEqual(len(response['Results']), 1)
        self.unpack(self.change('follow', self.at, self.bob['id']))
        self.assertEqual([v['UserId'] for v in self.listing(self.at)['FollowUsers']], [self.bob['id']])
        follower = self.listing(self.bt)['FollowerUsers'][0]
        self.assertEqual(follower['UserId'], self.alice['id'])
        self.assertTrue(follower['IsFollower'])
        with server.app.test_request_context('/api/user/top'):
            server.g.account_id = self.bob['id']
            server.g.account_store = AccountStore(self.db)
            self.assertEqual(server.load_json('./data/user/UserParameter.json')['FollowerCount'], 1)
        self.unpack(self.change('follow-release', self.at, self.bob['id']))
        self.unpack(self.change('follow-release', self.at, self.bob['id']))
        self.assertEqual(self.listing(self.bt)['FollowerUsers'], [])

    def test_remove_follower_does_not_remove_own_follow(self):
        self.unpack(self.change('follow', self.at, self.bob['id']))
        self.unpack(self.change('follow', self.bt, self.alice['id']))
        result = self.unpack(self.change('follower-release', self.bt, self.alice['id']))
        self.assertFalse(result['Results'][0]['IsFollower'])
        self.assertTrue(result['Results'][0]['IsFollow'])
        self.assertEqual(result['UserParameter']['FollowerCount'], 0)
        self.assertEqual(result['UserParameter']['FollowCount'], 1)

    def test_block_removes_both_follows_and_only_owner_can_unblock(self):
        self.unpack(self.change('follow', self.at, self.bob['id']))
        self.unpack(self.change('follow', self.bt, self.alice['id']))
        result = self.unpack(self.change('block', self.at, self.bob['id']))
        self.assertEqual(result['UserParameter']['BlockCount'], 1)
        self.assertEqual(result['UserParameter']['FollowCount'], 0)
        self.assertEqual(result['UserParameter']['FollowerCount'], 0)
        self.assertTrue(result['Results'][0]['IsBlock'])
        self.unpack(self.change('block', self.at, self.bob['id']))
        self.assertEqual(len(self.listing(self.at)['BlockUsers']), 1)
        self.assertEqual(self.listing(self.bt)['BlockUsers'], [])
        self.unpack(self.change('block-release', self.bt, self.alice['id']))
        for token, target in ((self.at, self.bob['id']), (self.bt, self.alice['id'])):
            self.assertEqual(self.change('follow', token, target).status_code, 400)
        self.unpack(self.change('block-release', self.at, self.bob['id']))
        self.assertEqual(self.listing(self.at)['FollowUsers'], [])
        self.unpack(self.change('follow', self.bt, self.alice['id']))
        self.assertEqual(len(self.listing(self.at)['FollowerUsers']), 1)

    def test_failed_batch_rolls_back_and_authentication_is_required(self):
        self.unpack(self.change('block', self.bt, self.alice['id']))
        self.assertEqual(self.change('follow', self.at, self.celia['id'], self.bob['id']).status_code, 400)
        self.assertEqual(self.listing(self.ct)['FollowerUsers'], [])
        self.assertEqual(self.change('block', self.at, self.celia['id'], self.alice['id']).status_code, 400)
        self.assertEqual(self.listing(self.at)['BlockUsers'], [])
        for action in ('follow', 'follow-release', 'follower-release', 'block', 'block-release'):
            self.assertEqual(self.client.get('/api/friend/' + action,
                headers={'Authorization': self.at}).status_code, 405)
            self.assertEqual(self.change(action, None, self.bob['id']).status_code, 401)
            self.assertEqual(self.change(action, self.at, 'missing').status_code, 400)
            self.assertEqual(self.change(action, self.at, self.alice['id']).status_code, 400)
        for targets in (None, 'bad', [None], [self.bob['id']] * 33):
            self.assertEqual(self.post('/api/friend/follow', {'targetUserIds': targets}, token=self.at).status_code, 400)

    def test_profile_search_flags_and_derived_counts_ignore_stale_save_values(self):
        store = AccountStore(self.db)
        try:
            raw = store.read(self.alice['id'], 'UserParameter.json')
            raw.update(FollowCount=999, FollowerCount=999, BlockCount=999)
            store.write(self.alice['id'], 'UserParameter.json', raw)
            store.connection.commit()
        finally:
            store.close()
        self.unpack(self.change('follow', self.at, self.bob['id']))
        found = self.unpack(self.post('/api/friend/search', {'searchId': self.bob['playerCode']}, token=self.at))
        self.assertEqual(found['User']['UserId'], self.bob['id'])
        self.assertTrue(found['User']['IsFollow'])
        views = self.unpack(self.post('/api/user/other-user-info', {'userIdInfo': [self.bob['id']]}, token=self.at))
        self.assertEqual(views['UserViews'], found['Users'])
        result = self.unpack(self.post('/api/user/change-view-param', {'word': 'Hi'}, token=self.at))
        self.assertEqual([result['UserParameter'][k] for k in ('FollowCount','FollowerCount','BlockCount')], [1,0,0])
        missing = self.unpack(self.post('/api/friend/search', {'searchId': 'missing'}, token=self.at))
        self.assertEqual(missing, {'User': None, 'Users': []})

    def test_concurrent_follows_remain_unique(self):
        def follow(_):
            return self.post('/api/friend/follow', {'targetUserIds': [self.bob['id']]},
                             token=self.at, client=server.app.test_client()).status_code
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(list(pool.map(follow, range(6))), [200] * 6)
        self.assertEqual(len(self.listing(self.bt)['FollowerUsers']), 1)


class SocialMigrationTests(unittest.TestCase):
    setUp = account_tests.AccountTests.setUp

    def test_version_two_migration_preserves_history_and_saves(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(INITIAL_SCHEMA + ACTIVITY_SCHEMA)
            db.execute("INSERT INTO accounts VALUES ('existing', 'code', 123)")
            db.execute("INSERT INTO saves VALUES ('existing', 'custom.json', '{\"x\":42}')")
            db.execute("INSERT INTO account_activity VALUES ('existing', 200)")
            db.execute("INSERT INTO login_history (account_id,logged_in_at,last_action_at,source) VALUES ('existing',123,200,'login')")
            db.execute('PRAGMA user_version=2')
            db.commit()
        store = AccountStore(self.db)
        try:
            self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(store.read('existing', 'custom.json'), {'x': 42})
            self.assertEqual(store.presence('existing', 201, 300), (True, 123))
            self.assertEqual(store.relationship_lists('existing'), {'FollowUsers': [], 'FollowerUsers': [], 'BlockUsers': []})
        finally:
            store.close()
