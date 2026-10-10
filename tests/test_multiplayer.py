from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

import test_accounts as account_tests
from accounts import AccountStore, INITIAL_SCHEMA, ACTIVITY_SCHEMA, SOCIAL_SCHEMA, SCHEMA_VERSION
from multiplayer import SocialStore
import server


class MultiplayerTests(unittest.TestCase):
    post = account_tests.AccountTests.post
    unpack = account_tests.AccountTests.unpack
    register = account_tests.AccountTests.register
    saved = account_tests.AccountTests.saved

    def setUp(self):
        account_tests.AccountTests.setUp(self)
        self.alice,self.at = self.register("Alice")
        self.bob,self.bt = self.register("Bob")
        self.celia,self.ct = self.register("Celia")

    def call(self,path,data=None,token=None):
        return self.unpack(self.post("/api/" + path,data,token=token or self.at))

    def send(self,body="Hello",kind=1,token=None,target=None):
        return self.call("message/post",{"targetUserId": target or self.bob["id"],
                         "type": kind,"message": body},token)

    def create(self,recruitment=2,token=None):
        return self.call("guild/create",{"name": "Friends", "recruitment": recruitment},token)["Guild"]

    def join(self,guild,token=None):
        return self.call("guild/join-apply",{"guildId": guild["GuildId"],"isCancel": False},token or self.bt)

    def message(self,guild,body="Hi",token=None):
        return self.call("guild/post-message",{"guildId": guild["GuildId"],"message": body,
                         "cdata": "","lastDate": ""},token)

    def view(self,target,token=None):
        return self.call("user/other-user-info",{"userIdInfo": [target]},token)["UserViews"][0]

    def test_configured_event_refresh_is_authenticated_and_account_scoped(self):
        from pve_publication import EventPublication
        class Catalog:
            def published_event_ids(self): return ('raid',)
        publication = EventPublication(Catalog(),[{'EventId':'raid'}],
            lambda account,event:{'EventId':event,'EpisodeUsers':[{'owner':account}]})
        with patch.dict(server.app.config,{'PVE_PUBLICATION':publication}):
            self.assertEqual(self.call('event/list'), {'Events':[{'EventId':'raid'}]})
            for token,account in ((self.at,self.alice['id']),(self.bt,self.bob['id'])):
                value = self.call('pve/list',{'eventId':'raid'},token)
                self.assertEqual(value['PveEvent']['EpisodeUsers'][0]['owner'],account)
                response = self.client.get('/api/pve/list?eventId=raid',
                    headers={'Authorization':token})
                self.assertEqual(self.unpack(response), value)
            self.assertEqual(self.client.get('/api/pve/list?eventId=raid&eventId=other',
                headers={'Authorization':self.at}).status_code,400)
            self.assertEqual(self.post('/api/pve/list',{'eventId':'unknown'},token=self.at).status_code,400)
            self.assertEqual(self.post('/api/pve/list',{'eventId':'raid','userId':self.bob['id']},token=self.at).status_code,400)
            self.assertEqual(self.client.post('/api/pve/list',data=b'\x80').status_code,401)
            self.assertEqual(self.client.get('/api/event/list').status_code,401)

    def test_configured_reward_list_is_scoped_and_has_explicit_native_collections(self):
        from pve_publication import EventPublication
        class Catalog:
            def published_event_ids(self): return ('raid',)
        rows = {'Mission':[], 'MissionMaster':[], 'GuildMission':[], 'GuildMissionMaster':[]}
        calls = []
        def rewards(account, event):
            calls.append((account,event))
            return rows
        publication = EventPublication(Catalog(),[{'EventId':'raid'}],
            lambda account,event:{'EventId':event},reward_list_provider=rewards)
        with patch.dict(server.app.config, {'PVE_PUBLICATION':publication}):
            for token, account in ((self.at,self.alice['id']),(self.bt,self.bob['id'])):
                response = self.client.get('/api/pve/reward-list?eventId=raid',
                    headers={'Authorization':token})
                self.assertEqual(self.unpack(response), rows)
                self.assertEqual(calls[-1], (account,'raid'))
            response = publication.reward_list(self.alice['id'],'raid')
            response['Mission'].append({'changed':True})
            self.assertEqual(rows['Mission'], [])
            count = len(calls)
            self.assertEqual(self.client.get('/api/pve/reward-list?eventId=unknown',
                headers={'Authorization':self.at}).status_code,400)
            self.assertEqual(len(calls), count)
            self.assertEqual(self.client.get('/api/pve/reward-list?eventId=raid').status_code,401)
            publication.reward_list_provider = None
            self.assertEqual(self.client.get('/api/pve/reward-list?eventId=raid',
                headers={'Authorization':self.at}).status_code,503)
            publication.reward_list_provider = lambda *args:{'Mission':[]}
            self.assertEqual(self.client.get('/api/pve/reward-list?eventId=raid',
                headers={'Authorization':self.at}).status_code,400)

    def test_configured_raid_home_tile_and_refresh_agree_for_each_account(self):
        from copy import deepcopy
        from pve_publication import EventPublication
        class Catalog:
            visible = ('raid',)
            def published_event_ids(self): return self.visible
        catalog = Catalog()
        publication = EventPublication(catalog,[{'EventId':'raid','Type':1}],
            lambda account,event:dict(EventId=event,EpisodeUsers=[{'owner':account}]))
        original_load = server.load_json
        source = dict(orderdIds=[{'MasterDataId':'story','Type':1}],events=[],pveEvents=[])
        def load(path):
            if path == './offline_responses/api/user/top.json': return deepcopy(source)
            if path.startswith('./data/masterdata/'): return []
            return original_load(path)
        with patch.dict(server.app.config,{'PVE_PUBLICATION':publication}), \
                patch('server.load_json',side_effect=load), \
                patch('server.top_add_episodes',return_value=[]), \
                patch('server.top_add_equipment',return_value=[]), \
                patch('server.top_add_characters',return_value=[]), \
                patch('server.add_all_emblems'):
            for token,account in ((self.at,self.alice['id']),(self.bt,self.bob['id'])):
                top = self.call('user/top',token=token)
                self.assertEqual(top['events'],self.call('event/list',token=token)['Events'])
                self.assertEqual(top['pveEvents'][0],self.call('pve/list',{'eventId':'raid'},token)['PveEvent'])
                self.assertEqual(top['pveEvents'][0]['EpisodeUsers'][0]['owner'],account)
                self.assertEqual(top['orderdIds'].count({'MasterDataId':'raid','Type':3}),1)
                self.assertIn({'MasterDataId':'story','Type':1},top['orderdIds'])
            catalog.visible = ()
            hidden = self.call('user/top')
            self.assertEqual(hidden['events'],[])
            self.assertEqual(hidden['pveEvents'],[])
            self.assertNotIn({'MasterDataId':'raid','Type':3},hidden['orderdIds'])
            self.assertEqual(self.call('event/list'),{'Events':[]})
            self.assertEqual(self.post('/api/pve/list',{'eventId':'raid'},token=self.at).status_code,400)

    def test_configured_room_discovery_receives_authenticated_identity(self):
        from pve_http import PveHttp
        from concurrent.futures import Future
        from unittest.mock import Mock
        future = Future()
        future.set_result([{'RoomId':'room'}])
        control = Mock()
        control.submit.return_value = future
        with patch.dict(server.app.config,{'PVE_HTTP':PveHttp(control)}):
            result = self.call('pve/room-list',{'eventId':'event','difficulty':2,'pveVersion':'v'})
            self.assertEqual(result,{'Rooms':[{'RoomId':'room'}]})
            control.submit.assert_called_once_with('discover_event',self.alice['id'],'event',2,'v')
            control.reset_mock()
            response = self.client.get('/api/pve/room-list?eventId=event&difficulty=2&pveVersion=v',
                headers={'Authorization':self.at})
            self.assertEqual(self.unpack(response), result)
            control.submit.assert_called_once_with('discover_event',self.alice['id'],'event',2,'v')
            control.reset_mock()
            for difficulty in ('-1','true','2.0','2147483648'):
                self.assertEqual(self.client.get('/api/pve/room-list',query_string=dict(
                    eventId='event',difficulty=difficulty,pveVersion='v'),
                    headers={'Authorization':self.at}).status_code,400)
            control.submit.assert_not_called()
            info = Future()
            info.set_result({'RoomId':'room'})
            control.submit.return_value = info
            self.assertEqual(self.call('pve/room-info',{'eventId':'event','roomId':'room','pveVersion':'v'}),
                             {'Room':{'RoomId':'room'}})
            control.submit.assert_called_once_with('info_event',self.alice['id'],'event','room','v')
            control.reset_mock()
            admission = Future()
            admission.set_result({'Prizm':{'RoomId':'created'}})
            control.submit.return_value = admission
            self.assertEqual(self.call('pve/create',{'episodeId':'ep','publicLevel':1,'pveVersion':'v'}),
                             {'Prizm':{'RoomId':'created'}})
            control.submit.assert_called_once_with('create_http',self.alice['id'],'ep','v',1)
            self.assertEqual(self.client.get('/api/pve/create',headers={'Authorization':self.at}).status_code,405)
            control.reset_mock()
            self.assertEqual(self.call('pve/join',{'roomId':'room','joinRoute':3,'pveVersion':'v'}),
                             {'Prizm':{'RoomId':'created'}})
            control.submit.assert_called_once_with('join_http',self.alice['id'],'room','v',3)
            control.reset_mock()
            matching = Future()
            matching.set_result({'Rooms':[],'Prizm':None,'RetryRequest':True,
                                 'RetryCount':3,'RetryInterval':1000})
            control.submit.return_value = matching
            result = self.call('pve/matching',{'eventId':'event','difficulty':2,
                                             'pveVersion':'v','maxPower':'999999'})
            self.assertTrue(result['RetryRequest'])
            control.submit.assert_called_once_with('matching_http',self.alice['id'],'event',2,'v')
            control.reset_mock()
            start = Future()
            start.set_result({'EpisodeToken':'member-token','BattleId':'battle'})
            control.submit.return_value = start
            result = self.call('pve/start',{'episodeId':'ep','characterId':'pl001',
                                          'memberIds':[self.alice['id'],None,None,None],
                                          'memberCharacterIds':['pl001']})
            self.assertEqual(result['EpisodeToken'],'member-token')
            control.submit.assert_called_once_with('start_http',self.alice['id'],'ep','pl001',
                                                   [self.alice['id']],['pl001'])
            control.reset_mock()
            for action in ('join','matching','start'):
                self.assertEqual(self.client.get('/api/pve/'+action,headers={'Authorization':self.at}).status_code,405)
                self.assertEqual(self.post('/api/pve/'+action,{},token=self.at).status_code,400)
                self.assertEqual(self.post('/api/pve/'+action,{}).status_code,401)
            self.assertEqual(self.post('/api/pve/room-list',{'eventId':'event','difficulty':True,'pveVersion':'v'},token=self.at).status_code,400)
            self.assertEqual(self.client.post('/api/pve/room-list',data=b'').status_code,401)
            control.submit.assert_not_called()

    def test_configured_http_completion_uses_authenticated_account_and_post(self):
        from pve_http import PveHttp
        from concurrent.futures import Future
        from unittest.mock import Mock
        control = Mock()
        future = Future()
        future.set_result({'Result':{}})
        control.submit.return_value = future
        with patch.dict(server.app.config,{'PVE_HTTP':PveHttp(control)}):
            for action,retire in (('end',False),('retire',True)):
                data = dict(episodeToken='token',playlog='opaque')
                expected = dict(EpisodeToken='token',Playlog='opaque')
                if not retire:
                    data['resultHash'] = 'hash'
                    expected['ResultHash'] = 'hash'
                control.reset_mock()
                self.assertEqual(self.call('pve/'+action,data,self.bt),{'Result':{}})
                control.submit.assert_called_once_with('complete_http',self.bob['id'],expected,retire)
                self.assertEqual(self.post('/api/pve/'+action,data | {'userId':self.alice['id']},token=self.bt).status_code,400)
                self.assertEqual(self.client.get('/api/pve/'+action,headers={'Authorization':self.bt}).status_code,405)

    def test_completion_writer_can_commit_while_http_waits_and_activity_survives(self):
        import json
        from pve_http import PveHttp
        from unittest.mock import Mock
        before = self.saved(self.alice,'UserParameter.json')
        with ThreadPoolExecutor(max_workers=1) as executor:
            def write_result(account):
                with closing(sqlite3.connect(self.db,timeout=0.2)) as database:
                    database.execute('BEGIN IMMEDIATE')
                    row = database.execute('SELECT value FROM saves WHERE account_id=? AND name=?',
                        (account,'UserParameter.json')).fetchone()
                    value = json.loads(row[0])
                    value['completion_test'] = value.get('completion_test',0)+1
                    database.execute('UPDATE saves SET value=? WHERE account_id=? AND name=?',
                        (json.dumps(value),account,'UserParameter.json'))
                    database.commit()
                return {'Result':{}}
            control = Mock()
            control.submit.side_effect = lambda operation,account,*args:executor.submit(write_result,account)
            with patch.dict(server.app.config,{'PVE_HTTP':PveHttp(control)}):
                for action in ('end','retire'):
                    data = dict(episodeToken='token',playlog='opaque')
                    if action == 'end': data['resultHash'] = 'hash'
                    self.assertEqual(self.call('pve/'+action,data,self.bt),{'Result':{}})
        self.assertEqual(self.saved(self.bob,'UserParameter.json')['completion_test'],2)
        self.assertEqual(self.saved(self.alice,'UserParameter.json'),before)
        with closing(sqlite3.connect(self.db)) as database:
            self.assertIsNotNone(database.execute('SELECT last_action_at FROM account_activity WHERE account_id=?',
                (self.bob['id'],)).fetchone())

    def test_every_listener_bound_route_releases_authentication_write_lock(self):
        from unittest.mock import Mock
        def pending_completion_write(account):
            with closing(sqlite3.connect(self.db, timeout=0.2)) as database:
                database.execute('BEGIN IMMEDIATE')
                database.execute('UPDATE accounts SET id=id WHERE id=?', (account,))
                database.commit()
            return {'Result':{}}
        with ThreadPoolExecutor(max_workers=1) as listener:
            adapter = Mock()
            actions = ('room-list','room-info','create','join','matching','start',
                       'end','retire','heart-beat')
            for action in actions:
                # Represents a queued HTTP operation waiting behind a listener
                # completion that needs the same SQLite writer lock.
                getattr(adapter, action.replace('-', '_')).side_effect = (
                    lambda account, data: listener.submit(pending_completion_write, account).result(1))
            with patch.dict(server.app.config, {'PVE_HTTP':adapter}):
                for action in actions:
                    with self.subTest(action=action):
                        self.assertEqual(self.call('pve/'+action, {}, self.bt), {'Result':{}})
            for action in actions:
                getattr(adapter, action.replace('-', '_')).assert_called_once_with(self.bob['id'], {})

    def test_direct_messages_persist_unread_stamps_and_likes(self):
        initial = self.send()
        mid = initial["Messages"][0]["MessageId"]
        self.assertEqual(initial["Messages"][0]["UserId"],self.alice["id"])
        self.assertTrue(self.view(self.alice["id"],self.bt)["IsNewMessage"])
        self.assertFalse(self.view(self.bob["id"])["IsNewMessage"])
        top = self.call("message/top",token=self.bt)
        self.assertEqual(top["DestUsers"][0]["LastMessage"],"Hello")
        conversation = self.call("message/list",{"targetUserId": self.alice["playerCode"]},self.bt)
        self.assertEqual(conversation["User"]["Name"],"Bob")
        self.assertEqual(conversation["TargetUser"]["Name"],"Alice")
        self.assertEqual(conversation["Messages"],initial["Messages"])
        via_get = self.unpack(self.client.get("/api/message/list",
            query_string={"targetUserId": self.alice["id"]},headers={"Authorization": self.bt}))
        self.assertEqual(via_get,conversation)
        self.assertFalse(self.view(self.alice["id"],self.bt)["IsNewMessage"])
        for _ in range(2):
            liked = self.call("message/like",{"targetUserId": self.alice["id"],
                             "messageId": mid,"like": True},self.bt)
            self.assertEqual(liked["Message"]["LikeCount"],1)
            self.assertTrue(liked["Message"]["IsLike"])
        stamp = self.send("stamp_001",2,self.bt,self.alice["id"])
        self.assertEqual([row["Type"] for row in stamp["Messages"]],[1,2])
        self.assertTrue(self.view(self.bob["id"])["IsNewMessage"])
        self.call("message/remove-dest",{"destUserId": self.bob["id"]})
        self.assertEqual(self.call("message/top")["DestUsers"],[])
        self.assertEqual(len(self.call("message/list",{"targetUserId": self.bob["id"]})["Messages"]),2)

    def test_conversation_privacy_validation_and_two_way_blocking(self):
        mid = self.send()["Messages"][0]["MessageId"]
        self.assertEqual(self.call("message/list",{"targetUserId": self.bob["id"]},self.ct)["Messages"],[])
        self.assertEqual(self.post("/api/message/like",{"targetUserId": self.bob["id"],
                         "messageId": mid,"like": True},self.ct).status_code,400)
        for value in ("",None,"x"*141,[],"a\x00b"):
            self.assertEqual(self.post("/api/message/post",{"targetUserId": self.bob["id"],
                             "type": 1,"message": value},self.at).status_code,400)
        for kind in (0,3,True,"1"):
            self.assertEqual(self.post("/api/message/post",{"targetUserId": self.bob["id"],
                             "type": kind,"message": "Hi"},self.at).status_code,400)
        self.call("friend/block",{"targetUserIds": [self.alice["id"]]},self.bt)
        for token,target in ((self.at,self.bob["id"]),(self.bt,self.alice["id"])):
            self.assertEqual(self.call("message/top",token=token)["DestUsers"],[])
            self.assertEqual(self.post("/api/message/list",{"targetUserId": target},token).status_code,400)
            self.assertEqual(self.post("/api/message/post",{"targetUserId": target,"type": 1,"message": "No"},token).status_code,400)
            self.assertFalse(self.view(target,token)["IsNewMessage"])
        self.call("friend/block-release",{"targetUserIds": [self.alice["id"]]},self.bt)
        self.assertEqual(len(self.call("message/list",{"targetUserId": self.bob["id"]})["Messages"]),1)

    def test_guild_lifecycle_roles_and_profiles(self):
        self.assertIsNone(self.call("guild/top")["Guild"])
        guild = self.create()
        self.assertEqual(guild["Members"],[self.alice["id"]])
        self.assertEqual(self.call("guild/search",{"name": "friends","count": 10})["Guilds"][0]["GuildId"],guild["GuildId"])
        self.join(guild)
        self.join(guild,self.ct)
        self.assertEqual(self.view(self.bob["id"])["GuildName"],"Friends")
        self.assertEqual(self.post("/api/guild/update",{"name": "No"},self.bt).status_code,400)
        promoted = self.call("guild/promote",{"targetUserId": self.bob["id"],"isPromote": True})["Guild"]
        self.assertEqual(promoted["Officers"],[self.alice["id"],self.bob["id"]])
        self.call("guild/update",{"name": "New name"},self.bt)
        self.assertEqual(self.view(self.celia["id"])["GuildName"],"New name")
        self.assertEqual(self.post("/api/guild/devolution",{"targetUserId": self.celia["id"]},self.bt).status_code,400)
        transferred = self.call("guild/devolution",{"targetUserId": self.bob["id"]})["Guild"]
        self.assertEqual(transferred["Members"][0],self.bob["id"])
        self.assertEqual(transferred["Officers"][0],self.bob["id"])
        self.assertEqual(transferred["LeaderName"],"Bob")
        self.assertEqual(self.post("/api/guild/leave",{},self.bt).status_code,400)
        self.call("guild/leave")
        self.assertEqual(self.call("guild/top")["UserGuild"]["Status"],0)
        self.assertEqual(self.post("/api/guild/disband",{"guildId": guild["GuildId"]},self.ct).status_code,400)
        self.call("guild/disband",{"guildId": guild["GuildId"]},self.bt)
        self.assertIsNone(self.call("guild/top",token=self.ct)["Guild"])
        self.assertEqual(self.view(self.celia["id"])["GuildName"],"")

    def test_application_privacy_cancellation_and_approval(self):
        guild = self.create(1)
        self.assertEqual(self.join(guild)["UserGuild"]["Status"],2)
        self.assertEqual(self.call("guild/top",token=self.bt)["Applications"],[])
        self.assertEqual(self.call("guild/top")["Applications"][0]["UserId"],self.bob["id"])
        self.join(guild,self.ct)
        self.call("guild/join-apply",{"guildId": guild["GuildId"],"isCancel": True},self.ct)
        self.assertEqual(len(self.call("guild/top")["Applications"]),1)
        accepted = self.call("guild/join-approve",{"targetUserId": [self.bob["id"]],"isAccept": True})
        self.assertEqual(accepted["Applications"],[])
        self.assertEqual(accepted["Guild"]["MemberCount"],2)
        self.assertEqual(self.call("guild/top",token=self.bt)["UserGuild"]["Status"],1)
        self.assertEqual(self.post("/api/guild/create",{"name": "Second"},self.bt).status_code,400)

    def test_guild_block_and_failed_batch_roll_back(self):
        guild = self.create()
        self.join(guild)
        self.join(guild,self.ct)
        self.assertEqual(self.post("/api/guild/drop-member",{"targetUserId": [self.bob["id"],self.alice["id"]],"isBlock": True},self.at).status_code,400)
        self.assertEqual(self.call("guild/top")["Guild"]["MemberCount"],3)
        self.assertEqual(self.call("guild/block-list")["Users"],[])
        self.call("guild/drop-member",{"targetUserId": [self.bob["id"]],"isBlock": True})
        self.assertEqual(self.post("/api/guild/join-apply",{"guildId": guild["GuildId"]},self.bt).status_code,400)
        self.call("guild/block",{"targetUserId": self.bob["id"],"isBlock": False})
        self.join(guild)
        self.assertEqual(self.call("guild/top")["Guild"]["MemberCount"],3)

    def test_guild_messages_visibility_pagination_likes_and_moderation(self):
        guild = self.create()
        self.join(guild)
        posted = self.message(guild)
        mid = posted["Messages"][0]["GuildMessageId"]
        cursor = posted["Messages"][0]["PostedAt"]
        with closing(AccountStore(self.db)) as store:
            self.assertTrue(SocialStore(store,self.bob["id"]).guild_unread())
            self.assertFalse(SocialStore(store,self.alice["id"]).guild_unread())
        self.assertEqual(self.post("/api/guild/message",{"guildId": guild["GuildId"]},self.ct).status_code,400)
        self.message(guild,"Hello back",self.bt)
        newer = self.call("guild/message",{"guildId": guild["GuildId"],"startDate": cursor,"isNewer": True,"count": 5})
        self.assertEqual([row["Message"] for row in newer["Messages"]],["Hello back"])
        for _ in range(2):
            liked = self.call("guild/like-message",{"guildId": guild["GuildId"],"messageId": [mid],"isRemove": False},self.bt)
            self.assertEqual(liked["Messages"][0]["Like"],1)
        self.assertEqual(self.post("/api/guild/delete-message",{"guildId": guild["GuildId"],"messageId": [mid]},self.bt).status_code,400)
        self.call("friend/block",{"targetUserIds": [self.alice["id"]]},self.bt)
        hidden = self.call("guild/message",{"guildId": guild["GuildId"]},self.bt)
        self.assertEqual([row["Message"] for row in hidden["Messages"]],["Hello back"])
        self.call("guild/delete-message",{"guildId": guild["GuildId"],"messageId": [mid]})
        self.assertEqual(self.call("guild/top")["Guild"]["CommentCount"],1)

    def test_capacity_is_atomic_and_joining_two_guilds_is_rejected(self):
        guild = self.create()
        other = self.create(token=self.ct)
        def join(gid):
            return self.post("/api/guild/join-apply",{"guildId": gid},self.bt,
                             client=server.app.test_client()).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(join,[guild["GuildId"],other["GuildId"]]))
        self.assertEqual(sorted(statuses),[200,400])
        current = self.call("guild/top",token=self.bt)["Guild"]
        with closing(AccountStore(self.db)) as store:
            for index in range(22):
                account,_ = store.create("Member " + str(index),account_tests.seeds())
                SocialStore(store,account).add_member(current["GuildId"],account)
            store.connection.commit()
        late,token = self.register("Late member")
        self.assertEqual(self.post("/api/guild/join-apply",{"guildId": current["GuildId"]},token).status_code,400)
        self.assertEqual(self.call("guild/top",token=self.bt)["Guild"]["MemberCount"],24)

    def test_auth_methods_and_raid_unavailability(self):
        for path in ("message/post","message/like","guild/create","guild/update","guild/post-message","guild/disband"):
            self.assertEqual(self.post("/api/" + path).status_code,401)
            self.assertEqual(self.client.get("/api/" + path,headers={"Authorization": self.at}).status_code,405)
        for action in ("create","join","start","end","matching","heart-beat"):
            self.assertEqual(self.post("/api/pve/" + action,{},self.at).status_code,501)
        self.assertEqual(self.call("pve/room-list"),{"Rooms": []})
        self.assertEqual(self.call("pve/get-recently-matching"),{"Users": []})

    def test_invalid_guild_inputs_do_not_create_or_change_state(self):
        for data in ({"name": ""},{"name": "x"*33},{"name": "Good","minPower": 500},
                     {"name": "Good","recruitment": -1},{"name": "Good","mood": True}):
            self.assertEqual(self.post("/api/guild/create",data,self.at).status_code,400)
        self.assertIsNone(self.call("guild/top")["Guild"])
        guild = self.create()
        self.assertEqual(self.post("/api/guild/update",{"name": "Changed","minPower": 1},self.at).status_code,400)
        self.assertEqual(self.call("guild/top")["Guild"]["Name"],"Friends")
        for data in ({"guildId": guild["GuildId"],"count": 0},
                     {"guildId": guild["GuildId"],"startDate": "bad"}):
            self.assertEqual(self.post("/api/guild/message",data,self.at).status_code,400)
        self.assertEqual(self.post("/api/message/post",{"targetUserId": self.bob["id"],
                         "type": 1,"message": "One","Message": "Two"},self.at).status_code,400)

    def test_native_cursor_precision_and_optional_message_fields(self):
        from datetime import datetime
        guild = self.create()
        with patch("multiplayer.time.time",return_value=1800000000.123456):
            first = self.call("guild/post-message",{"message": "First","cdata": None})
            # Native request code uses yyyy-MM-dd HH:mm:ss.ffffzzz.
            parsed = datetime.fromisoformat(first["Messages"][0]["PostedAt"].replace("Z","+00:00"))
            cursor = parsed.strftime("%Y-%m-%d %H:%M:%S.") + f"{parsed.microsecond // 100:04d}" + "+00:00"
            self.call("guild/post-message",{"message": "Second"})
            self.call("guild/post-message",{"message": "Third"})
        newer = self.call("guild/message",{"guildId": guild["GuildId"],"startDate": cursor,"isNewer": True,"count": 1})
        self.assertEqual([r["Message"] for r in newer["Messages"]],["Second"])
        next_page = self.call("guild/message",{"guildId": guild["GuildId"],
                              "startDate": newer["Messages"][0]["PostedAt"],"isNewer": True})
        self.assertEqual([r["Message"] for r in next_page["Messages"]],["Third"])

    def test_top_badges_follow_reads_and_blocks(self):
        original_load = server.load_json

        def load(path):
            if path == "./offline_responses/api/user/top.json":
                return {"orderdIds": [],"badge": {"PresentCount": 7}}
            if path.startswith("./data/masterdata/"):
                return []
            return original_load(path)

        def badges(token):
            with patch("server.load_json",side_effect=load), \
                 patch("server.top_add_episodes",return_value=[]), \
                 patch("server.top_add_equipment",return_value=[]), \
                 patch("server.top_add_characters",return_value=[]), \
                 patch("server.add_all_emblems"):
                return self.call("user/top",token=token)["badge"]

        guild = self.create()
        self.join(guild)
        self.send()
        self.message(guild)
        result = badges(self.bt)
        self.assertTrue(result["IsNewMessage"])
        self.assertTrue(result["IsNewGuildMessage"])
        self.assertEqual(result["PresentCount"],7)
        self.call("message/list",{"targetUserId": self.alice["id"]},self.bt)
        self.call("guild/message",{"guildId": guild["GuildId"]},self.bt)
        self.assertFalse(badges(self.bt)["IsNewMessage"])
        self.assertFalse(badges(self.bt)["IsNewGuildMessage"])
        self.send("Again")
        self.message(guild,"Again")
        self.call("friend/block",{"targetUserIds": [self.alice["id"]]},self.bt)
        self.assertFalse(badges(self.bt)["IsNewMessage"])
        self.assertFalse(badges(self.bt)["IsNewGuildMessage"])

    def test_post_limit_is_shared_between_direct_and_guild_chat(self):
        guild = self.create()
        with patch("multiplayer.time.time",return_value=1800000000):
            for _ in range(29):
                self.send()
            self.message(guild)
            failed = self.post("/api/message/post",{"targetUserId": self.bob["id"],
                               "type": 1,"message": "Too many"},self.at)
            self.assertEqual(failed.status_code,400)
        with patch("multiplayer.time.time",return_value=1800000061):
            self.send("Allowed again")

    def test_search_cursor_matches_returned_last_access(self):
        with patch("multiplayer.time.time",return_value=1800000000.123456):
            first = self.create()
            second = self.create(token=self.bt)
            self.message(first)
        page = self.call("guild/search",{"count": 1})["Guilds"]
        self.assertEqual(page[0]["GuildId"],first["GuildId"])
        next_page = self.call("guild/search",{"count": 1,"startDate": page[0]["LastAccessAt"]})["Guilds"]
        self.assertEqual(next_page[0]["GuildId"],second["GuildId"])


class MultiplayerMigrationTests(unittest.TestCase):
    setUp = account_tests.AccountTests.setUp

    def test_v3_upgrade_keeps_accounts_relationships_and_unknown_save_fields(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(INITIAL_SCHEMA + ACTIVITY_SCHEMA + SOCIAL_SCHEMA)
            db.execute("INSERT INTO accounts VALUES ('a','code-a',123)")
            db.execute("INSERT INTO accounts VALUES ('b','code-b',124)")
            db.execute("INSERT INTO follows VALUES ('a','b')")
            db.execute("INSERT INTO saves VALUES ('a','custom.json','{\"unknown\":42}')")
            db.execute("PRAGMA user_version=3")
            db.commit()
        with closing(AccountStore(self.db)) as store:
            self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0],SCHEMA_VERSION)
            self.assertEqual(store.read('a','custom.json'),{"unknown":42})
            self.assertEqual(store.relationship_lists('a')["FollowUsers"],['b'])
            self.assertIsNone(SocialStore(store,'a').membership())

    def test_failed_social_migration_rolls_back_all_new_tables(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(INITIAL_SCHEMA + ACTIVITY_SCHEMA + SOCIAL_SCHEMA)
            db.execute("PRAGMA user_version=3")
            db.commit()
        with patch("multiplayer.MULTIPLAYER_SCHEMA","CREATE TABLE incomplete(id TEXT); invalid SQL;"):
            with self.assertRaises(sqlite3.OperationalError):
                AccountStore(self.db)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],3)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='incomplete'").fetchone())
