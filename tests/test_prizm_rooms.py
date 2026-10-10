import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from prizm_rooms import Rooms, RoomError, BattlePreparation
from prizm_sessions import SessionRegistry
from test_prizm_lobby import player


class RoomTests(unittest.TestCase):
    def test_prepared_start_roster_survives_other_member_departure(self):
        rooms, registry = Rooms(2), SessionRegistry()
        room_id = self.create(rooms)
        rooms.join(room_id, player('bob',1,False), 'v1')
        tcp, _ = registry.issue('alice',room_id,1)
        guest_tcp, _ = registry.issue('bob',room_id,2)
        host, guest = registry.open(tcp), registry.open(guest_tcp)
        rooms.ready(guest,'bob',1)
        responses = {account:dict(EpisodeToken='token-'+account,BattleId='battle',
            CharacterDetail={},EnemyDetail={},EpisodeDetail={},EpisodeDetailUser={},
            MasterGroup={},LimitTime=60,BgmId='bgm') for account in ('alice','bob')}
        rooms.prepare_battle(host,lambda room:responses)
        rooms.leave('bob',room_id)
        self.assertEqual(rooms.start_response('alice','episode','pl001',
            ['alice','bob'],['pl001','pl001']), responses['alice'])
        with self.assertRaises(RoomError):
            rooms.start_response('alice','episode','pl001',['alice'],['pl001'])
        with self.assertRaises(RoomError):
            rooms.start_response('bob','episode','pl001',['alice','bob'],['pl001','pl001'])
        with self.assertRaises(RoomError):
            rooms.battle_roster(guest,'episode','pl001',['alice','bob'],['pl001','pl001'])

    def test_unselected_lobby_member_cannot_ready_or_start(self):
        from prizm_lobby import player_payload,join_reply
        rooms,registry = Rooms(2),SessionRegistry()
        unselected = player() | dict(CharacterId='',CharacterLevel=0,CharacterPower=0,
            CharacterHp=0,CharacterAttack=0,CharacterDefense=0,Ready=0,
            VisualEquipments=[],CostumeSpells=[],WeaponSpells=[])
        with self.assertRaises(ValueError): player_payload(unselected)
        player_payload(unselected,allow_unselected=True)
        with self.assertRaises(ValueError):
            player_payload(unselected | {'CharacterHp':1},allow_unselected=True)
        room = rooms.create(unselected,'ep','v',False,1,1,(60,3,20))
        tcp,_ = registry.issue('alice',room['RoomId'],1)
        host = registry.open(tcp)
        join_reply(room['Players'],60,3,20)
        with self.assertRaises(RoomError): rooms.ready(host,'alice',1)
        with self.assertRaises(RoomError): rooms.start_candidate(host)
        rooms.change_character(host,player())
        self.assertEqual(rooms.start_candidate(host)['Players'][0]['CharacterId'],'pl001')

    def test_replacement_identity_must_match_selected_and_prepared_characters(self):
        rooms, registry = Rooms(3), SessionRegistry()
        room_id = self.create(rooms)
        tcp, _ = registry.issue('alice',room_id,1)
        host = registry.open(tcp)
        responses = {'alice':dict(EpisodeToken='token',BattleId='battle',
            CharacterDetail={},EnemyDetail={},EpisodeDetail={},EpisodeDetailUser={
                'playCharacters':[dict(characterId='replacement',level=1,exp=0,hp=100,sp=0)]},
            MasterGroup={},LimitTime=60,BgmId='bgm')}
        characters = {'alice':{1:'replacement',2:'replacement',3:None,4:1,5:0,
                              6:100,7:0,8:[],9:[],10:[]}}
        for identities in (None, {}, {'bob':('pl001','replacement')},
                           {'alice':('other','replacement')}, {'alice':('pl001','other')}):
            with self.assertRaises(RoomError):
                rooms.prepare_battle(host,lambda room:BattlePreparation(responses,characters,identities))
            self.assertNotIn('PreparedBattle', rooms.rooms[room_id])
        result = rooms.prepare_battle(host,lambda room:BattlePreparation(
            responses,characters,{'alice':('pl001','replacement')}))
        self.assertEqual(result['BattleCharacters']['alice'][1], 'replacement')
        self.assertEqual(result['Players'][0]['CharacterId'], 'pl001')

    def test_paired_preparation_freezes_both_outputs_atomically(self):
        rooms,registry = Rooms(3),SessionRegistry()
        room_id = self.create(rooms)
        tcp,_ = registry.issue('alice',room_id,1)
        host = registry.open(tcp)
        responses = {'alice':dict(EpisodeToken='token',BattleId='battle',
            CharacterDetail={},EnemyDetail={},EpisodeDetail={},EpisodeDetailUser={
                'playCharacters':[dict(characterId='pl001',level=1,exp=0,hp=100,sp=0)]},
            MasterGroup={},LimitTime=60,BgmId='bgm')}
        for invalid in (None, {}, {'alice':{}}):
            with self.assertRaises(RoomError):
                rooms.prepare_battle(host,lambda room:BattlePreparation(responses,invalid))
            self.assertNotIn('PreparedBattle',rooms.rooms[room_id])
        character = {1:'pl001',2:'pl001',3:None,4:1,5:0,6:100,7:0,8:[],9:[],10:[]}
        for change in ({6:99}, {4:2}, {1:'another'}, {5:1}, {7:1}):
            with self.assertRaises(RoomError):
                rooms.prepare_battle(host, lambda room:BattlePreparation(
                    responses,{'alice':character | change}))
            self.assertNotIn('PreparedBattle',rooms.rooms[room_id])
        result = rooms.prepare_battle(host,
            lambda room:BattlePreparation(responses,{'alice':character}))
        character[6] = 999
        responses['alice']['EpisodeToken'] = 'changed'
        self.assertEqual(result['BattleCharacters']['alice'][6],100)
        self.assertEqual(result['PreparedBattle']['alice']['EpisodeToken'],'token')

    def test_preparation_failure_and_success_freeze_authoritative_roster(self):
        rooms,registry = Rooms(3),SessionRegistry()
        room_id = self.create(rooms)
        rooms.join(room_id,player('bob',1,False),'v1')
        tcp,_ = registry.issue('alice',room_id,1)
        guest_tcp,_ = registry.issue('bob',room_id,2)
        host,guest = registry.open(tcp),registry.open(guest_tcp)
        rooms.ready(guest,'bob',1)
        with self.assertRaises(RoomError):
            rooms.start_response('alice','episode','pl001',['alice','bob'],['pl001','pl001'])
        with self.assertRaises(RoomError): rooms.prepare_battle(host,None)
        with self.assertRaises(RoomError): rooms.prepare_battle(host,lambda room:{})
        self.assertNotIn('PreparedBattle',rooms.rooms[room_id])
        prepared = {name:dict(EpisodeToken='token-'+name,BattleId='battle',
            CharacterDetail={},EnemyDetail={},EpisodeDetail={},EpisodeDetailUser={},
            MasterGroup={},LimitTime=60,BgmId='bgm') for name in ('alice','bob')}
        invalid = {name:dict(value,EpisodeToken='shared') for name,value in prepared.items()}
        with self.assertRaises(RoomError): rooms.prepare_battle(host,lambda room:invalid)
        for overrides in ({'CharacterDetail':[]},{'LimitTime':True},{'BgmId':None},
                          {'EpisodeDetail':{'bad':object()}}):
            invalid = {name:dict(value,**overrides) for name,value in prepared.items()}
            with self.assertRaises(RoomError): rooms.prepare_battle(host,lambda room:invalid)
            self.assertNotIn('PreparedBattle',rooms.rooms[room_id])
        with self.assertRaises(RoomError):
            rooms.prepare_battle(host,lambda room:prepared,lambda account,room:{})
        self.assertNotIn('PreparedBattle',rooms.rooms[room_id])
        self.assertNotIn('BattleCharacters',rooms.rooms[room_id])
        character = {1:'pl001',2:'master',3:'name',4:1,5:0,6:100,7:0,8:[],9:[],10:[]}
        def character_provider(account,context):
            self.assertEqual(context['PreparedBattle'][account]['EpisodeToken'],'token-'+account)
            return character
        result = rooms.prepare_battle(host,lambda room:prepared,character_provider)
        character[6] = 999
        self.assertEqual(result['BattleCharacters']['alice'][6],100)
        self.assertEqual(rooms.rooms[room_id]['BattleCharacters']['bob'][6],100)
        prepared['alice']['EpisodeToken'] = 'changed'
        result['PreparedBattle']['bob']['EpisodeToken'] = 'changed'
        self.assertEqual(rooms.rooms[room_id]['PreparedBattle']['alice']['EpisodeToken'],'token-alice')
        self.assertEqual(rooms.rooms[room_id]['PreparedBattle']['bob']['EpisodeToken'],'token-bob')
        self.assertEqual(rooms.start_response('alice','episode','pl001',
            ['alice','bob',None,None],['pl001','pl001'])['EpisodeToken'],'token-alice')
        with self.assertRaises(RoomError):
            rooms.start_response('alice','episode','pl001',['alice',None,'bob',None],['pl001','pl001'])
        for name in ('alice','bob'):
            response = rooms.start_response(name,'episode','pl001',['bob','alice'],['pl001','pl001'])
            self.assertEqual(response['EpisodeToken'],'token-'+name)
            response['EpisodeToken'] = 'changed'
            self.assertEqual(rooms.start_response(name,'episode','pl001',['alice','bob'],
                             ['pl001','pl001'])['EpisodeToken'],'token-'+name)
        for name,episode,character,members in [('outsider','episode','pl001',['alice','bob']),
                ('alice','forged','pl001',['alice','bob']),
                ('alice','episode','forged',['alice','bob']),
                ('alice','episode','pl001',['alice','outsider'])]:
            with self.assertRaises(RoomError):
                rooms.start_response(name,episode,character,members,['pl001','pl001'])
        with self.assertRaises(RoomError): rooms.prepare_battle(host,lambda room:prepared)
        with self.assertRaises(RoomError): rooms.join(room_id,player('celia'),'v1')
        with self.assertRaises(RoomError): rooms.ready(guest,'bob',0)
        self.assertEqual(rooms.discover('v1',lambda room:True),[])

    def test_pve_start_roster_rejects_forged_episode_members_and_characters(self):
        rooms,registry = Rooms(2),SessionRegistry()
        room_id = self.create(rooms)
        bob = player('bob',1,False)
        bob['CharacterId'] = 'pl002'
        rooms.join(room_id,bob,'v1')
        tcp,_ = registry.issue('bob',room_id,2)
        session = registry.open(tcp)
        for episode,character,members,characters in [
                ('other','pl002',['alice','bob'],['pl001','pl002']),
                ('episode','pl001',['alice','bob'],['pl001','pl002']),
                ('episode','pl002',['alice','celia'],['pl001','pl002']),
                ('episode','pl002',['alice','bob'],['pl002','pl001']),
                ('episode','pl002',['bob','bob'],['pl002','pl002']),
                ('episode','pl002',['bob'],['pl002']),
                ('episode','pl002',['alice','bob'],['pl001']),
                ('episode','pl002','bob',['pl002'])]:
            with self.subTest(members=members),self.assertRaises(RoomError):
                rooms.battle_roster(session,episode,character,members,characters)
        room = rooms.battle_roster(session,'episode','pl002',['bob','alice'],['pl002','pl001'])
        self.assertEqual([p['UserId'] for p in room['Players']],['alice','bob'])
        rooms.leave('alice',room_id)
        with self.assertRaises(RoomError):
            rooms.battle_roster(session,'episode','pl002',['bob','alice'],['pl002','pl001'])

    def test_battle_candidate_requires_host_and_wire_ready_guests(self):
        rooms,registry = Rooms(2),SessionRegistry()
        room_id = self.create(rooms)
        rooms.join(room_id,player('bob',1,False),'v1')
        host_tcp,_ = registry.issue('alice',room_id,1)
        guest_tcp,_ = registry.issue('bob',room_id,2)
        host,guest = registry.open(host_tcp),registry.open(guest_tcp)
        with self.assertRaises(RoomError): rooms.start_candidate(guest)
        for readiness in (0,2):
            rooms.ready(guest,'bob',readiness)
            with self.assertRaises(RoomError): rooms.start_candidate(host)
        rooms.ready(guest,'bob',1)
        candidate = rooms.start_candidate(host)
        self.assertEqual([p['UserId'] for p in candidate['Players']],['alice','bob'])
        candidate['Players'].clear()
        self.assertEqual(len(rooms.rooms[room_id]['Players']),2)
        self.assertEqual(rooms.rooms[room_id]['Status'],0)

    def test_readiness_scoped_to_authenticated_player(self):
        rooms = Rooms(capacity=2)
        room_id = self.create(rooms)
        rooms.join(room_id,player('bob',1,False),'v1')
        registry = SessionRegistry()
        tcp,_ = registry.issue('bob',room_id,2)
        session = registry.open(tcp)
        with self.assertRaises(RoomError):
            rooms.ready(session,'alice',1)
        result = rooms.ready(session,'bob',1)
        self.assertEqual([p['Ready'] for p in result['Players']],[0,1])
        rooms.leave('bob',room_id)
        with self.assertRaises(RoomError):
            rooms.ready(session,'bob',0)
    def create(self, rooms):
        return rooms.create(player(),'episode','v1',False,0,1,(60,3,20))['RoomId']

    def test_atomic_last_slot_host_handover_and_revocation(self):
        rooms = Rooms(capacity=2)
        room_id = self.create(rooms)
        def join(name):
            try:
                return rooms.join(room_id,player(name,1,False),'v1')
            except RoomError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(join,['bob','celia']))
        self.assertEqual(sum(value is not None for value in results),1)
        remaining = rooms.leave('alice',room_id)
        self.assertEqual(len(remaining['Players']),1)
        self.assertTrue(remaining['Players'][0]['IsHost'])
        registry = SessionRegistry()
        tcp,_ = registry.issue('alice',room_id,1)
        with self.assertRaises(RoomError):
            rooms.snapshot(registry.open(tcp),12,False)
        self.assertIsNone(rooms.leave(remaining['Players'][0]['UserId'],room_id))
        self.assertEqual(rooms.rooms,{})

    def test_snapshots_are_isolated_and_versions_checked(self):
        rooms = Rooms(capacity=3)
        room_id = self.create(rooms)
        with self.assertRaises(RoomError):
            rooms.join(room_id,player('bob',1,False),'wrong')
        returned = rooms.join(room_id,player('bob',1,False),'v1')
        returned['Players'][0]['Name'] = 'Tampered'
        self.assertEqual(rooms.rooms[room_id]['Players'][0]['Name'],'Alice')
        with self.assertRaises(RoomError):
            rooms.join(room_id,player('bob',1,False),'v1')
