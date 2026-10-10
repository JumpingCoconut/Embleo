import asyncio
import hashlib
import json
import os
import shutil
import ssl
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from prizm_listener import Listener
from prizm_sessions import SessionRegistry, SessionError
from prizm_protocol import hello_request, FrameDecoder, read_handshake_response, Opcode
from prizm_protocol import (fallback_request, user_message, rpc_request,
                            read_user_message, read_rpc_response,
                            command_message, read_command_message)
from prizm_runtime import Runtime
from test_prizm_lobby import player
from prizm_lobby import player_payload
from pve_http import PveHttp
from pve_preparation import PreparedEnemySpawns
from pve_completion import native_result_hash,native_playlog_hash
from accounts import AccountStore,token_hash
from pve_results import DurableCompletionProvider,NativeCompletionRenderer,JOURNAL
import msgpack


class Writer:
    def __init__(self):
        self.data = bytearray()
        self.closed = False
    def write(self, data):
        self.data.extend(data)
    async def drain(self):
        pass
    def close(self):
        self.closed = True
    async def wait_closed(self):
        pass


class ListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_verified_tls_lobby_exchange(self):
        await self._tls_battle_flow()

    async def test_real_verified_tls_installed_battle_and_save_preservation(self):
        root = os.environ.get('EMBLEO_TEST_RAID_DATA')
        if not root:
            self.skipTest('Set EMBLEO_TEST_RAID_DATA to installed masters and local save fixtures.')
        await self._tls_battle_flow(Path(root).resolve())

    async def _tls_battle_flow(self, installed_root=None):
        openssl = os.environ.get('EMBLEO_TEST_OPENSSL') or shutil.which('openssl')
        if not openssl:
            self.skipTest('Set EMBLEO_TEST_OPENSSL to run real TLS integration.')
        with tempfile.TemporaryDirectory(prefix='embleo-prizm-tls-') as directory:
            key, cert = Path(directory)/'key.pem', Path(directory)/'cert.pem'
            subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes',
                            '-keyout',str(key),'-out',str(cert),'-days','1',
                            '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(cert,key)
            trusted = ssl.create_default_context(cafile=str(cert))
            class Profiles:
                def for_character(self, account, character):
                    if character != 'pl001':
                        raise ValueError('Unowned character')
                    return player(account)
            prepared_calls = []
            def prepare(room):
                prepared_calls.append(room)
                return {entry['UserId']:dict(EpisodeToken='token-'+entry['UserId'],
                    BattleId='shared-battle',CharacterDetail={},EnemyDetail={},
                    EpisodeDetail={'LayoutGroup':{'Enemies':[
                        dict(EpisodeEnemyId='spawn',EnemyId='boss')]}},EpisodeDetailUser={},
                    MasterGroup={'enemyIndividuals':[dict(Index='boss')]},LimitTime=60,BgmId='bgm')
                    for entry in room['Players']}
            character = {1:'pl001',2:'pl001',3:None,4:10,5:0,6:1000,7:0,8:[],9:[],10:[]}
            profiles = Profiles()
            database = None
            event_providers = {}
            completion_provider = lambda account,room,request,retire:dict(Result={},
                RankingScore=None,Rewards=[],RewardResult={},SpecialDrops=[])
            settlements = []
            if installed_root is not None:
                from pve_preparation import installed_battle_assembler
                from pve_players import SnapshotRaidPlayers
                names = ('UserCharacter.json','UserEquipment.json','UserItems.json','User.json',
                         'UserParameter.json','HcBalance.json')
                originals = {name:(installed_root/'user'/name).read_bytes() for name in names}
                hashes = {name:hashlib.sha256(value).digest() for name,value in originals.items()}
                database_path = Path(directory)/'accounts.sqlite3'
                initial_store = AccountStore(database_path)
                database = initial_store.connection
                self.addCleanup(database.close)
                for account in ('alice','bob'):
                    database.execute('INSERT INTO accounts VALUES(?,?,?)',(account,account,0))
                    database.execute('INSERT INTO tokens VALUES(?,?)',(token_hash('test-'+account),account))
                    for name,content in originals.items():
                        value = json.loads(content)
                        if name == 'User.json': value.update(id=account,name=account.title())
                        database.execute('INSERT INTO saves VALUES(?,?,?)',(account,name,json.dumps(value)))
                database.commit()
                original_saves = list(database.execute('SELECT * FROM saves ORDER BY account_id,name'))
                original_accounts = list(database.execute('SELECT * FROM accounts ORDER BY id'))
                def settle(saves,room,request,retire):
                    # Diagnostic policy: exercises persistence, grants no rewards.
                    settlements.append(request['EpisodeToken'])
                    return dict(Outcome=room['GameOver'][1],RankingScore=None,Rewards=[],SpecialDrops=[])
                def reward_projection(saves):
                    return dict(User=saves.read('User.json'),UserParameter=saves.read('UserParameter.json'),
                        HcBalance=saves.read('HcBalance.json'),UserCharacters=saves.read('UserCharacter.json'),
                        UserItems=saves.read('UserItems.json'),UserEquipments=saves.read('UserEquipment.json'),
                        UserPresents=[],UserTickets=[],UserStampBadge=[],UserEventSkits=[],UserPanelMissions=[])
                render = NativeCompletionRenderer(reward_projection)
                completion_provider = DurableCompletionProvider(database_path,settle,render)
                ordering = lambda snapshot:[dict(Type=1,MasterDataId=row['CharacterId'])
                    for row in snapshot['UserCharacter.json']]
                definition = dict(ScenarioId='PvE_001_EASY',LayoutId='pve_season001',
                    LocationEpisodeId='PvE_Season001',EventDrops=[],EpisodeDetailUser={},
                    LimitTime=300,BgmId='BGM_00071')
                assembler = installed_battle_assembler(installed_root,database_path,ordering,
                    {'episode':definition},{},extra_saves=('User.json',))
                profiles = SnapshotRaidPlayers(assembler.snapshots,assembler.presentation,
                    lambda account,prepared:dict(CharacterId='pl001',Platform='android',
                                                 ClientVersion='1.6.0',MissionRank=1))
                from datetime import datetime,timezone,timedelta
                from pve_events import EpisodeCatalog,ScheduledCatalog
                from prizm_discovery import CatalogRoomViews
                from prizm_admission import admission_payload
                now = datetime.now(timezone.utc)
                catalog = ScheduledCatalog(EpisodeCatalog([dict(EpisodePveEventId='link',
                    EventId='event',EpisodeId='episode',RequiredPower=0,Difficulty=0,
                    MinVerIOS='1.0.0',MinVerAndroid='1.0.0')],{'episode'}),[
                    dict(EventId='event',PublishStartAt=now,StartAt=now,
                         EndAt=now+timedelta(hours=1))],lambda:now)
                views = CatalogRoomViews(catalog,lambda *args:dict(IconUrl='',EmblemId='',
                    IsFriend=False,IsGuild=False),lambda room:1234)
                event_providers = dict(event_catalog=catalog,
                    eligibility_provider=profiles.admission_eligibility,
                    room_settings_provider=lambda episode:dict(Mode=1,SuspendLimits=(60,3,20)),
                    room_view_provider=views,connection_provider=lambda room,tcp,udp:
                        admission_payload(room['RoomId'],'1234567',tcp,udp,'localhost',port,'localhost',port))
                def validate(room,prepared,character_id,overrides):
                    power = prepared.character(prepared.account_id,character_id,overrides)['Power']
                    self.assertEqual(catalog.eligible_event(room['EpisodeId'],power,'android','1.6.0'),
                                     (room['EventId'],room['Difficulty']))
                assembler.eligibility_validator = validate
                def prepare(room):
                    prepared_calls.append(room)
                    return assembler(room)
            runtime = Runtime(2,player_provider=profiles.admission if installed_root else profiles,
                battle_provider=prepare,**event_providers,
                completion_provider=completion_provider,
                battle_character_provider=None if installed_root else lambda account,room:character,
                battle_enemy_provider=PreparedEnemySpawns())
            listener = runtime.listener
            clients = []
            sockets = await runtime.start('127.0.0.1',0,tls)
            port = sockets[0].getsockname()[1]
            async def control(operation,*args):
                def http_thread():
                    return runtime.control.submit(operation,*args).result(3)
                return await asyncio.to_thread(http_thread)
            def unselected(name='alice'):
                if installed_root is not None: return profiles.admission(name)
                return player(name) | dict(CharacterId='',CharacterLevel=0,
                    CharacterPower=0,CharacterHp=0,CharacterAttack=0,CharacterDefense=0)
            http = PveHttp(runtime.control)
            if installed_root is not None:
                # Use the actual server authentication, routing, transaction and
                # response hooks, rather than calling the HTTP adapter directly.
                import server
                config = patch.dict(server.app.config,dict(ACCOUNT_DB=str(database_path),
                    PVE_HTTP=http,TESTING=True))
                config.start();self.addCleanup(config.stop)
                class AuthenticatedHttp:
                    def __getattr__(inner,action):
                        def call(account,data):
                            with server.app.test_client() as client:
                                response = client.post('/api/pve/'+action.replace('_','-'),
                                    data=msgpack.packb(data,use_bin_type=True),
                                    headers={'Authorization':'Bearer test-'+account},
                                    content_type='application/x-msgpack')
                                decoded = msgpack.unpackb(response.data,raw=False,strict_map_key=False)
                                self.assertEqual(response.status_code,200,decoded)
                                self.assertEqual(response.headers['Cache-Control'],'no-store')
                                return decoded
                        return call
                http = AuthenticatedHttp()
                with server.app.test_client() as anonymous:
                    self.assertEqual(anonymous.post('/api/pve/create',data=b'\x80').status_code,401)
                admitted = (await asyncio.to_thread(http.create,'alice',dict(
                    EpisodeId='episode',PublicLevel=1,PveVersion='version')))['Prizm']
                room = runtime.rooms.rooms[admitted['RoomId']]
                tcp,udp = admitted['JwtTcp'],admitted['JwtUdp']
                self.assertEqual(await asyncio.to_thread(http.heart_beat,'alice',
                    {'RoomId':room['RoomId']}),{})
                listed = await asyncio.to_thread(http.room_list,'bob',dict(
                    EventId='event',Difficulty=0,PveVersion='version'))
                self.assertEqual([entry['RoomId'] for entry in listed['Rooms']],[room['RoomId']])
                self.assertEqual(listed['Rooms'][0]['HostCharacterId'],'')
                info = await asyncio.to_thread(http.room_info,'bob',dict(
                    EventId='event',RoomId=room['RoomId'],PveVersion='version'))
                self.assertEqual(info['Room']['HostUserId'],'alice')
            else:
                room,tcp,udp = await control('create',unselected(),'episode','version',False,0,1,(60,3,20))
            room_id = room['RoomId']
            async def receive(reader):
                header = await asyncio.wait_for(reader.readexactly(5),3)
                opcode,size = struct.unpack('<Bi',header)
                return opcode,await asyncio.wait_for(reader.readexactly(size),3)
            try:
                for name,number in [('alice',1),('bob',2)]:
                    if name == 'bob':
                        if installed_root is not None:
                            admitted = (await asyncio.to_thread(http.join,'bob',dict(
                                RoomId=room_id,JoinRoute=1,PveVersion='version')))['Prizm']
                            tcp,udp = admitted['JwtTcp'],admitted['JwtUdp']
                        else:
                            _,tcp,udp = await control('join',room_id,unselected('bob'),'version')
                        opcode,body = await receive(clients[0][0])
                        sid,payload = read_user_message(body)
                        command,notification = read_command_message(payload)
                        joined = msgpack.unpackb(notification,raw=False,strict_map_key=False)
                        self.assertEqual((opcode,sid,command),(7,1000,2))
                        self.assertEqual((joined[1][1],joined[1][8]),('bob',False))
                    reader,writer = await asyncio.open_connection('127.0.0.1',port,
                        ssl=trusted,server_hostname='localhost')
                    clients.append((reader,writer))
                    writer.write(hello_request(tcp)+fallback_request(udp))
                    await writer.drain()
                    opcode,body = await receive(reader)
                    self.assertEqual(opcode,3)
                    self.assertEqual(read_handshake_response(body)[0],0)
                    opcode,body = await receive(reader)
                    self.assertEqual(opcode,9)
                    self.assertEqual(read_handshake_response(body)[0],0)
                    for command,request in [(1,{1:False}),(12,{})]:
                        writer.write(user_message(1000,rpc_request(command,17,msgpack.packb(request))))
                        await writer.drain()
                        opcode,body = await receive(reader)
                        self.assertEqual(opcode,7)
                        service,payload = read_user_message(body)
                        cmd,status,rid,reply = read_rpc_response(payload)
                        self.assertEqual((service,cmd,status,rid),(1000,command,1,17))
                        decoded = msgpack.unpackb(reply,raw=False,strict_map_key=False)
                        self.assertEqual([p[1] for p in decoded[1]],['alice'] if name == 'alice' else ['alice','bob'])
                        self.assertTrue(all(p[3] == '' for p in decoded[1]))
                # Both clients select through the actual reliable socket, with
                # submitted stats deliberately differing from server profiles.
                for index,name in enumerate(('alice','bob')):
                    authoritative = profiles.for_character(name,'pl001')
                    submitted = player_payload(authoritative) | {13:999999}
                    clients[index][1].write(user_message(1000,
                        command_message(5,msgpack.packb({1:submitted}))))
                    await clients[index][1].drain()
                    for reader,_ in clients:
                        opcode,body = await receive(reader)
                        service,payload = read_user_message(body)
                        command,notification = read_command_message(payload)
                        selected = msgpack.unpackb(notification,raw=False,strict_map_key=False)
                        self.assertEqual((opcode,service,command),(7,1000,6))
                        self.assertEqual((selected[1],selected[2][3],selected[2][13]),
                                         (name,'pl001',authoritative['CharacterHp']))
                clients[1][1].write(user_message(1000,command_message(7,msgpack.packb({1:'bob',2:1}))))
                await clients[1][1].drain()
                # Alice sends nothing: delivery must not depend on another request.
                for reader,_ in clients:
                    opcode,body = await receive(reader)
                    service,payload = read_user_message(body)
                    command,notification = read_command_message(payload)
                    self.assertEqual((opcode,service,command),(7,1000,8))
                    self.assertEqual(msgpack.unpackb(notification,raw=False,strict_map_key=False),
                                     {1:'bob',2:1})
                clients[0][1].write(user_message(1000,rpc_request(12,18,msgpack.packb({}))))
                await clients[0][1].drain()
                _,body = await receive(clients[0][0])
                _,payload = read_user_message(body)
                _,status,request_id,reply = read_rpc_response(payload)
                self.assertEqual((status,request_id),(1,18))
                snapshot = msgpack.unpackb(reply,raw=False,strict_map_key=False)
                self.assertEqual(snapshot[1][1][10],1)
                clients[0][1].write(user_message(1000,
                    command_message(9,msgpack.packb({1:'alice'}))))
                await clients[0][1].drain()
                for reader,_ in clients:
                    opcode,body = await receive(reader)
                    service,payload = read_user_message(body)
                    command,notification = read_command_message(payload)
                    self.assertEqual((opcode,service,command),(7,1000,10))
                    self.assertEqual(msgpack.unpackb(notification,raw=False,strict_map_key=False),{1:'alice'})
                self.assertEqual(len(prepared_calls),1)
                adapter = http
                request = dict(EpisodeId='episode',CharacterId='pl001',
                    MemberIds=['alice','bob',None,None],MemberCharacterIds=['pl001','pl001'])
                responses = await asyncio.gather(*(asyncio.to_thread(adapter.start,name,request)
                    for name in ('alice','bob')))
                self.assertNotEqual(responses[0]['EpisodeToken'],responses[1]['EpisodeToken'])
                self.assertEqual(responses[0]['BattleId'],responses[1]['BattleId'])
                responses[0]['EpisodeDetail']['client-edit'] = True
                again = await asyncio.to_thread(adapter.start,'alice',request)
                self.assertNotIn('client-edit',again['EpisodeDetail'])
                self.assertEqual(len(prepared_calls),1)
                # Native reconnect repeats Connect with the original Prizm
                # response, then sends Join(rejoin=true), without HTTP joining.
                old_session = next(key for key, connection in runtime.service.connections.items()
                    if connection.session.admission.account_id == 'bob')
                clients[1][1].close()
                await clients[1][1].wait_closed()
                async def disconnected():
                    while old_session in runtime.service.connections:
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(disconnected(), 3)
                reader, writer = await asyncio.open_connection('127.0.0.1', port,
                    ssl=trusted, server_hostname='localhost')
                clients[1] = (reader, writer)
                writer.write(hello_request(tcp) + fallback_request(udp))
                await writer.drain()
                for expected in (3, 9):
                    opcode, body = await receive(reader)
                    self.assertEqual((opcode, read_handshake_response(body)[0]), (expected, 0))
                writer.write(user_message(1000, rpc_request(1, 19, msgpack.packb({1:True}))))
                await writer.drain()
                _, body = await receive(reader)
                service, payload = read_user_message(body)
                command, status, request_id, reply = read_rpc_response(payload)
                self.assertEqual((service, command, status, request_id), (1000, 1, 1, 19))
                joined = msgpack.unpackb(reply, raw=False, strict_map_key=False)
                self.assertEqual([entry[1] for entry in joined[1]], ['alice', 'bob'])
                self.assertEqual(len(prepared_calls), 1)
                replay = await asyncio.to_thread(adapter.start, 'bob', request)
                self.assertEqual(replay, responses[1])
                # Continue through the battle service on these same sockets.
                creations = []
                for index,name in enumerate(('alice','bob')):
                    character = runtime.rooms.rooms[room_id]['BattleCharacters'][name]
                    if installed_root is not None:
                        play = responses[index]['EpisodeDetailUser']['playCharacters'][0]
                        self.assertEqual((play['characterId'],play['hp'],play['sp'],play['level'],play['exp']),
                            (character[1],character[6],character[7],character[4],character[5]))
                    creations.append({1:{1:bytes(range(index,index+16))},2:{},3:{4:1.0},
                        4:character,6:player_payload(runtime.rooms.rooms[room_id]['Players'][index])})
                    clients[index][1].write(user_message(2000,
                        rpc_request(10,40+index,msgpack.packb(creations[-1]))))
                    await clients[index][1].drain()
                    _,body = await receive(clients[index][0])
                    service,payload = read_user_message(body)
                    command,status,request_id,reply = read_rpc_response(payload)
                    self.assertEqual((service,command,status,request_id),(2000,10,1,40+index))
                    self.assertEqual(msgpack.unpackb(reply,raw=False,strict_map_key=False)[1][1],name)
                    _,body = await receive(clients[1-index][0])
                    service,payload = read_user_message(body)
                    command,notification = read_command_message(payload)
                    self.assertEqual((service,command),(2000,11))
                    self.assertEqual(msgpack.unpackb(notification,raw=False,strict_map_key=False)[4],character)
                enemy_id = responses[0]['EpisodeDetail']['LayoutGroup']['Enemies'][0]['EpisodeEnemyId']
                enemy = {1:{1:bytes(range(2,18))},2:{},3:{4:1.0},4:enemy_id}
                clients[0][1].write(user_message(2000,command_message(12,msgpack.packb(enemy))))
                await clients[0][1].drain()
                _,body = await receive(clients[1][0])
                service,payload = read_user_message(body)
                command,notification = read_command_message(payload)
                self.assertEqual((service,command),(2000,13))
                self.assertEqual(msgpack.unpackb(notification,raw=False,strict_map_key=False)[4],enemy_id)
                # Unreliable object state is carried over authenticated fallback.
                status_update = {1:creations[0][1],2:{1:1.0}}
                clients[0][1].write(user_message(2000,
                    command_message(2,msgpack.packb(status_update)),fallback=True))
                await clients[0][1].drain()
                opcode,body = await receive(clients[1][0])
                service,payload = read_user_message(body)
                command,notification = read_command_message(payload)
                self.assertEqual((opcode,service,command),(Opcode.FALLBACK_MESSAGE,2000,3))
                self.assertEqual(msgpack.unpackb(notification,raw=False,strict_map_key=False),status_update)
                # Drop a socket after objects exist, then restore the peer's
                # scene through the native owner-targeted creation resends.
                old_session = next(key for key, connection in runtime.service.connections.items()
                    if connection.session.admission.account_id == 'bob')
                clients[1][1].close()
                await clients[1][1].wait_closed()
                await asyncio.wait_for(disconnected(), 3)
                reader, writer = await asyncio.open_connection('127.0.0.1', port,
                    ssl=trusted, server_hostname='localhost')
                clients[1] = (reader, writer)
                writer.write(hello_request(tcp) + fallback_request(udp)
                    + user_message(1000, rpc_request(1, 20, msgpack.packb({1:True}))))
                await writer.drain()
                for expected in (3, 9, 7):
                    opcode, body = await receive(reader)
                    self.assertEqual(opcode, expected)
                    if expected == 7:
                        self.assertEqual(read_rpc_response(read_user_message(body)[1])[:3], (1, 1, 20))
                    else:
                        self.assertEqual(read_handshake_response(body)[0], 0)
                clients[0][1].write(user_message(2000, rpc_request(10, 45,
                    msgpack.packb(creations[0] | {7:'bob'})))
                    + user_message(2000, command_message(12, msgpack.packb(enemy | {5:'bob'}))))
                await clients[0][1].drain()
                _, body = await receive(clients[0][0])
                self.assertEqual(read_rpc_response(read_user_message(body)[1])[:3], (10, 1, 45))
                for expected, guid in ((11, creations[0][1]), (13, enemy[1])):
                    _, body = await receive(reader)
                    service, payload = read_user_message(body)
                    command, notification = read_command_message(payload)
                    self.assertEqual((service, command), (2000, expected))
                    self.assertEqual(msgpack.unpackb(notification, raw=False, strict_map_key=False)[1], guid)
                self.assertEqual(len(runtime.rooms.rooms[room_id]['PlayerObjects']), 2)
                self.assertEqual(len(runtime.rooms.rooms[room_id]['EnemyObjects']), 1)
                report = {1:1,2:[{1:'alice',2:100},{1:'bob',2:50}],3:'',4:0}
                clients[0][1].write(user_message(2000,rpc_request(0,46,msgpack.packb(report))))
                await clients[0][1].drain()
                _,body = await receive(clients[0][0])
                service,payload = read_user_message(body)
                self.assertEqual((service,*read_rpc_response(payload)[:3]),(2000,0,1,46))
                _,body = await receive(clients[1][0])
                service,payload = read_user_message(body)
                self.assertEqual((service,read_command_message(payload)[0]),(2000,1))
                clients[1][1].write(user_message(2000,rpc_request(26,47,msgpack.packb({}))))
                await clients[1][1].drain()
                _,body = await receive(clients[1][0])
                _,payload = read_user_message(body)
                self.assertEqual(msgpack.unpackb(read_rpc_response(payload)[3],
                    raw=False,strict_map_key=False),{1:1,2:report})
                for name,response in zip(('alice','bob'),responses):
                    if installed_root is not None:
                        self.assertEqual(await asyncio.to_thread(http.heart_beat,name,{'RoomId':room_id}),{})
                    raw_log = json.dumps({'characters':[dict(characterId='pl001')],
                                          'pveLog':dict(resurrectionAmount=0,damagePer=0.5,damageRank=1)})
                    completion = dict(EpisodeToken=response['EpisodeToken'],
                                      Playlog=native_playlog_hash(raw_log,response['EpisodeToken'])+','+raw_log,
                                      ResultHash=native_result_hash(response['BattleId'],True))
                    result = await asyncio.to_thread(http.end,name,completion)
                    self.assertEqual(result['Rewards'],[])
                    if database is not None:
                        self.assertEqual(result['Result']['Parameter'],result['RewardResult']['UserParameter'])
                        self.assertEqual(result['Result']['Characters'],result['RewardResult']['UserCharacters'])
                        self.assertEqual(result['RewardResult']['User']['id'],name)
                    self.assertEqual(await asyncio.to_thread(http.end,name,completion),result)
                if database is not None:
                    self.assertEqual(list(database.execute(
                        'SELECT * FROM saves WHERE name != ? ORDER BY account_id,name',(JOURNAL,))),original_saves)
                    self.assertEqual(list(database.execute('SELECT * FROM accounts ORDER BY id')),original_accounts)
                    self.assertEqual(len(settlements),2)
                    records = list(database.execute('SELECT account_id,value FROM saves WHERE name=?',(JOURNAL,)))
                    self.assertEqual({row[0] for row in records},{'alice','bob'})
                    self.assertTrue(all(len(json.loads(row[1])['Battles']) == 1 for row in records))
                    self.assertEqual({row[0] for row in database.execute(
                        'SELECT account_id FROM account_activity')},{'alice','bob'})
                    self.assertEqual(list(database.execute('SELECT hash,account_id FROM tokens ORDER BY account_id')),
                        [(token_hash('test-alice'),'alice'),(token_hash('test-bob'),'bob')])
                    for name,digest in hashes.items():
                        self.assertEqual(hashlib.sha256((installed_root/'user'/name).read_bytes()).digest(),digest)
                clients[0][1].write(user_message(1000,command_message(3,msgpack.packb({1:'Back home'}))))
                await clients[0][1].drain()
                opcode,body = await receive(clients[1][0])
                sid,payload = read_user_message(body)
                command,notification = read_command_message(payload)
                departed = msgpack.unpackb(notification,raw=False,strict_map_key=False)
                self.assertEqual((opcode,sid,command),(7,1000,4))
                self.assertEqual(departed[1],'alice')
                self.assertEqual([(p[1],p[8]) for p in departed[2]],[('bob',True)])
                self.assertEqual(await asyncio.wait_for(clients[0][0].read(1),3),b'')
                with self.assertRaises(ssl.SSLCertVerificationError):
                    await asyncio.open_connection('127.0.0.1',port,
                        ssl=ssl.create_default_context(),server_hostname='localhost')
            finally:
                for _,writer in clients:
                    writer.close()
                for _,writer in clients:
                    await writer.wait_closed()
                await runtime.stop()
                if database is not None: database.close()
            self.assertEqual(listener.service_handler.connections,{})
            self.assertEqual(runtime.registry.credentials,{})
            self.assertEqual(runtime.registry.sessions,{})
            self.assertEqual(runtime.rooms.rooms,{})

    async def test_handler_authenticates_and_revokes_on_eof(self):
        registry = SessionRegistry()
        tcp, _ = registry.issue('alice','room',1)
        listener = Listener(registry, lambda *args: [])
        reader, writer = asyncio.StreamReader(), Writer()
        reader.feed_data(hello_request(tcp))
        reader.feed_eof()
        await listener.handle(reader,writer)
        self.assertTrue(writer.closed)
        decoded = FrameDecoder().feed(writer.data)
        status, token, _ = read_handshake_response(decoded[0][1])
        self.assertEqual(status,0)
        with self.assertRaises(SessionError):
            registry.get(token['session_id'])
        self.assertEqual(listener.tasks,set())

    async def test_idle_timeout_and_shutdown_close_writers(self):
        listener = Listener(SessionRegistry(),lambda *args: [],idle_timeout=0.01)
        writer = Writer()
        await listener.handle(asyncio.StreamReader(),writer)
        self.assertTrue(writer.closed)
        writer = Writer()
        task = asyncio.create_task(listener.handle(asyncio.StreamReader(),writer))
        await asyncio.sleep(0)
        await listener.stop()
        self.assertTrue(task.done())
        self.assertTrue(writer.closed)

    async def test_plaintext_listener_refused(self):
        listener = Listener(SessionRegistry(),lambda *args: [])
        with self.assertRaises(ValueError):
            await listener.start('127.0.0.1',0,None)
