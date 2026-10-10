# Multiplayer and social systems

`src/multiplayer.py` owns persistent direct messages, guild membership and guild
messages. `src/server.py` registers its routes, populates profile guild/message
fields and derives message badges. All operations use the authenticated
request's `AccountStore` transaction; failures roll back the entire request.

## Storage and compatibility

Account database schema 4 adds social tables without rewriting accounts,
tokens, saves, activity or follow/block relationships. Direct messages and
guilds are shared records in that same database, rather than per-user JSON
fixtures. Multiple instances see them only when they use the same database.
Older servers that support schema 3 reject this database after migration;
retain a compatible server when rolling back code. Follow the database backup
instructions in [Accounts and Saves](Accounts%20and%20Saves.md).

Requests accept client camelCase fields and PascalCase equivalents. Conflicting
aliases are rejected. Responses use the existing MessagePack contracts.
Mutations require POST; GET cannot fall through to a static success fixture.
All social routes require account authentication.

## Direct messages

Implemented `/api/message/` routes: `top`, `list`, `post`, `like`,
`register-dest`, `remove-dest`.

- Conversations are scoped to their two participants. Looking up another
  pair's message ID does not grant access to it.
- Text and stamp messages use types 1 and 2. System messages cannot be posted
  by players. Message bodies must be nonempty and at most 140 characters.
  Direct and guild posting share a limit of 30 messages per account per minute.
- `list` returns the latest 100 messages in chronological order and marks
  those messages read. Previous history remains stored; this request contract
  has no paging cursor.
- Likes are unique per player and message and can be removed.
- Sending registers the conversation for both participants. Removing a
  destination affects only the caller's destination list and preserves history.
- Blocking in either direction prevents posting, reading and liking direct
  messages, hides the destination and suppresses unread badges. Unblocking
  restores access to retained history.
- Profiles and destination lists expose `LastMessage` and `IsNewMessage` from
  stored messages, and `/api/user/top` derives `badge.IsNewMessage`.

Stamp bodies are retained identifiers; individual stamp ownership/unlock
requirements are not enforced. Text uses an emulator limit of 140 characters;
only the guild comment limit is established by the recovered client constant.

## Guilds

Implemented `/api/guild/` routes: `top`, `info`, `search`, `create`, `update`,
`join-apply`, `join-approve`, `leave`, `promote`, `devolution`, `drop-member`,
`disband`, `block`, `block-list`, `message`, `post-message`, `like-message`,
`delete-message`.

- A player belongs to at most one guild and has at most one pending application.
  Membership is limited to 24 players. SQLite's request transaction serializes
  admission, so simultaneous joins cannot exceed capacity or join two guilds.
- Recruitment 0 is closed, 1 requires approval, and 2 admits automatically.
  Applications can be cancelled or rejected. Application details are visible
  only to the leader and officers.
- Leaders appoint officers and transfer leadership. Leaders and officers can
  edit settings, approve applications, moderate messages and remove ordinary
  members. Officers cannot remove the leader or other officers. Only leaders
  can disband. Leaders must transfer leadership or disband before leaving.
- Guild blocks are separate from personal blocks. They prevent admission and
  remove pending applications; existing members must first be removed.
- Profiles report the player's current guild name. Guild top returns actual
  membership/applications instead of the former hardcoded guild.
- Guild messages require membership. Personal blocks hide messages between
  blocked players. Likes are idempotent; authors can delete their own messages,
  and leaders/officers can moderate others. Removing/disbanding a guild revokes
  message access; disband cascades through its memberships, applications,
  blocks, messages and likes.
- Message reads support `StartDate`, `IsNewer` and `Count` (1–100). Responses
  are chronological. Posting supports `LastDate`. Guild unread badges derive
  from each member's read position.

Native client role checks establish that `Guild.Officers[0]` is the leader;
the remaining officer entries are submasters. Guild message requests format
date cursors as `yyyy-MM-dd HH:mm:ss.ffffzzz`. Stored message times match that
precision and advance on equal/backward clock readings. These are native-code
findings, not Android playtest results.

Guild level/experience/currency, guild missions, event scores, automatic
leadership succession, system history messages and guild raid invitations are
not implemented. Profile combat power is not calculated, so creating/updating
a guild with a positive minimum-power gate is explicitly rejected. Name,
description and notification limits are emulator policy where not established
by a recovered client constant.

## Raids / co-op PvE

Raids are not playable. The recovered client uses two separate layers:

1. `/api/pve/` HTTP calls for event data, room discovery, battle setup, result
   submission, rewards and rankings.
2. A Prizm service for TCP/UDP authentication, relay/RPC room operations,
   ready/character changes, room chat and synchronized battle state.

The create/join HTTP responses supply `Prizm` connection addresses and separate
TCP/UDP credentials. The client contains a reliable hello exchange, UDP packet
ciphering, relay/RPC modules and application-level lobby/battle messages.
Returning only a room identifier from HTTP cannot satisfy that client path.

Completion remains missing after transport game-over: native GameOverTask
async94 (0x18A7D40) calls PrizmOutGameProcessor.PveEnd at0x18A8468 or
PveRetire at0x18A83C4. PveEndRequest carries EpisodeToken, Playlog and
ResultHash; PveRetireRequest carries EpisodeToken/Playlog. PveEndResponse
contains Result, RankingScore, Rewards, RewardResult and SpecialDrops, while
retire returns Result. Configured HTTP end/retire now dispatch through the
listener control bridge; without a configured runtime they remain unavailable.
Transport game-over tests therefore do not establish completed client raids.
Account-scoped prepared-token validation and bounded completion payload handling
are implemented. Identical in-room retries return detached cached responses;
conflicting submissions reject, and provider failures record no completion.
End requires transport game-over; retire does not. Explicit completion_provider
is required and receives authenticated account, detached frozen room/request,
and retire flag. It must validate playlog/hash and implement durable atomic
result/reward idempotency keyed by BattleId/account, including recovery after
process loss or provider failure. The room cache is not persistent reward
authority. Host-reported game-over alone does not validate rewards or playlog.
`DurableCompletionProvider` now supplies the atomic persistence boundary:
account save changes and a compact `PveCompletions.json` result artifact commit
in one SQLite transaction. Concurrent or repeated submissions settle once;
conflicting requests reject. Rendering failures roll back both save changes and
the completion record. Explicit settlement and rendering callbacks still own
gameplay validation, reward policy and native result contents. The journal
stores request fingerprints rather than submitted playlogs or inventory copies.
Provider reconstruction can replay a result with the same prepared context;
room/token recovery after a runtime restart remains unfinished. The installed
two-client TLS test exercises this provider with a diagnostic no-reward policy,
checks one journal entry per account and preserves all original copied saves.
Native metadata defines `EpisodeResult` as `Parameter` (UserParameter),
`Characters` (UserCharacter[]) and `Reward` (RewardResult). PveEnd stores the
received response in PrizmOutGameProcessor.PvEEndInfo at native36A2A70; merely
accepting an empty Result object does not verify the later result UI.
`NativeCompletionRenderer` projects this nested result and the separate
RewardResult from an explicit account-scoped reward reader. It requires all
native RewardResult collections rather than silently using global defaults.
RankingScore, Rewards and SpecialDrops come explicitly from the settlement
artifact. Durable-provider replay reads current saves, preserving subsequent
inventory changes instead of returning old inventory stored in the journal.
In-room retries call an explicit provider `replay` method when implemented.
The durable provider re-renders current snapshots from the existing journal
artifact and never settles through that method: a missing record fails closed.
Providers without this hook retain detached in-room response caching. A SQLite
regression changes inventory after completion, verifies the room retry reflects
that change without another settlement, then removes the journal to verify
that retry cannot grant the reward again.
The installed TLS test now verifies these native nested snapshots; its empty
optional collections and no-reward policy remain diagnostic configuration.
Its installed-data branch also sends create, room-list, room-info, join, start
and end through the real Flask app with two isolated bearer tokens. This
exercises authentication, route normalization, SQLite request ownership,
activity recording and MessagePack response hooks together with the TLS room
flow. Anonymous creation rejects; original account rows, saves and tokens are
preserved. Flask test-client requests are in-process: this does not verify a
public reverse proxy, deployed TLS routing or an Android client.
Configured `api/pve/heart-beat` accepts POST with only RoomId and returns the
native empty PveHeartBeatResponse. The listener checks authenticated current
membership, including after battle preparation; unknown, foreign or departed
rooms reject. It does not create/rejoin rooms or claim to renew a persistent
lease. HTTP activity recording remains the normal account request hook.
The installed Flask/TLS flow covers host lobby and both battle heartbeats;
focused control tests verify outsider rejection and revocation on leave.
Installed master files currently provide no PvE reward table. Native Reward
Type identifies Gold2, Coin3, Noblecoin6 and Item5, but this metadata alone
does not establish raid reward amounts, progression or ranking formulas.
Native result-panel checks narrow one initialization uncertainty:
UIPvEResultPoint.setResponse (`31BA6FC`) obtains PvEEndInfo and checks both
the response (`31BA7E8`) and RankingScore (`31BA7F0`) before dereferencing
score fields. Missing data branches to allZeroClear at `31BA864`, returning
false. UIPvEResultCharacterPoint.setResponse (`31B3CE8`) has the same null
guards (`31B3DD4`/`31B3DDC`) and zero-clear path (`31B3E44`); with a present
score, it also clears display values when CharacterScore is below one.
Thus a null RankingScore is explicitly supported by these two panels. This
does not prove all result-screen consumers or Android execution are compatible.
The normal panel reads BaseScore, Score, TotalScore and the four SpecialEffect
fields; the character panel reads CharacterScore and TotalCharacterScore.
No score formula can be inferred from these display reads.
PveModifyRequest metadata describes RoomId, HostCharacterId, HostLevel,
MemberCount, IsDelete, IsCreate and PublicLevel; response contains Room.
Native caller/order semantics are not yet verified, so the endpoint remains
unimplemented rather than accepting client host/count/deletion authority.
`EventResources` preflights native image construction against explicit installed
manifest names/client languages and can be supplied to EventPublication through
`resource_validator`. EpisodeDetailInfo.get_IconPath (`19D31B0`, event branch
`19D320C`) uses MasterDataId, hence the home event ID, in
`UIExternal/UI/Common/Textures/Icon/PvE/{EventId}`. LogoId selects the localized
boss title `lang_{language}/Textures/Icon/PvE/pve_{language}_{LogoId}`
(`19D33D8`). DecoId selects nested `_01`, `_02`, `_03`, `_05` images and a
localized `pve_{language}_{DecoId}_04` image (`19D35A4` through `19D3920`).
Empty LogoId/DecoId are guarded by native IsNullOrEmpty checks. The validator
does not guess dates, help-text keys, asset availability over HTTP or score
rules. Local installed preflight verifies nine paths for event eve01_00001,
boss-title em0107_001 and decoration eve_calendar_01 in English/Japanese.
Captured home responses contain no events/pveEvents and captured PvE response
files are empty objects, so they supply no reusable production event metadata.
`scheduled_event_metadata` renders PublishStartAt/StartAt/EndAt from the same
ScheduledCatalog used by admission; ranking dates remain explicit independent
configuration. It outputs timezone-aware UTC ISO strings and preserves other
metadata. The default HTTP ApiOptions serializer (`1B2DFB0`) constructs the
SouthPointe MessagePackFormatter (`1B2E068`) with CamelCaseNamingStrategy and
DateTimePackingFormat.Epoch2 for writing (`1B2E044`/`048`). This writing option
does not prohibit string responses: DateTimeHandler.Read (`1D0458C`) has a
string branch which verifies the string object and calls DateTime.Parse at
`1D0480C`. Event string dates therefore have a native read path. This is not
an Android end-to-end check or a claim that every request uses default options.
Before end/retire dispatch, authenticated HTTP releases its authentication-only
SQLite transaction. Otherwise the request's BEGIN IMMEDIATE lock would block a
listener-side completion writer while HTTP waits for that same writer. The
normal response hook records activity in a new transaction after completion.
A real second-thread SQLite regression verifies completion writes succeed and
other-account saves/activity behavior remain scoped.
Requests cap playlog UTF-8 at2MiB, token512 characters, hash256 characters;
Nonempty playlogs now verify the native envelope before provider dispatch:
CalcPlayLogHash0x190C028 UTF8-encodes JSON and episode token, constructs
HMACSHA256 with token bytes as key (0x190C110), hashes the original JSON bytes
(0x190C124), and formats lowercase x2. BuildPlayLog0x1906300 prepends
hash/comma when nonempty. The decoder retains the exact original bytes for
verification, rejects duplicate keys/nonfinite values/out-of-range int64,
requires an object and caps nesting64/nodes100000. Empty playlogs remain
subject to provider policy because the client can skip log submission. A token
known to the client lets it sign fabricated claims; the verified envelope is
not gameplay/reward authority. Native PveEnd async45
(0x36A2748) reads PveStartResponse.BattleId at offset0x50, formats
{0}:{1} with integer win0/1, ASCII-encodes and SHA256-hashes it, then removes
BitConverter hyphens and lowercases the result (0x36A2858..0x36A2940).
An empty BattleId produces an empty hash. The server checks this formula against
the prepared battle and reported GameOverReason.Win=1. This is consistency,
not authentication or evidence of damage/victory. Complete native response
envelopes are checked before caching. HTTP integration and installed TLS tests
exercise explicit no-reward fixture policy, not a production reward validator.

### Available assets and verified client path

The installed data contains partial PvE content: two test-stage layouts and a
season layout under `data/extract/masterdatadebug/episode/`, with enemy,
checkpoint and stage-event records. `data/masterdata/scenario/` contains four
season difficulty scripts plus the two test-stage scripts. Their existence does
not establish that they constitute a complete playable event.

Raid discovery uses the event path in `/api/user/top`: `events` supplies event
metadata, `pveEvents` supplies PvE-specific configuration and player state, and
`orderdIds` supplies the home tile. The client declares `DataType.Event = 3`
and `EventType.Pve = 1`; the corresponding tile uses
`{"MasterDataId": "<EventId>", "Type": 3}`. Match the `EventId` across the
event and PvE records. `PveEvent.EpisodePveEvents` holds the difficulty/episode
links, including `EpisodeId`, `EpisodePveEventId` and `RequiredPower`.
`Event` holds display identifiers and publishing/battle/ranking dates.

The top fixture currently has empty `events` and `pveEvents` arrays and no
event tile. There is no `EventsMasterData` file or loader in this checkout;
an event master-data source would need to feed these response fields. The
normal episode generator only emits character and crossroads episodes, but
that alone does not establish that a raid tile cannot be published: event
registration is a separate path. All 18 `offline_responses/api/pve/` fixtures
and `api/event/list` remain empty. Complete event configuration, battle
handling and reward/ranking policy still need implementation. Publishing a
tile is distinct from making room joining and battles work.

The event-selection HTTP contracts narrow the next discovery milestone:

| Route | Request fields | Response fields |
| --- | --- | --- |
| `/api/event/list` | See the event API request contract | `Events` (event metadata array) |
| `/api/pve/list` | `EventId` | `PveEvent` (one selected event) |
| `/api/pve/create` | `EpisodeId`, `PublicLevel`, `PveVersion` | `Prizm` |
| `/api/pve/join` | `RoomId`, `JoinRoute`, `PveVersion` | `Prizm` |

These are `Game.Net` declarations. In particular, create selects an episode,
not an `EpisodePveEventId`; keep both identifiers in the event configuration
and do not substitute one for the other. A disabled-by-default event registry
can supply top metadata, the tile and selected-event refresh independently of
the room transport. Validate display resources, schedules and installed
episode links before exposing it to clients.

Native inspection of the supplied client establishes these control-flow and
wire-format facts:

| Finding | Owning native method / verification anchor |
| --- | --- |
| HTTP join is followed by Prizm room joining | `PrizmOutGameProcessor.<JoinRoom>d__29.MoveNext`, RVA `0x36A2160`: calls `PveJoinApi` then `JoinPrizmRoom` |
| The game builds Prizm endpoints/credentials and connects a new client | `PrizmManager.<Connect>d__102.MoveNext`, RVA `0x1B6FF84` |
| TCP connects first; UDP connection errors can enter negotiated TCP fallback | `PrizmClient.<DoConnectImpl>d__48.MoveNext`, RVA `0x1B37DF4`, and `CanTcpFallback`, RVA `0x1B3683C` |
| Fallback is a request/response exchange, not an omitted UDP address | `TcpConnection.<FallbackRequest>d__39.MoveNext`, RVA `0x1B1B2A4`; `ProtocolFallbackResponse.Read`, RVA `0x1B3A88C` |
| Unreliable traffic has a distinct TCP fallback opcode | `TcpConnection.SendFallbackMessage`, RVA `0x1B18F10`: opcode 10; fallback request/response opcodes are 8/9 |
| The application room RPC service is 1000; join command is 1 and room-info command is 12 | `AppRoomServiceBase.GetServiceId`, `Join`, `RoomInfo`, RVAs `0x3283DC4`, `0x3283DCC`, `0x3284074` |
| Reliable hello includes protocol version 1 and a length-prefixed credential body | `ReliableHelloRequest.Pack`, RVA `0x1B13918`, and its frame writer at `0x1B1381C` |
| Hello responses contain a status byte, length-prefixed UTF-8 session-token JSON and a length-prefixed message | `ReliableHelloResponse.Read`, RVA `0x1B1396C` |
| Frame headers have an opcode byte followed by a four-byte little-endian length; short lengths/commands are also little-endian | `BinaryUtil.WriteHeader`, `ReadInt`, `ReadShort`, RVAs `0x1B32578`, `0x1B328E0`, `0x1B32510` |

The room protocol has its own MessagePack serializer; it must not be treated as
the HTTP API's named-field payloads. For example, native `JoinRequest.Write`
uses a numeric field ID (1) for its rejoin boolean through `IWriter`'s map/int/
bool interface. Nested player payloads, RPC request/response envelopes,
notifications and the battle relay remain to be verified completely.

Further native inspection establishes the inner RPC envelope (after the
transport has supplied the service ID):

- Client requests contain a little-endian short command followed by a short
  request ID and the serialized request body.
- Reliable responses contain the short command, short status, short request
  ID and serialized response body. Status 1 is success; other statuses enter
  the error path, which reads any remaining body as a UTF-8 error message.
- Response matching requires service ID, command and request ID to match the
  outstanding request. An unreliable response cannot complete that request.

Verification anchors: `RpcClient.Request<object, object>` at `0x25F5EE4`,
`RpcClient.OnReceive` at `0x1B14F44`, `OnReceiveCommand` at `0x1B15070`,
`HandleResponse` at `0x1B151F4`, and `Command.Read` at `0x1B3360C`.
The prototype implements these envelopes and nested join/player payloads.
Android compatibility remains unverified.

A TCP-first local Prizm emulator is therefore a plausible first prototype,
using the client's negotiated fallback. This is an implementation inference
from the native path, not a tested compatibility result. Omitting UDP simply
takes a different early-return path and is not proof of a working fallback.
No original Prizm backend has been shown necessary to reproduce the protocol;
the local replacement is still an unintegrated prototype. Preserve
normal certificate verification when implementing its TLS endpoint.

`room-list` and `get-recently-matching` now return typed empty collections.
Other PvE calls return HTTP 501 rather than acknowledging the old empty
fixtures. They cannot award rewards or accept unchecked battle results.
Event exposure remains disabled.

Required implementation work, in dependency order:

1. Finish the partially established native handshake/serialization contracts,
   including credential validation, session identity, RPC response matching and
   fallback acknowledgement. Keep extracted client artifacts outside the
   repository. Prototype TCP hello, negotiated fallback and room join/info
   before attempting synchronized gameplay; implement UDP cipher/key exchange
   for the full transport.
2. Implement and locally test the compatible transport, room membership,
   heartbeat/expiry, reconnects, host handover and lobby notifications.
3. Connect room create/join/list/matching HTTP handlers to that service;
   enforce public/private/guild visibility, version compatibility and capacity.
4. Supply valid installed event and episode data, multiplayer character/enemy
   setup and battle tokens. Implement host/battle synchronization.
5. Validate completion logs against server-owned sessions, grant rewards once,
   then derive personal/character/guild scores and rankings.
6. Playtest with at least two clients, including disconnect/rejoin and repeated
   result submissions, before advertising raids as supported.

## Current implementation and handoff

Raids remain disabled and unplayable. All raid modules below are local work;
none are registered with Flask or started by `run_server.py`.

| Module | Implemented behavior |
| --- | --- |
| `prizm_protocol.py` | Bounded frames, service/RPC and one-way command envelopes, hello/fallback codecs, ping timestamp echo |
| `prizm_sessions.py` | Shared process-local registry, single-use room-bound credentials, expiry/replay/revocation |
| `prizm_connection.py` | Authenticated state machine, negotiated TCP fallback, bounded notification queue, outgoing revocation checks without extending idle lifetime |
| `prizm_listener.py` | Opt-in verified TLS sockets, idle/write timeouts, notification delivery and shutdown |
| `prizm_lobby.py` | Numeric player/join/info payloads, readiness/join/leave/start notification codecs |
| `prizm_rooms.py` | Locked membership, capacity/version checks, host handover, authoritative snapshots, readiness and battle-roster validation |
| `prizm_room_service.py` | Shared-registry admission with rollback, room-scoped lobby fanout, departure revocation and handover |
| `pve_http.py` | Configured authenticated room-list, room-info, create, join and matching adapters to listener-owned event admission; battle calls remain disabled |
| `pve_events.py` | Installed episode-link eligibility and internal UTC publication/battle schedule gates; event responses not wired |
| `prizm_runtime.py` | Shared service/registry/listener lifecycle; serialized startup/shutdown closes control, sockets and unused admissions |
| `prizm_control.py` | Bounded HTTP-thread submission of create/join/discovery/leave to the listener loop, detached inputs, queued-request cancellation and shutdown |
| `prizm_discovery.py` | Native HTTP room view and explicit public/private/guild access policy; routes not registered |
| `prizm_admission.py` | Validated HTTP connection payload builder; no endpoint configuration or HTTP registration |
| `prizm_battle.py` | Load-status request/notification codec and identity validation; no battle dispatch |

Room-service mutations and fanout must execute on the listener loop.
`RoomControl` supplies a bounded thread-to-loop bridge; the explicit runtime owns its
startup/shutdown. Optional Flask adapters require explicit configuration; production process startup is not wired yet. Cancellation prevents execution only
before the future starts running. Once execution starts, callers must collect
the outcome rather than treating a response timeout as a rolled-back admission. Room admission callers must enforce
authentication, event access, privacy and guild visibility. Socket loss retains
membership pending reconnect policy; explicit departure revokes active sessions
and unused credentials. State is process-local and cannot be shared across
independent HTTP/transport workers.

### Additional verified contracts

| Contract | Native anchor |
| --- | --- |
| AppPlayer fields 1 through 16 | `AppPlayer.Write`, `0x3280BBC` |
| JoinReply fields 1 through 4; RoomInfoReply fields 1 through 6 | `0x1B63BD8`; `0x36AF840` |
| JoinNotification command 2, field 1 AppPlayer | `JoinNotification.Write`, `0x1B6358C`; receive table `0x3BE3998` |
| LeaveRequest reliable one-way command 3, reason field 1 | `AppRoomServiceBase.Leave`, `0x3283E40`; `LeaveRequest.Write`, `0x1B66610` |
| LeaveNotification command 4, fields 1 UserId and 2 remaining AppPlayer array | `LeaveNotification.Write`, `0x1B65A78`; receive table `0x3BE3998` |
| Ready request command 7; notification command 8 | `AppRoomServiceBase.Ready`, `0x3283F28`; receive table `0x3BE3998` |
| InGameStart reliable one-way request command 9; notification command 10; UserId field 1 | `AppRoomServiceBase.InGameStart`, `0x3283FA4`; writers `0x1B62F34` and `0x1B628DC`; receive table `0x3BE3998` |
| Battle service 2000; load-status request 18, notification 19; fields 1 UserId and 2 signed Status | `GetServiceId`, `0x1B61418`; `LoadStatus`, `0x1B619AC`; writer `0x1B66C68`; receive table `0x376C26C` targets `0x1B62740` |

`Game.Net.Prizm` declares `JwtTcp`, `JwtUdp`, `Tcp`, `Udp`, `RoomId` and
`SearchId`. `PrizmManager.<Connect>d__102.MoveNext` at `0x1B6FF84` passes the
credentials and addresses into Prizm. `ServerEndPoint(string)` at `0x1B17B58`
splits on the last colon and parses the port: use `host:port`, without URL
schemes or paths. Native `UILayoutPvERoom.setRoomId` reads SearchId and displays
`Substring(0, 3)` followed by `Substring(3, 4)` (calls at `0x3269740`
and `0x32697AC`). Shorter codes throw before room polling.
`UIPartsPvEInputID` allocates seven digit slots and ten digit buttons;
it enables room entry only when all seven slots are filled.
The admission builder and HTTP provider validation require exactly seven
ASCII decimal digits. Search lookup/uniqueness and public endpoint
configuration remain operator responsibilities. Preserve certificate verification; the unencrypted application
session flag does not replace TLS.

The lobby caller `UILayoutPvERoom.<execute>d__36.MoveNext` at `0x3179568`
checks `IPrizmManager.get_IsHost` (interface slot 6) before InGameStart.
`UILayoutPvERoom.<setReady>d__39.MoveNext` at `0x317C440` compares Ready with
zero and sends the boolean result as integer 0/1 at `0x317C700`. The UI enum
`PlayerState.Ready = 2` is distinct from ready-button wire value 1.
`Rooms.start_candidate` validates host membership and ready guests without
changing state; battle preparation must atomically revalidate before starting.

`Game.Net.PveStartRequest` declares EpisodeId, CharacterId, MemberIds and
MemberCharacterIds. `Rooms.battle_roster` checks these against authenticated
membership and the authoritative episode/character roster. Paired arrays may
arrive in a different order, but cannot replace server slot order. It rejects
foreign, duplicate, missing or stale members and character substitutions.

`PveStartResponse` requires EpisodeToken, CharacterDetail, EnemyDetail,
EpisodeDetail, EpisodeDetailUser, MasterGroup, LimitTime, BgmId and BattleId.
The PvE fixture is empty. The solo-start handler inserts placeholder HP/SP
values and must not be reused unchanged for raids. Battle-start and load-status
codecs are not dispatched; their existence does not prove prepared or
synchronized combat. Other battle commands need separate request/notification
mapping rather than indiscriminate echo.

### Next implementation steps

1. Wire the runtime into process startup/shutdown and authenticated create/join/list/leave
   handlers, with event/privacy/guild gates and server-owned player statistics.
2. Establish reconnect/expiry cleanup, character-change and room-chat behavior;
   verify room status enums and SearchId semantics before exposing them.
3. Build valid installed event/episode and per-account battle data, issue battle
   tokens, atomically commit the host start, then implement battle relay and
   object ownership. Verify full UDP transport or Android TCP fallback behavior.
4. Implement validated, idempotent result/reward handling and scores/rankings.
5. Playtest two Android clients, including disconnect/rejoin and repeated result
   submissions. Do not advertise playable raids before this succeeds.

### Verification

From the repository root:

```powershell
$env:EMBLEO_TEST_OPENSSL = '<path to openssl executable>'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
```

Without OpenSSL, the real TLS integration test is skipped. Focused transport
checks use `-p 'test_prizm*.py'`. Tests cover fragmented/coalesced frames,
wire vectors, bounded payloads, credential replay/expiry/revocation, wrong-room
fallback, unauthenticated traffic, admission rollback and room isolation.
The TLS test submits creation and guest admission from separate HTTP-like
threads through the control bridge, sends native one-way Leave command 3,
and exercises join
notifications, hello/fallback, join/info, idle-recipient readiness delivery,
authoritative snapshots, host departure/handover, socket closure and rejection
of an untrusted certificate. Both clients initially join unselected, then send
CharacterChange over verified TLS; submitted HP is replaced with the server
profile and both peers receive the update. Guest readiness and host start
deliver notifications to both sockets. Concurrent authenticated HTTP start
lookups return distinct account tokens and the same battle ID; detached
responses cannot mutate frozen preparation. This test uses explicit fixture
battle data. It then creates both player objects, delivers the host's authorized
enemy to the guest, relays an authenticated fallback object-status update, and
exchanges host game-over reporting plus guest confirmation over the same TLS
sockets. It does not verify installed episode gameplay, damage correctness,
rewards or persistence.

The broader suite covers account schema/save preservation, social transactions,
chat isolation, guild permissions and explicit raid unavailability. These are
server tests; they do not establish Android compatibility or playable raids.

HTTP discovery contracts: `PveRoomInfoRequest` takes EventId, RoomId and
PveVersion; its response contains Room. `PveRoomListRequest` takes EventId,
Difficulty and PveVersion; its response contains Rooms. `Game.Net.Room`
contains RoomId, EpisodeId, RequiredPower, Difficulty, HostUserId,
HostCharacterId, HostName, HostLevel, IconUrl, EmblemId, Count, IsFriend,
IsGuild and signed-long ExpireAt. `prizm_discovery.room_view` assembles this
schema from server data and tracks host handover; ExpireAt units still need
native verification before publication.

Native RoomPublicLevel values are Public=1, Private=2 and Guild=3;
RoomJoinRoute values are List=1, Matching=2 and Id=3. The implemented emulator
access policy hides private rooms from list/matching and permits direct-ID
admission; guild access requires nonempty current server-resolved shared
membership. This policy is an implementation choice, not recovered backend
behavior. `RoomService.join_checked` now checks authorized episode scope, route and
current host/viewer guilds under the room lock before membership changes.
Guild lookup is configured on the service and executes on the listener loop;
missing guild lookup denies guild admission. `RoomService.discover` uses the same access predicate under the room lock
to filter authorized episode scope, compatible version and open state. Matching
excludes full rooms; explicit list discovery can show full rooms and their count.
`RoomService.match_checked` selects and admits under the same room lock,
preventing last-slot races. It returns real credentials or an explicit error;
private rooms are never matching candidates. Callers must resolve event
difficulty and power eligibility into the authorized episode scope first.
Returned snapshots are detached. HTTP routes remain unwired.
Unknown enum values fail closed without altering persisted account data.

`EpisodeCatalog` validates native EpisodePveEvent link identities, installed
EpisodeId references, RequiredPower, Difficulty and platform minimum versions.
It derives the episode scope from server-owned power and platform/version input;
HTTP MaxPower must not substitute for an authoritative account calculation.
Current version parsing accepts numeric three-part versions only.
`ScheduledCatalog` takes timezone-aware internal dates, normalizes to UTC,
requires PublishStartAt <= StartAt < EndAt, and gates admission with the
half-open battle window [StartAt, EndAt). Publication can precede battle start.
Ended events remain publication candidates for ranking UI; ranking retention
and wire date formatting are not implemented by this catalog. Unknown event
links and absent schedules cannot grant admission. `RoomService.match_event` and `join_event` now compute scheduled eligibility
on the listener loop under the room lock, using a configured server-owned
account eligibility provider. Runtime accepts this provider and the catalog;
unconfigured event admission fails explicitly. No HTTP MaxPower input is used
by these operations. Top/event/list/PvE HTTP responses and production startup
remain unwired. Existing low-level trusted helpers do not apply schedule gates
and must not be selected by HTTP admission handlers.

`RoomService.create_event` resolves the requested EpisodeId to exactly one
active eligible event/difficulty link, rejects ambiguous or ineligible selection,
and uses a configured server room-settings provider for mode/suspend limits.
Public levels are restricted to native values 1/2/3; guild creation requires
current membership. This uses emulator privacy policy (level 2 means private).
Missing configuration cannot create a room. The runtime accepts the settings
provider; low-level create remains a trusted prototype helper and must not be
exposed as an HTTP admission operation.

`/api/pve/room-list` now delegates to `app.config['PVE_HTTP']` when explicitly
configured with `PveHttp(runtime.control)`. Existing account authentication
supplies the caller identity; request fields are EventId, Difficulty and
PveVersion with the shared camel/Pascal alias validation. Invalid requests are
rejected before submission. The adapter submits read-only `discover_event`
through the control bridge with a timeout and returns Rooms. The listener-owned
room-view provider must supply valid event/profile metadata and wire expiry.
Without PVE_HTTP configuration the route retains its typed empty collection.
Production startup and event publication remain unwired; battle/result routes
remain disabled.

The configured HTTP adapter also serves `/api/pve/room-info`, taking EventId,
RoomId and PveVersion. Listener-side `info_event` resolves the room episode's
eligible difficulty links, rechecks schedule/account eligibility, version and
current visibility, then calls the server room-view provider on a detached
snapshot. Direct-ID private-room visibility follows the emulator access policy;
no transport credentials are returned. Unconfigured room-info remains HTTP 501.

`test_pve_http.py` exercises HTTP adapters from worker threads through the real
control bridge and room/event service, with only TLS socket startup mocked.
It verifies public listing, direct-ID private room information, current power
changes, event closure, runtime shutdown and cancellation of a queued read on
timeout. Certificate/socket behavior is separately exercised by the real TLS
listener test. Flask account authentication is covered in test_multiplayer.py;
these layers still need a combined Android playtest after production wiring.

`RoomService.create_http` obtains the authoritative player from a configured
listener-side provider, checks that its UserId matches the authenticated caller,
uses scheduled create_event admission, then builds Prizm through a configured
connection provider. RoomId and both returned credentials must match the actual
admission; response-construction failure removes membership and revokes issued
credentials. Rooms allocate a unique seven-digit SearchId, retain it across host
handover and release it when the room empties. Connection providers must publish
that exact code. HTTP room-info and join resolve it to the internal RoomId before
applying the existing event, version, eligibility and access checks.
Transport identity remains the internal RoomId.
Configured POST `/api/pve/create` accepts EpisodeId, PublicLevel and PveVersion.
Configured POST `/api/pve/join` accepts RoomId, JoinRoute and PveVersion, matching
the native PveJoinRequest declaration. The server resolves the room episode's
active event/difficulty and rechecks account eligibility, version, visibility
and capacity under the room lock. Both return real issued Prizm credentials;
unconfigured admission routes remain HTTP 501. Timed-out queued mutations are
cancelled; already-running mutations return their actual outcome rather than
leaving an admission behind while reporting a timeout. Providers must therefore
be bounded operations. Worker-thread integration tests exercise private-room
route restrictions, successful admission and capacity rejection without leaking
membership. Production providers and two-device Android verification remain
required.

Configured POST `/api/pve/matching` accepts EventId, Difficulty, PveVersion and
optional string MaxPower; eligibility uses authoritative server power. Native
`UILayoutPvEDetail.<AutoMatching>d__44.MoveNext` (RVA `0x3261C9C`) checks
RetryRequest and requires both Prizm and a nonempty Rooms array before directly
calling JoinPrizmRoom. RetryInterval feeds the integer-millisecond Delay
overload; exhausted retries fall through to room creation. The emulator returns
one atomically admitted compatible room with its view and real credentials, or
an empty retry response (three retries, 1000 milliseconds, emulator policy).
Private and full rooms are excluded; view/connection construction failure rolls
back membership and credentials. This is not an Android compatibility proof.

Lobby command 9 now accepts only the authenticated host's UserId and reliable
service 1000 transport. Native `AppRoomServiceBase.InGameStart` (`0x3283FA4`)
sends this one-way command; `InGameStartRequest.Write` (`0x1B62F34`) writes
UserId as field 1. A configured bounded, side-effect-free battle provider must
prepare one detached PvE start response per authoritative member, with a shared
BattleId and distinct member EpisodeTokens. Failed preparation leaves the lobby
open. Successful preparation revalidates the roster, stores the responses,
blocks join/discovery/readiness changes and broadcasts command 10. Internal
PreparedBattle is the admission gate; wire RoomInfo.Status is unchanged because
its state values have not yet been verified. The production response builder
remains unimplemented; test fixtures are not real
character/enemy battle data.

Preparation validates the five nested detail/master fields as MessagePack maps,
LimitTime as a nonnegative signed 32-bit integer and BgmId as a string, and
serializes each response before committing the start transition. These checks
prove wire encodability, not complete nested battle semantics. The solo episode
builder cannot be reused unchanged: fill_episode_character_detail reads global
user fixtures, while episode_start substitutes placeholder HP/SP. Installed
EpisodeMasterData currently has no PvE entries; partial debug layouts require a
raid-specific metadata source and authoritative member-stat builder.

After preparation, reliable battle service 2000 command 18 validates the sender
and relays command 19 load-status notifications only to current room members.
The service records the latest status without assuming that a numeric value
means every player can begin combat. Minion creation, combat relay,
start synchronization and completion/rewards remain unimplemented.

Configured POST `/api/pve/start` retrieves the authenticated member's prepared
response after checking EpisodeId, CharacterId and the paired roster arrays.
Retries return the same member token; retrieval writes no account progress.
Native `PrizmOutGameProcessor.<PveStart>d__44.MoveNext` (`0x36A3150`) allocates
MemberIds with four slots (`0x36A324C`) and fills them from the complete player
list, while MemberCharacterIds is Select/ToArray over actual players. The
adapter accepts trailing null padding only on that four-slot MemberIds format;
interior nulls, duplicates and forged/missing members are rejected. Prepared
responses are copied and scoped to the caller, never returned as a room-wide
token map. This path still requires a real response builder and Android proof.

Player-object creation uses reliable service 2000 RPC command 10
(`InGameServiceBase.CreatePlayer`, `0x1B61750`). Native CreatePlayer.Write
(`0x1B585E0`) fields 1..7 are Guid, Position, Rotation, CharacterData, Type,
AppPlayer and ToUserId; Guid.Write (`0x1B505D8`) wraps Bytes as field 1.
CreatePlayerReply.Write (`0x1B598B8`) wraps the authoritative AppPlayer as field
1. Receive table `0x376C26C` maps command 11 to CreatePlayer unpack at
`0x1B622EC`. The implementation checks transforms, the nonempty 16-byte object
GUID, server-owned character data and player identity, and room membership of
an optional recipient. It registers room-local GUID ownership and relays
command 11 to peers (or the explicit recipient). Identical retries return the
same RPC reply without another peer creation; changed or stolen GUID reuse is
rejected. A configured battle_character_provider must build the authoritative
numeric CharacterData snapshot; no production provider exists yet. Tests prove
codec/dispatch behavior, not Android spawning or complete battle relay.

Enemy creation is reliable one-way command 12 (`InGameServiceBase.CreateEnemy`,
`0x1B617FC`), with Guid, Position, Rotation, UniqueId and ToUserId as fields
1..5 (`CreateEnemy.Write`, `0x1B5639C`). The receive table maps command 13 to
CreateEnemy unpack at `0x1B624C0`. A configured battle_enemy_provider receives
the authenticated account and room snapshot and returns allowed episode spawn
UniqueIds; this must establish both spawn validity and creation authority.
UniqueId is not assumed to be a master enemy ID. The room registers enemy GUID
ownership, rejects player/enemy GUID collisions and sends command 13 to peers
or an admitted target. Identical repeated creates do not duplicate notification;
changed GUID reuse is rejected. Actual episode-spawn authorization and targeted
recreation during reconnect still require integration and Android verification.

prepared_enemy_spawns provides initial layout-spawn authorization from the
frozen per-account EpisodeDetail.LayoutGroup.Enemies. Only the authenticated
room host receives the EpisodeEnemyId allowlist; guests and outsiders receive
an empty set. It rejects duplicate or empty construction IDs. Native
CreateEnemy async132 (0x3129764) gates creation through IGameNetworkManager
slot5 IsOwnLocalOrHostLocation (0x3129888) and passes construction UniqueId
at0x3129A1C into the notification. SetupConstructionData (0x17D3FF0) copies
the source's virtual UniqueID slot5 to construction offset0x10 (0x17D4158).
EpisodeEnemyInfo.get_UniqueID (0x3617274) reads the inherited _id field;
the adapter exposes that value as EpisodeEnemyId. EnemyId is the separate
individual identity, not the spawn request's UniqueId. This provider covers
initial layout rows; transformation, sequence summons and child construction
identities still need their native derivation before authorizing those spawns.

Dynamic construction IDs use a separate namespace. GetProcessingInternalEnemyId
(0x17D4A54) prepends `Ext.` to its argument. SetupConstructionDataTransform
(0x17D44BC) concatenates the source construction UniqueId, `/`, and the
resolved transformed individual's Index (0x17D4624..0x17D463C), then applies
that prefix (0x17D466C) before storing the resulting UniqueId. The source
individual's TransformConditions must be nonzero (0x17D4530/0x17D4538).
SetupConstructionDataSequenceSummon (0x17D4AA8) instead concatenates the
source construction UniqueId, `+`, and the summoned individual's Index
(0x17D4C9C..0x17D4CB0), then applies `Ext.` (0x17D4CE0). Installed individual
masters expose Index, TransformConditions, TransformId and
SummonEnemyIndividualIds. These formulas alone do not authorize arbitrary
suffixes: dynamic spawn policy must resolve the declared individual links
from the frozen layout/master group, including nested construction identities.

PreparedEnemySpawns now validates these paths against the frozen layout and
MasterGroup.enemyIndividuals. It resolves each `Ext.` step back to a layout
root, requires a nonzero TransformConditions with matching TransformId for `/`,
and a declared SummonEnemyIndividualIds target for `+`. Missing source/target,
unrelated installed individuals, guest callers and excessive nesting reject.
RoomService accepts this provider's boolean authorize method as well as the
older exact-ID collections. Tests cover a transformed boss summoning a minion
and attempts to use unrelated or wrong-kind links. Runtime assembly still
needs integration; this does not verify Android spawning.

Child creation async144 (0x312C59C) selects an individual ID from the parent's
ChildEnemyData using its formation entry's index, concatenates parent UniqueId,
`.` and that child ID (0x312C69C..0x312C6B4), then prepends `Ext.`
(0x312C6E4). It looks up this construction identity before creating the child.
PreparedEnemySpawns therefore also checks `.` paths against the parent's
frozen layout Child.Ids. Transform construction copies ChildEnemyData from
its source (0x17D48C0/0x17D48C4), so transformed parents retain these links.
Sequence summons and child targets do not inherit the layout parent's child
allowlist. Tests cover declared children, children of transformed parents,
unrelated targets and unsupported nested child creation.

BattleAssembler carries a PreparedEnemySpawns policy. Runtime adopts it when
no explicit enemy provider is supplied, so installed battle preparation and
spawn validation use the same frozen response. An explicit operator override
still takes precedence. Runtime tests verify that wiring and room-service
tests exercise the installed policy through command12, peer notification,
ownership checks and targeted recreation. Complete event/operator configuration
and real client gameplay remain unverified.

pve_setup.installed_runtime_factory assembles the installed battle provider
with the scheduled event catalog and explicit eligibility, room-settings,
room-view, player and connection readers. It requires catalog episode IDs to
match the installed definitions exactly and validates required reader callables.
The returned zero-argument factory creates Runtime on the host's owning event
loop; configuration alone opens no listener or player database. Operator config
can assign it to PVE_RUNTIME_FACTORY and provide PVE_BIND_HOST, PVE_BIND_PORT
and PVE_TLS to the existing HTTP lifecycle. Guild/minion providers remain
explicit optional inputs. A wiring test checks the catalog, account readers,
assembler and inherited enemy policy; it does not substitute for installed-data
or Android integration verification. Verified event metadata and complete
account readers still need a concrete operator configuration.

The factory preloads every catalog episode through InstalledBattleResponses
before returning the runtime factory. Missing scenarios/layouts or invalid
response time/music types fail configuration before a listener can start.
This preflight reads installed data only; it does not prepare accounts, mint
episode tokens or edit progress. The setup test verifies a failing episode
preflight prevents factory creation.

SnapshotRaidPlayers builds lobby AppPlayer and eligibility values from one
PreparedCombatStats account snapshot per read. It reads User.json for account
identity/name, resolves the owned selected character's level/visuals/spells,
and calculates HP/attack/defense/power from the same saved loadout. The explicit
selection callback supplies server-resolved character, platform, client version
and mission rank using that preparation. Operator configuration must include
User.json and relevant selection documents in the snapshot; client-reported
power is not used. The provider exposes player and eligibility callbacks for
the runtime factory. Separate callback invocations take separate fresh snapshots;
this is not an atomic multi-call admission transaction. A focused test verifies
one read uses one account preparation and isolates a second account.

Character selection is not carried in PveCreateRequest/PveJoinRequest; their
fields are episode/public-level/version and room/join-route/version. The client
instead exposes AppRoomServiceBase.CharacterChange (0x3283EB4), sending command5
with CharacterChangeRequest.Player at request offset0x10. Its writer delegates
to AppPlayer.Write (0x1B51FD4). CharacterChangeNotification contains UserId and
AppPlayer, and its callback invokes OnCharacterChange(userId, player)
(0x328383C). RoomService handles reliable lobby command5, using only the
authenticated UserId and requested CharacterId from the submitted AppPlayer.
Its player provider's for_character method resolves saved ownership/loadout
and recalculates the profile. SnapshotRaidPlayers exposes this method without
persisting a new selection. Rooms preserves member order and host assignment,
resets readiness, rejects changes after preparation, and publishes command6
with authoritative UserId/AppPlayer to the room. Native command6's receive
jump-table entry0x3BE39A8 targets0x3284470, which unpacks the character-change
notification. Submitted combat stats and role/order fields are ignored. Tests
cover forged HP/role/order, wrong account, unowned selection and frozen battle.
Do not infer the initial raid selection from
the social favourite-character setting or trust submitted AppPlayer stats.

The installed runtime factory also binds a battle-time participant eligibility
validator. After resolving the selected party/replacement ID and level overrides,
BattleAssembler calculates power from that participant's frozen preparation and
rechecks the scheduled catalog using fresh server platform/version metadata.
The eligibility reader's initial-selection Power is not reused. An expired
event or ineligible selected character rejects preparation before room battle
state or tokens are published. Tests check selected frozen power replaces a
larger reader value, event rejection propagates, and replacement ID/level
override reach the validator. Separate account metadata reads remain explicit;
this is not an atomic transaction across all participants.

Explicit data_root now reaches gimmick loading as well as layout/scenario
loading. Its episode/location and stage-option dependencies resolve under that
root instead of the process working directory. Existing calls without a root
retain their data-directory behavior. An isolated loader test verifies all
gimmick dependencies use the configured root.
Raid definitions may also supply LocationEpisodeId separately from playable
EpisodeId, ScenarioId and LayoutId. It selects the installed episode master
used for location-dependent gimmicks. Installed season-one data uses scenario
PvE_001_EASY and layout pve_season001, while episode master PvE_Season001 maps
to ORB51; using the scenario ID for this lookup yields no areas. Omission
retains the ordinary episode-ID lookup. Empty/non-string overrides reject.
An installed-data diagnostic with this mapping assembles five scenario entries,
two checkpoints and one enemy. All four PvE_001 difficulty scenarios contain
party parameter type1/value BGM_00071 (Game.Net.PartyParamType.BgmId=1), then
script event Examples/PvE_test001. This establishes scenario music and a script
dependency; it does not prove the initial response BgmId, battle LimitTime or
script loading by the APK. The manifest's events/examples/pve_test001 bundle
was retrieved successfully with its declared size. Its EventScript operations
are EventStart (UseEventCamera=0, IsCancelSeqEvent=1), ActivateInGameUI
(IsTown=0, IsChange=0, IsActivate=1), then EventEnd (KeepPartyStopped=0).
This establishes asset availability and serialized UI initialization, not
successful client execution or enemy spawning. The extracted bundle is private
and is not included in the repository.
The installed season-one layout has one PvE_001_0001 root referencing
em0107_001_01, AppearanceRule.Type=0 (EnemyAppearanceType.Init), appearance
count1 and ScenarioNo[-1,99999]. That individual resolves uniquely in installed
master data. PreparedEnemySpawns authorizes this root for the host and rejects
outsiders/undeclared IDs in an installed-master diagnostic. Its saved layout
switches are all zero, matching the adapted Flags=0 for this particular entry;
this does not validate flag adaptation for other layouts or prove client spawn.
An isolated two-account installed-data diagnostic exercises Runtime/PveHttp
admission, canonical unselected profiles, reliable framed character changes,
guest ready, host start and concurrent account-scoped HTTP start responses.
It uses installed character/equipment/enemy masters, readonly account snapshots,
and the mapped season-one loader. Shared BattleId, distinct tokens and paired
HTTP/transport character ID, HP, MP, level and Exp match; database dumps and
original save hashes remain unchanged. Listener startup is mocked in this
diagnostic; it does not prove installed preparation over real TLS or Android.
Time limit, initial BgmId and fresh episode-user defaults are diagnostic policy,
not verified production configuration.
The optional installed TLS test combines this preparation with two verified
TLS clients through character selection, ready/start, player creation, actual
layout enemy delivery, fallback state updates and game-over confirmation.
Set EMBLEO_TEST_RAID_DATA to a private installed data directory containing
masters, extracted layouts/scenarios and user save fixtures; no assets or saves
are added to the repository. It copies fixtures into temporary schema4 SQLite
accounts, verifies paired HTTP/transport resources and unchanged database/source
save hashes, and shuts down the listener. Without this variable the test skips.
This is a simulated-client integration test, not Android gameplay or reward
persistence verification; the diagnostic episode defaults remain unverified.
Native InGameScene.applySuspendData (0x2E61E10) obtains EpisodeDetailUser
through IUserDataManager method slot12, reads PlayUser at offset0x30
(0x2E61FA4), and branches to the separate character restoration block
(0x2E624C4) when null. PlayCharacters at offset0x38 is checked separately
(0x2E6252C/30). Thus absence of PlayUser skips this path's resource restore
rather than proving a crash; it does not establish that every PvE initialization
path accepts omitted fresh-run fields. Paired PlayCharacters must remain supplied.
The installed TLS test enters through PveHttp event creation, room list/info
and guest admission, then uses their credentials on actual sockets. It verifies
discovery of the unselected host and rechecks selected power/event binding at
preparation. Event schedule, display metadata, expiry and connection endpoints
are explicit test policy; publication tiles/resources and production routing
still require their configured integration and client checks.
Authenticated Flask tests also compare user/top events/pveEvents against
event/list and pve/list for two accounts, verify one Type3 raid tile alongside
existing story tiles, and check that hidden events disappear from all three
paths. These tests use minimal explicit metadata and verify publication wiring,
not native event-resource completeness or Android tile rendering.
Difficulty configuration must also select the installed enemy individual:
the shared season-one layout references em0107_001_01/EASY (HP120000, attack65),
while _02/NORMAL, _03/HARD and _04/EXTREAM carry distinct AI/stats. Other
variants exist, so do not infer the chosen individual from the scenario name.
Raid definitions may supply EnemyIndividuals mapping EpisodeEnemyId to an
installed individual Index. RaidEpisodeLoader validates both references,
replaces only EnemyId on a detached layout, preserves spawn identity/child links,
and derives EnemyDetail from the resulting layout. This makes explicit operator
difficulty mapping possible without changing installed assets or trusting clients.

The client maintains a separate multiplayer LastSelectCharacterId in
MultiPlayLobbyUtility's static state (getter0x343AF2C, setter0x343AF94 writes
static offset0x58). This is not an account save field or a favourite-character
alias. JoinPrizmRoom async30 (0x36A17C4) requests/reads the JoinReply and
registers its OnJoin callback; that path alone does not establish an automatic
CharacterChange after admission. CharacterChange async35 (0x369F7A4) waits
an AsyncNop, flushes buffered messages (0x369F898), and sends command5
(0x369F8AC) without a command-specific request/reply wait. The server's
one-way update and command6 notification match this sending path. Initial
profile configuration remains distinct from a later client selection change.
The lobby-scene caller establishing initial selection is described below.

The lobby caller is now located: UILayoutPvERoom.updateCharacterIconList
async34 actual0x317D018 reads MyPlayer.CharacterId (0x317E008). It uses
MultiPlayLobbyUtility.LastSelectCharacterId at static offset0x58 only when
that player ID is empty (0x317E014/0x317E074); a nonempty admission profile
therefore bypasses the saved local last-selection branch. When a last selection
exists it constructs a Type1 OrderedIdItem with that ID and invokes
UIPartsPvERoomContents.SetCharacter at0x317E29C. SetCharacter obtains the
owned CharacterDetailInfo and copies ID, level, HP/attack/defense, visual
equipment and spell arrays into MyPlayer (0x309B798..0x309B834), then sends
CharacterChange at0x309BA0C. This identifies an initial-selection compatibility
path: SnapshotRaidPlayers.admission now clears character identity, visuals,
spells, level and stats while retaining account/profile metadata. Its separate
admission_eligibility reader calculates maximum owned character power before
selection. Operator configuration can use these two bound callbacks; the
character-change resolver remains available through the provider instance.
Room admission and lobby serialization allow only a canonical unselected state
with zero stats/readiness and empty arrays. Rooms rejects readiness or battle
preparation until every participant has a selected character. Character change
still resolves owned data and cannot submit an empty selection. Discovery can
represent an unselected host. Battle preparation rechecks the actual selected
power, so admission capacity does not authorize an ineligible battle choice.
Tests serialize an unselected join, reject nonzero placeholder stats and
ready/start attempts, and allow start after server-resolved selection.

ScheduledCatalog.active_event_ids distinguishes current battle windows from
historical published/ranking events. CatalogRoomViews filters frozen links
against that current window, so reuse of an episode in a later event does not
make historical links ambiguous. Missing or overlapping active links still
reject rather than choosing an arbitrary difficulty.
Event-created rooms retain their resolved EventId/Difficulty internally.
Discovery, matching, direct admission and preparation enforce that binding;
episode reuse cannot reassign an existing room to a later event. Low-level
non-event room helpers remain available for isolated transport tests.

CatalogRoomViews supplies the runtime's room_view_provider by combining frozen
catalog difficulty/power links with the current room host. A server display
reader receives viewer account, host account and current character ID (which
can be empty before selection), and supplies icon/emblem and friendship/guild
flags. A separate expiry reader supplies verified native wire units. Missing
or ambiguous catalog links reject instead of inventing difficulty metadata.
Its focused test covers selected/unselected host identities, detached catalog
data and unknown episodes. Concrete display and expiry readers still belong
in the operator configuration; room access is enforced by RoomService before
calling the view provider.

Targeted player/enemy recreation now compares the registered object identity
without ToUserId. An unchanged object from its existing owner can be resent to
an admitted peer, including repeated targeted sends, without creating another
registry object. Untargeted duplicate creation remains suppressed. Changes to
the stored creation data remain rejected; refreshing transforms/character data
during a full reconnect still needs verification.

Reliable ObjectHeartbeat command 22 (`0x1B61AE8`) sends UserId and Guid;
ObjectAliveConfirm command 24 (`0x1B61B60`) sends FromUserId, ToUserId, Guid and
Alive. Peer commands are 23 (receive branch `0x1B62364`) and 25
(`0x1B623C4`). Dispatch authenticates the sender, restricts heartbeats to the
registered owner and routes alive-confirm to that owner only. This supports the
missing-object notification followed by targeted recreation; it does not renew
credentials or implement complete connection recovery. The tests exercise
heartbeat, missing confirmation and targeted resends through connection frames.

Object status updates use unreliable command 2 (`InGameServiceBase.UpdateStatus`,
`0x1B614AC`) and peer command 3 (receive branch `0x1B621E4`). The fields are
Guid, Position, Rotation, MoveEnvironment, MoveStatus, BattleStatus, Flags,
ExParam, UpdateSequenceNo, MoveSequenceNo and StatusSequenceNo. Dispatch checks
current membership, prepared battle and registered object ownership, validates
top-level maps/transforms/integers and preserves nested status maps and sequence
counters. Full nested status semantics and counter ordering remain unverified.
The TCP-first implementation sends these notifications as fallback frames only
to peers that negotiated fallback; queued status messages coalesce by GUID,
placing the newest update at the end of the queue. This does not implement UDP
ciphering or establish Android fallback behavior. Reconnect replay, ownership
transfer, action/attack/damage messages and combat completion remain unfinished.

Movement command 6 (`InGameServiceBase.MoveAction`, `0x1B61638`) and attack-start
command 8 (`InGameServiceBase.AttackStart`, `0x1B616C8`) use reliable one-way
delivery. Their peer commands are 7 (receive branch `0x1B62270`) and 9
(`0x1B6216C`). Movement fields are Guid, Type, Vecter0 and Vecter1; attack-start
fields are Guid, TargetInfo and AttackName. Dispatch validates bounded payloads,
GUID ownership and prepared/current room membership before relaying to peers.
Movement vectors and type, and attack target/name container types are checked;
TargetInfo internals and attack-sequence authorization still need verification.
This relay does not implement damage application or results.

Reliable BattleAction command 4 (`InGameServiceBase.BattleAction`, `0x1B61580`)
now relays peer command 5 (receive branch `0x1B62444`) after the same registered
object-owner check. Fields are Guid, ActionInfo, Position, Rotation,
MoveEnvironment, MoveStatus, TargetInfo and unsigned MoveSequenceNo
(`BattleActionNotification.Write`, `0x3287654`). Container, transform and
sequence types are validated; nested action/target/environment semantics pass
through and require further native/client verification. Successful relay is
not proof that attacks apply damage or that a complete battle works.

Reliable reflection command 16 (`InGameServiceBase.ReflectParam`, `0x1B61910`)
relays peer command 17 (receive branch `0x1B626C0`). Fields are Guid, Reflector,
Receiver, ReflectParam and DamageParam (`ReflectParamNotification.Write`,
`0x36AA394`). The native SendAction_ReflectParam path (`0x2FF76C0`) checks
NetGameObject.IsLocalLocation before sending; dispatch checks the originating
GUID's registered owner. Nonempty reflector/receiver GUIDs must exist in this
room, and nonempty damage-credit UserId must identify a member. Empty/default
reference GUIDs remain supported. Nested reflection semantics and damage values
are client signals; they do not authorize rewards or persistent progress. Full
damage application, minion/static-object references and Android verification
remain required.

Reliable DestroyObject command 14 (`InGameServiceBase.DestroyObject`,
`0x1B61898`) relays peer command 15 (receive branch `0x1B62528`), with Guid and
ToUserId as fields 1 and 2 (`DestroyObject.Write`, `0x1B5BD94`). The registered
owner may remove an object globally; the room clears its ownership/status,
retains an owner tombstone to reject GUID reuse/stale updates and suppresses
duplicate destruction notifications. A named admitted recipient receives a
targeted removal while the shared registry remains intact. This targeted/global
policy is emulator behavior, pending Android verification. Minion cascades,
reconnect recreation and ownership transfer remain unimplemented.

Reliable minion creation uses command 27 (`InGameServiceBase.CreateMinion`,
`0x1B61C4C`) and peer command 28. Native CreateMinion.Write (`0x1B572A8`)
fields are Guid, OwnerGuid, Position, Rotation, UniqueId, Param and ToUserId.
Dispatch requires an existing parent object owned by the authenticated sender
and an explicit battle_minion_provider approval for the detached request.
Self-parenting, cross-kind GUID collisions, destroyed GUID reuse and foreign
recipients are rejected. Identical broadcasts are suppressed; targeted resends
remain possible. Minions join the room's ownership/status/action/heartbeat/
destruction checks. Production skill/spawn validation, parent-death lifecycle
and Android spawning remain unverified.

CreateMinionDecoyClipBehaviour.CreateMinion (0x1857848) requires owner
location, constructs MinionSetupParamMagicDecoy and uses UniqueId
`MagicDecoy` at0x1857A78. CalcDecoyHP (0x1857BD8) reads the owner's MaxHP,
applies a buff calculation and rounds up with Mathf.CeilToInt; accepting an
arbitrary client HP as authoritative is not equivalent to that calculation.
The setup JSON includes MaxHP, HP, Base_LoadPath and AddPrefabInfos.
ReceiveCreateMinionImpl's async body (0x199E0AC) reconstructs CreateParam
from the notification and invokes CreateMinionInternal at0x199E1D0.
QueryMinionCreatorSetupParam (0x1998D48) normally obtains a copied installed
SetupParams entry, with a separate magic-decoy branch. That branch
(0x1998DF4) deserializes MinionSetupParamMagicDecoy at0x1999044 and uses its
prefab paths. A production approval provider must therefore validate the
installed skill/setup relationship and dynamic parameters, in addition to
the existing GUID ownership checks. The isolated trial now permits the verified
static Bit binding described below; dynamic decoys remain a playability gap.

SetupParams' native static initializer (0x343184C) registers four preset keys:
Toto (0x3431C24), Bit (0x3431E44), EnemyBit (0x3432064) and MagicDecoy
(0x3432250). Bit uses the pl021 bit prefab; EnemyBit uses an em0221 bit
prefab. GetCopySetupParam (0x3431724) copies the registry entry, rather than
loading a JSON minion-master table. These are preset identifiers, not evidence
that every equipped skill may create each preset. CharacterSequenceMasterData
contains serialized categories whose clip records include default minion
settings even for ordinary attacks; presence of a `clip_Minion...` key alone
must not be used as skill authorization. Resolve the active native sequence
behaviour and its equipped-skill relationship before enabling the provider.

CreateMinionClipBehaviour has a serialized MinionUniqueId at0x88, defaulted
to Bit by its constructor (0x185696C); the timeline can override it.
OnBegin (0x1856D18) requires owner location, obtains the owner's bit
supervisor and compares ProcessorCountWithCreating with the live owner's
`MaxMinionCount` parameter at0x1856EF0. Equality returns without creating;
this trace does not establish a general server-side greater-than limit.
CreateMinionBitClipBehaviour's async body (0x18569C0) creates via that
supervisor and applies its serialized Mode at0x1856C08. Those serialized
behaviour fields are absent from the exported sequence clip slots inspected
here. The adapted master response alone does not identify the active minion
behaviour or its count policy; inspect the timeline asset and owner parameters.

The installed pl021 Charge1 timeline provides one concrete binding: its
enabled MonoBehaviour resolves through m_Script to
CreateMinionBitClipBehaviour, with MinionUniqueId `Bit` and Mode1, referenced
by another timeline object. The checked OnBattle, Attack1, Magic1 and
SpecialSkill1 bundles have no MinionUniqueId behaviour. All five fetched
bundles matched the installed manifest sizes before inspection. This proves
one timeline-to-preset relationship, not the equipped parameter count,
runtime activation timing, full character coverage or Android peer spawning.

PreparedBitSummons now implements that verified pl021 binding. It requires
the frozen battle CharacterId and MasterDataId to be pl021, the registered
parent to be that account's player object, preset Bit and empty parameters.
The empty native constructor argument resolves to the empty string literal;
installed pl021 UniqueParamData sets MaxMinionCount5. The provider reads that
bounded integer from the frozen master response and counts live Bit objects
for this account, allowing existing GUID resends without consuming a slot.
Recreating the player parent GUID does not grant additional summon slots;
this account-wide bound is emulator policy for one selected raid character.
RoomService still checks collisions, destroyed GUIDs and recipients. Tests
exercise actual command27 dispatch and peer command28, deny the sixth live
spawn, foreign parents, unsupported characters/presets and dynamic parameters.
This enables one verified summon family in the isolated trial; dynamic decoys,
other preset bindings, replacement costumes and skill timing remain unfinished.

The installed decoy binding is EquipmentMasterData wp005_05_003, SpellId
mag01_1101_00 (SpCategory11). Its magic timeline contains an enabled
CreateMinionDecoyClipBehaviour. Serialized settings specify DecoyHpRate0.5,
the matching mag01_1101_00 minion prefab and matching effect prefab.
CalcDecoyHP multiplies live owner MaxHP by that rate (falling back to0.5
when nonpositive), then calculates Param_MinionDecoyDegradedHp with the
attack settings' BuffKeyHashs before CeilToInt. Installed buff
psv_wp005_05_003 supplies that effect with AddMultiply reflection, keyword
mag01_1100 and level values1.06/1.09/1.13/1.18/1.25. A validator which merely
requires ceil(frozenHP*0.5) would reject the legitimate weapon passive.
Use the frozen equipped spell, installed prefab binding and verified buff
level/reflection calculation, while accounting for live owner MaxHP changes.
The inspected magic and dependency bundles matched manifest sizes; native
peer spawning and the full dynamic validation policy are still unverified.

decoy_max_hp implements only the verified AddMultiply calculation for supplied
owner MaxHP/rate/effect values. BuffCollection.EffectTypeSet.CalculateValue
(0x3467F74) starts that bucket at RawBuffValue.One, subtracts One from each
effect at0x34682BC, adds deltas at0x34682C8 and multiplies the base at0x3468330.
The helper rounds each intermediate to native single precision, applies the
nonpositive-rate fallback, zero lower bound and final ceiling. Tests distinguish
int-to-single rounding from Python double arithmetic and additive reflection
from stacking multiplication. The helper does not determine equipped effects,
maintain live MaxHP or approve a MagicDecoy spawn; those remain policy work.

PreparedDecoyRelay supplies a separate client-owned combat relay policy.
The operator provides verified spell-to-prefab bindings and a bounded live
decoy limit. CharacterData.WeaponSpell contains equipment IDs, as does the
saved WeaponSpell slot. Approval requires the selected item in frozen owned
userEquipments and its frozen equipment master's SpellId to match the binding,
an account-owned registered player parent, exact configured prefab paths and
strict native JSON fields with signed-int32 nonnegative HP <= MaxHP. These HP
values remain client combat claims; the relay does not grant rewards/progress
or attempt to recreate the client's skill simulation. Existing RoomService
checks freeze prefab/maxHP identity on recovery, allow bounded HP updates,
validate recipients and reject destroyed/colliding GUIDs. Tests exercise real
peer creation and targeted recovery, including denial of changed maxHP and
unknown/unequipped prefabs. The isolated trial enables the verified
mag01_1101_00 binding with a16-live-decoy account limit and installed-manifest
preflight. Other skill bindings and Android spawning remain unverified.

Native raid TLS must be included in client test preparation. PrizmManager
QuerySslVerifier (0x1B6EC08) selects None0, FingerPrintOnly1 or FullVerify2.
The inspected retained compatibility APK's Main serialized boot data uses
FullVerify with two SHA256 certificate fingerprints. SslVerifier.Validation
(0x1B17EE0) checks the leaf, then chain status/date validity and requires a
configured fingerprint match on the leaf or a chain certificate. The full
verifier rejects a leaf whose subject equals its issuer at0x1B18084/88.
A locally generated self-signed fixture certificate therefore does not establish
Android transport compatibility. API URL editing alone leaves these pins
unchanged. Client test packaging must preserve full verification and configure
the appropriate test-server certificate or chain fingerprint; no Android
handshake with that prepared configuration has yet been verified.

Native in-battle reconnect reuses the original HTTP transport credentials.
InGamePvEScene.reconnectingPhase_StartAsync (async body0x2E5EEF0) invokes
RejoinPrizmRoom at0x2E5EFE4. RejoinPrizmRoom (async body0x36A3CD8) reads
JoinedPrizmInfo at0x36A3D2C and calls JoinPrizmRoom with rejoin=true at0x36A3D38;
it does not obtain a new HTTP admission. JoinPrizmRoom invokes IPrizmManager
slot34 Connect with this Prizm instance at0x36A1C90, then sends the room Join
RPC at0x36A1D10. Consuming the TCP credential permanently on first connection
therefore prevents this path from authenticating after socket loss.

Runtime enables SessionRegistry reconnect mode. Credentials remain bound to
the admitted account/room/player and only one live session per account/room
is allowed. Closing a socket removes its session while retaining credentials
for a bounded reconnect window. Authenticated inbound activity extends that
window; outbound notifications do not. Explicit leave revokes credentials and
sessions together. Independent registry users retain single-use mode by
default. Tests cover concurrent replay rejection, expiry and revocation, plus
real verified-TLS reconnection after battle preparation, Join(rejoin=true),
unchanged prepared token/response and subsequent battle/completion with
preserved original account saves. These are fixture clients; Android recovery
and recovery after server process restart remain unverified.

Reliable status action command 20 (`0x1B61A28`), buff registration 29
(`0x1B61CFC`), removal 31 (`0x1B61DD4`) and command 33 (`0x1B61E60`) relay peer
commands 21, 30, 32 and 34. Dispatch checks registered object ownership and
optional admitted recipients, preserves signed hash/flag values and validates
native integer, sequence, finite-number, byte/string and bool field types.
Global buff registrations are retained by object GUID/IdHash, removed by
UnregisterBuff and cleared on object destruction; targeted messages do not
change the shared buff registry. These are client effect signals, not server
reward/progress authority. Actual status/skill semantics, recovery replay and
Android combat remain unverified.

Battle completion uses reliable RPC command 0 (`InGameServiceBase.GameOver`,
`0x1B61420`) and peer notification 1. GameOverNotification fields are Reason,
DamageResults, Complement and BossRecoveryTotal; GameOverReply returns
DamageResults and BossRecoveryTotal. Dispatch accepts only the current host,
checks damage-summary identifiers against prepared battle participants and
latches the first report. Identical retries return the same reply without
rebroadcast; conflicting outcomes are rejected. These remain host-reported
signals, not verified damage totals or persistent result authority.

RPC command 26 (`GameOverConfirm`, `0x1B61BF4`) accepts an empty map and returns
State and GameOver. Native InGamePvEScene.<GameOverConfirm>d__57.MoveNext
(`0x18A7A2C`, check at `0x18A7B8C`) invokes OnGameOver only for State OutGame
(1) with a populated GameOver. The emulator returns InGame (0) before a report
and OutGame (1) with the latched report afterwards. Native GameOverReason values
0..4 and signed damage/recovery integers are preserved. HTTP end/retire, reward
validation, post-completion cleanup and Android results remain unimplemented.

`pve_stats.py` implements the native base character level-curve calculation,
verified at `CalcLevelStatus.Character` (`0x342D2A4`): floor(base ×
(1 + scale × Levels[level−1])). Master scale is rounded to float32 before
widening to double, matching `CharacterStatusParam.get_HPBase` (`0x360F72C`).
CharacterBaseStats indexes installed character/curve tables and uses the saved
character level without writing or altering saved loadouts. All 21 characters
in the installed local user fixture resolve their curves and calculate; this
is base-stat validation, not a per-account playtest. Equipment aggregation, passive effects,
relationship/country modifiers, MP and total power remain required before this
can supply authoritative raid admission or battle totals.

EquipmentBaseStats implements `CalcLevelStatus.Equipment` (`0x342D37C`):
equipment scales remain doubles, levels beyond the curve clamp to its final
entry, and a positive override level takes precedence over the saved level.
Missing curves and nonpositive levels yield zero. HP uses the effect-value
curve, matching `EquipmentStatusParam.get_HP` (`0x351D054`); attack and defense
use their own curves. All 42 installed local equipment records calculate.
These are individual item stats; equipped-item ownership, subslot weights and
passive bonuses still require validation before producing battle totals.

`equipment_slot_total` applies the verified SubEquipmentCorrection of double
0.1 (`GameConfigParam..cctor`, store at `0x354F87C`). Main contributions are
summed unchanged; the combined subslot sum is multiplied and floored once,
matching `GetEquipmentPower` (`0x36102E0`) and `get_AccessorysHP`
(`0x360FDFC`). Callers must first resolve owned equipped items and the
appropriate category/stat contributions; this helper does not establish those.

Native character totals also differ by stat: `get_AttackTotal` (`0x360FEDC`)
adds CountryAttack to Attack, while `get_HPTotal` (`0x3610094`) adds truncated
HPBuff, AccessorysHP and CountryHP. Do not substitute the base curve output
for these totals. The current regression suite passes 161 tests; this does
not establish Android raid playability.

EquipmentLoadoutStats resolves saved WeaponMain/WeaponSub, Costume and
AccessoryMain/AccessorySub against an explicitly supplied owned-equipment
collection. Unknown or unowned equipped items are rejected without modifying
saves. It reproduces `get_Weapons`, `get_Costumes` (`0x360FCB4`) and
`get_AccessorysHP` contributions. Native equipment type classification
(`0x351CDC0`) uses category and BaseId: empty-base category 3 is accessory,
category 4 is attachment, wp001..wp007 identify weapons and pl identifies
costume. GetEquipmentPower uses defense for costumes, HP+attack+defense for
accessories, and attack otherwise. All 21 local saved loadouts resolve against
their local owned items. Passive and country bonuses remain separate.

`relation_stat_contribution` implements `CalcOutputParam` (`0x3610190`):
floor(local stat * 0.135) for Faction 3, otherwise floor(local stat * 0.08).
Both factors are native doubles initialized at `0x354F850` and `0x354F868`.
CountryAttack iterates related characters and applies this to each character's
Attack (not AttackTotal); CountryHP uses HPBuff plus accessory HP (not HPTotal).
Contributions are rounded individually before summing, preventing recursive
country bonuses. RelatedCharacters selects Type 1 entries from an account's
ordered IDs, excludes the target ID, and compares master Faction, matching
`HomeSceneUtility.GetRelationCharacters` (`0x32E3438`, comparison at
`0x32E36E0`). It requires selected entries to be owned and installed, rejects
duplicates, and preserves the input order without changing saves. Native UI
sorting is unnecessary for the integer contribution sum. Passive initialization
and account-provider integration remain required for complete raid stats.

Passive arithmetic is implemented by passive_effect_value and passive_stat.
`InputPassiveEffects` (`0x360F234`) resets bonuses and visits Costume,
WeaponMain and AccessoryMain in that order; subslots are excluded. Its overload
(`0x3610AB4`) sums each applicable effect multiplier minus one. Buff effect
values use SpLevel minus one and clamp beyond the last value
(`GetEffectValueD`, `0x2FCA860`); missing values or nonpositive levels yield
zero. AttackBuff floors base * (1 + combined bonus) once. Resolving installed
equipment buffs and their setup effect types remains necessary; these helpers
accept resolved values and do not fabricate absent passive data.

EquipmentPassives now resolves Buff lists from installed equipment masters
against installed buff IDs and each owned item's SpLevel. It visits Costume,
WeaponMain and AccessoryMain in native order, separates `magic:` entries as
`Equipment.setupBuff` (`0x176F9DC`) does, and selects Setup_HP, Setup_Attack
and Setup_Defense (verified in BuffEffectTypeHash initialization at
`0x19E7F10`). Missing equipment ownership or installed buff IDs fails without
save writes. All 21 local loadouts resolve their passive values. Complete stat
composition and account battle-provider integration remain required.

CharacterCombatStats now composes HP, attack and defense using these installed
tables and explicitly supplied account saves. Local attack adds Weapons and
AccessorysAttack to AttackBuff (`0x360FADC`); defense adds Costumes and
AccessorysDefense to DefenseBuff (`0x360FC58`); HP adds AccessorysHP to HPBuff
(`0x360FDC0`). Each related character contributes from its local stats once,
without recursively including faction totals. All 21 local fixture characters
calculate with equipment and passive effects. Account-provider integration,
MP and Android battle verification remain outstanding. CharacterCombatStats.power
returns total HP + attack + defense, verified at native get_Power (`0x361081C`),
and rejects totals outside signed int32 rather than issuing invalid admission
metadata. It does not use stale saved LastPower or client-provided power.

AccountCombatStats reads UserCharacter.json and UserEquipment.json through an
account-scoped read callback and obtains ordering through an account-scoped
provider. It returns computed HP/attack/defense/Power and rejects characters
not owned by that account. The caller must provide a consistent save snapshot
and a database connection appropriate to its thread. Runtime registration and
native battle response assembly remain outstanding. Native MaxMP
(`CharacterDataBase.get_MaxMP`, `0x342F248`) reads the initialized
IncreaseStatusInfo at object offset 0x50; its construction still needs tracing.

The two native SetStatus callers clarify MP ownership. UserDataManager.UpdateStatus
(`0x177B28C`) constructs IncreaseStatusInfo and sets Level, HP, Attack and
Defense only; its constructor (`0x3521F70`) does not initialize MP. The Prizm
CreatePrizmCharacterData path (`0x2FF44A4`) copies current HP and MP from
serialized CharacterData into the local character, then copies those same
values into IncreaseStatusInfo at `0x2FF4644` and `0x2FF464C`. Thus this path
uses the transmitted MP as MaxMP; it does not derive it from a level curve.
Trace the PvE start/player-data builder before choosing the transmitted SP
value. Zero-initialized normal status is not evidence that raids should start
with zero SP.

PlayUserCharacter carries CharacterId, Hp, Sp, Level and Exp (native offsets
0x10, 0x18, 0x20, 0x28 and 0x30). MakeDeckCharacters (`0x177A84C`) looks up
matching EpisodeDetailUser.playCharacters and, when its override flag is set,
copies Level and Exp into CharacterData at `0x177ADDC` and `0x177ADEC` before
calling UpdateStatus. Those loads are level/experience, not HP/SP. Raid start
assembly must account for any episode level overrides; current calculators
use saved levels. The HP/SP application path still needs verification.

CharacterCombatStats.character accepts explicit server-selected level_overrides
for owned characters. Overrides apply to detached rows before local and
related-character calculations, leave saved Level/Exp untouched, and reject
unowned IDs, invalid levels or levels beyond installed curves. These values
must come from the episode policy, not a client request. Default calculations
continue to use saved levels. Runtime response assembly must pass the same
levels that it publishes in PlayUserCharacter.
The account adapter and power method accept the same overrides, keeping
computed power consistent with battle stats. Every supplied override is
validated against installed curves, including owned characters outside the
selected faction contribution set.

BattlePlayer.MakeSetupParam (`0x2E4A194`) copies current HP/MP from
CharacterData and reads MaxHP/MaxMP from IncreaseStatusInfo. BattlePlayer.Setup
(`0x2E4A964`) then calls SetupBuff before clamping current HP/MP to maxima via
SetHPMP (`0x2E4AA68`). SetupBuff registers passive and startup buffs;
RegisterStartUpBuff (`0x2E4A3F4`) obtains the `StartUpBuffIdList` parameter
before registering those buff IDs. Starting SP therefore requires tracing
the character data and startup-buff values together; the pre-buff MaxMP
getter alone does not establish the final battle capacity.

startup_buff_ids resolves StartUpBuffIdList from character UniqueParamData
string-array parameters and requires each referenced buff to be installed.
All 41 installed character-master rows validate. Installed buffs include
Param_RepairSPGauge and Param_UseSPGauge, but no Status_MaxMP entries; MP and
skill-gauge capacity must not be assumed to be interchangeable. Startup
reference validation does not yet establish the transmitted raid SP value.

Player creation validates the authoritative CharacterData snapshot before
comparing client values: exactly ten numeric fields, strings, signed int32
Level/HP/MP, signed int64 Exp, and bounded string equipment/spell arrays.
Snapshots are detached. A matching client payload cannot make a malformed
server snapshot acceptable (for example bool Level or int32-overflow HP).
The first successful player creation stores a detached per-account
BattleCharacters snapshot in the room. Later duplicate or targeted recovery
requests use that snapshot instead of recalculating from potentially changed
account saves. Invalid creation requests do not freeze character values.
Production battle preparation must still derive the initial snapshot from the
same account state used for its HTTP start response.
When a character provider is configured, preparation now resolves every
member's CharacterData before freezing or broadcasting start. The provider
receives detached PreparedBattle responses so it can derive the snapshot from
the same start data. Invalid character fields leave both PreparedBattle and
BattleCharacters unset. Valid snapshots are committed with the start responses
and reused for object creation and recovery. Production providers still need
to be implemented and registered.

Native WrapperCreatePlayer.UpdateParam (`0x2FF9060`) refreshes CharacterData
HP and MP from the live BattlePlayer before recovery. Creation validation
therefore freezes identity, level, experience and loadout while allowing
current HP/MP from zero through the prepared snapshot limits. Object identity
comparisons exclude these two mutable fields. Recovery notifications carry
the submitted current values without replacing the frozen limits. These are
owner-reported state, not verified damage or reward authority; providers must
set limits that agree with the actual client battle initialization.
WrapperCreatePlayer.UpdateParam also refreshes position and rotation at
`0x2FF90CC` and `0x2FF90E4`. Player recovery identity comparisons exclude
these transforms as well as current HP/MP. Targeted resends therefore recreate
the object at its current location while retaining GUID ownership and the
frozen character/loadout fields. Transform values still require bounded native
field shapes and finite numbers.
Enemy recovery follows the same transform rule: native
WrapperCreateEnemy.UpdateParam (`0x2FF8EA4`) copies current position and
rotation. The server excludes these fields from fixed enemy identity while
still requiring the original GUID owner and authorized spawn UniqueId.
Targeted recovery notifications use the updated transforms.
Minion recovery likewise permits refreshed position/rotation, verified in
WrapperCreateMinion.UpdateParam (`0x2FF8F14`). Its GUID, parent owner GUID,
authorized spawn ID remain fixed. The virtual callback at `0x2FF9048` invokes
MinionSetupParamBase.UpdateFromMinion. Magic-decoy UpdateFromMinion
(`0x19A22C8`) copies current BattleMinion HP into its setup parameter;
CreateParam.DelayUpdateParam (`0x191E80C`) subsequently serializes that setup
through MakeParam. Recovery therefore permits changed HP in the known
magic-decoy JSON shape, bounded by its original MaxHP, while freezing MaxHP,
Base_LoadPath and AddPrefabInfos. Unknown parameter formats retain exact
equality, and each resend still requires the spawn provider's authorization.

`accounts.read_save_snapshot` opens an existing schema-4 database in SQLite
read-only mode and reads the requested account saves in one transaction. It
does not create or migrate databases. `SnapshotCombatStats.prepare` uses that
boundary to detach character/equipment saves plus any explicitly requested
ordering inputs. Its ordering resolver receives those same detached saves;
the returned account-bound stat provider can calculate multiple characters
without rereading live state. Level overrides operate on detached rows.
Production battle assembly must prepare once per participant and use the same
snapshot for HTTP start fields and transport CharacterData; it is not yet wired.
`tests/test_account_snapshot.py` exercises real SQLite persistence, reads during
an uncommitted WAL writer, cross-account rejection, and prepared stats remaining
unchanged after committed save edits.

Native `InGameScene.applySuspendData` (`0x2E61E10`) resolves the player matching
each PlayUserCharacter. At `0x2E62708` and `0x2E6270C` it reads SP/HP from
offsets 0x20/0x18, then calls BattleCharaBase.SetHPMP at `0x2E62714`.
The general phase_SetupFinished calls this at `0x2E65774`. Its internal
guard checks IUserDataManager.EpisodeDetailUser (interface slot 12), and the
player loop checks PlayCharacters at offset 0x38. There is no resume-only
flag around this loop: supplied start-response HP/SP are applied during
general setup completion as well. The call's ordering relative to the first
network player creation still needs verification for raid snapshot limits.
NotificationParam_CreatePlayer.CharacterData_ToPrizmObject (`0x2FF959C`)
copies current CharacterData HP/MP (offsets 0x48/0x4C) into transport fields
6/7 and copies visual equipment, costume spells and weapon spells from
offsets 0x68/0x70/0x78 into fields 8/9/10. It performs no stat calculation
or SP defaulting here. Production snapshot assembly must therefore match
the actual initialization path rather than select a default from serialization.

`CharacterDataBase.SetStatus` (`0x342F510`) stores IncreaseStatusInfo at
offset 0x50; it does not assign current HP/MP at 0x48/0x4C. The UserCharacter
constructor (`0x342E694`) copies saved level, experience and equipment/spells
after `init`, but likewise does not initialize HP/MP from combat totals.
`init` (`0x342F37C`) obtains these current values from CharacterInfo.Empty;
its static initializer (`0x342F5EC`) leaves that object's HP/MP zero.
UpdateStatus then calls SetupDebugStatus (`0x342F554`) at `0x177B3C4`.
Despite its name, this method unconditionally copies IncreaseStatusInfo HP/MP
into current CharacterData HP/MP at `0x342F560`/`0x342F574`. On this normal
path IncreaseStatusInfo receives calculated HP but no MP assignment, so
initial CharacterData contains calculated HP and zero MP. This supersedes
the earlier inference from SetStatus alone. PreparedCombatStats.initial_resources
models these pre-buff resources and respects episode level overrides.
BattleCharaBase.Setup (`0x2EDBCC8`) delegates to OverrideStatus
(`0x2EDBEA8`), which copies SetupParam HP/MP at offsets 0x1C/0x20
through SetRawHP/SetRawMP, and copies maxima separately at 0x24/0x28.
Thus base setup itself does not fill current values to their maxima.
CharacterDataBase.HealHPMP (`0x342F57C`) does perform that fill from
IncreaseStatusInfo. Direct native branch/call references in the installed
binary identify UserDataManager.AddExp (`0x177D21C`) as its sole caller;
fresh battle setup cannot be assumed to invoke it.
BattlePlayer.SetTempSaveStatus (`0x2E498E0`) separately restores integer
HP/MP via SetHPMP and float skill-gauge SP via set_SP (or an alternate gauge
controller). These fields have distinct storage and restoration paths.
PlayLogManager.GetEpisodeLog (`0x1905070`) calls BattleCharaBase.get_MP at
`0x19053AC` and stores its widened integer result in PlayLogCharacter.sp
at `0x19053B4`. The playlog's SP label therefore denotes MP, independently
of the separate float skill gauge.
The initial notification originates in PlayerManager.LoadParty's async
implementation (`0x3275294`): after player Setup (`0x3276DAC`), it passes
the party CharacterData at state-machine offset 0xF0 to the notification
constructor at `0x3276F70`, then invokes IGameNetworkManager interface slot15
(SendNotification_CreatePlayer) at `0x3277018`. This copies the CharacterData
input rather than refreshing it from BattlePlayer in this send path.
General scene setup completion applies response HP/SP later. The remaining
initialization question is therefore the HP/MP of the party CharacterData
before LoadParty sends, not a missing default in network serialization.
LoadParty's visual preparation callback (`0x326FBD8`) also falls back to
character-master UniqueParam VisualEquipments when the CharacterData visual
array is null; authoritative response assembly must account for this fallback.
LoadParty obtains those CharacterData instances via IUserDataManager interface
slot67, ForMainMemberWithPriorityMember (`0x32755F0`). Its implementation
(`0x177DC84`) resolves the existing character via FindCharacterData, invokes
the callback, and does not assign HP/MP. The notification constructor
(`0x2FF93E4`) stores the provided CharacterData reference at offset 0x28
without modifying its fields. PlayerController.Setup (`0x1866EF8`) delegates
to BattlePlayer.Setup at `0x186727C`; this call must not be mistaken for
a separate fill-to-maximum operation on the CharacterData being serialized.
PreparedCombatStats.battle_character now builds paired HTTP PlayCharacter
and numeric transport CharacterData from the same frozen saved row and
native-derived initial resources. Installed server policy must supply the
resolved master ID, character name and default visuals; browser/client
creation fields are not authoritative inputs. Null or shorter-than-two-slot
visual arrays use the supplied master fallback: native SetVisualEquipments
ignores these arrays, leaving LoadParty's fallback active. Null spell arrays
normalize to empty arrays. The transport validator checks all final fields.
Production master/presentation resolution and room-provider wiring remain
required before this helper is a playable raid start implementation.

PartyCharacterPresentation resolves normal party defaults from installed
Character.UniqueParamData's VisualEquipments string array, requiring installed
equipment references and returning detached values. MakeDeckCharacters passes
the selected ID as both CharacterID and MasterDataID (0x177AAC8/0x177AACC and
0x177ACA0/0x177ACA4); LoadParty's visual fallback looks up that CharacterID
(0x326FC28) and reads VisualEquipments (0x326FC70). The transmitted master ID
therefore follows the party ID after local costume replacement, which can
differ from the original lobby selection. The resolver currently supplies the constructor's null name;
later client assignment paths and production provider wiring remain to verify.

CharacterName is a nullable transport reference, not necessarily the character
master's display name. The UserCharacter constructor (0x342E694) and init
(0x342F37C) leave its backing field at offset0x28 unset; SetMasterData
(0x342F478) only stores the master reference. CharacterData_ToPrizmObject
(0x2FF959C) copies that reference unchanged. Native CharacterData.Write
(0x1B52450, name branch0x1B5289C) omits it in skip-default mode when null,
and otherwise emits field3 with nil. The server validator therefore supports
a null authoritative name and interprets omitted field3 as null, without
accepting a different client-supplied name. This establishes wire behavior;
it does not prove that no later client path assigns a name before creation.

BattleAssembler (pve_preparation.py) connects the snapshot and presentation
providers: each participant is prepared once, and paired HTTP playCharacters
and transport CharacterData come from that account-bound preparation. An
installed episode response builder must still supply episode/master details,
tokens and common battle identity; this builder must not persist progress or
publish tokens. BattlePreparation bundles both outputs for Rooms to validate
and freeze atomically. Invalid or missing bundled characters leave the lobby
unprepared. RoomService can create players from these frozen characters without
a separate live character provider. This assembly boundary is implemented;
installed episode response construction and production runtime wiring remain.

InstalledBattleResponses now composes the start envelope from an authorized
episode loader and installed character/visual/master definitions. Its account
fields come only from PreparedCombatStats, including UserItems.json (which
must be requested by SnapshotCombatStats.extra_saves). BattleAssembler supplies
one common BattleId; each member receives a distinct random EpisodeToken.
The loader must supply complete fresh-run episode defaults, enemy details,
time limit and music; the empty offline pve/start.json is not usable. The
installed-data loader and production runtime registration are still required.

RaidEpisodeLoader (pve_episode.py) reads explicitly catalog-mapped scenario
files and layout directories, independently of story battle-skip settings.
It preserves scenario order, rejects invalid/duplicate scenario identity and
numbers, and assembles enemy detail from own/child layout references. Installed
definitions still supply fresh-run user defaults, drops, time limit and music.
InstalledBattleResponses binds one detached episode definition to a battle
before preparing participants, preventing mixed file versions within a room.

RuntimeHost (prizm_host.py) owns Runtime on a dedicated event-loop thread and
returns the PvE HTTP adapter only after listener startup. attach_runtime is an
explicit startup hook, not automatic server registration. Shutdown revokes
control, waits for cleanup and reports failures; startup timeout cancels the
listener task. Loopback verified-TLS tests cover the actual Runtime lifecycle.
Production providers, event publication and server startup configuration remain
unassembled, and Android/two-client playability remains unverified.

The server entry point now supports explicit opt-in startup through
EMBLEO_PVE_CONFIG, an operator-owned Python Flask configuration file. It must
supply PVE_RUNTIME_FACTORY (constructing a fully configured Runtime),
PVE_BIND_HOST, PVE_BIND_PORT and PVE_TLS (a server SSLContext). Event publication
uses PVE_PUBLICATION; configured metadata/state feed user/top, event/list and
pve/list. Configuration/resources and account-state providers are not supplied
by this hook. Keep private hosting configuration outside the repository.
run_http starts transport before HTTP, disables the development reloader when
raids are configured, and clears the adapter/stops transport when serving exits.
Module import does not open listeners. Runtime remains disabled without this
explicit configuration, and installed provider assembly still needs work.

installed_battle_assembler loads character/equipment/buff/curve masters and
the normal episode master group from one installed data root. The curves and
buffs transmitted to clients are the same detached inputs used by the server
calculator; callers cannot substitute different statistical masters through
the optional supplemental group. Construction does not create/open player
storage. An isolated two-account installed-data exercise prepared the Easy
raid with unchanged database contents, but used diagnostic time/music/defaults
and therefore does not establish client-ready event configuration or gameplay.

PvE party setup supersedes the checkpoint's fixed party list for the local
player: InGamePvEScene.phase_SetupParty async0x18ADB48 obtains IPrizmManager
slot23 get_MyPlayer, reads AppPlayer.CharacterId at0x18AE050, and creates a
single-member party array. It looks up the owned UserCharacter through
IUserDataManager slot69 GetUserCharacter and, when found, passes it through
slot71 UserCharacterReplaceID (0x18AE1C4). It then calls slot33
MakeDeckCharacters with that party, an empty reserve, isDebug=true and
isFirst=false (0x18AE258..0x18AE270). Thus a pl001 checkpoint entry alone is
not evidence that all clients must play pl001. The replacement-ID mapping still
needs alignment with prepared CharacterData; this is not Android verification.

UserDataManager.set_UserCharacters (0x177979C) adds each original owned row
to its dictionary, then clones rows with a different UserCharacterReplaceID
(0x1779878). The clone's CharacterId becomes the replacement ID and its
BaseCharacterId becomes the original ID (0x1779884/0x177988C). The replacement
row therefore retains the owned level, experience and loadout. get_BaseCharacterId
(0x17774B0) falls back to CharacterId only when that stored reference is null.
UserCharacterReplaceID reads the first visual equipment's ReplaceCharacterId
at equipment offset0xC0; the prefab-name getter reads this same field. These
are not separate replacement criteria. MakeDeckCharacters looks up the cloned
row using the replaced party ID and passes that ID as both CharacterID and
MasterDataID. UpdateStatus resolves that master before CreateStatusParam.
The installed assembler resolves the first saved visual equipment through its
installed replacement master, clones the owned row for calculation and keeps
the original HTTP UserCharacter save list unchanged. CharacterData and the
HTTP PlayCharacter use the same resolved ID, level override, experience and
resources. BattlePreparation supplies an account-scoped pair of original lobby
selection and resolved battle ID; Rooms requires both to match its candidate
and frozen transport character before accepting the paired response. Legacy
preparations without this mapping still require the original ID. Identity
collisions and missing replacement masters reject before freezing battle state.

The related-character callback CreateStatusParam.b__138_1 (0x177E25C)
skips owned replacement clones (0x177E350/0x177E354), the target ID and
the target's BaseCharacterId (0x177E380/0x177E390), then compares faction.
RelatedCharacters now applies these exclusions when receiving cloned rows;
otherwise the replacement could receive its own base character's contribution.
The original saved rows remain unchanged. A regression checks the original
and replacement targets alongside another character and its replacement alias.
The applySuspendData player predicate (0x2E62B7C) compares the battle player's
CharacterId field at0x48 against PlayCharacter.characterId, not its separate
BaseCharacterId getter. This is evidence that restoration must follow the
actual battle identity rather than blindly retaining the lobby selection.

The downloaded episode response supplies the scene's per-episode master data.
DownloadManager.StoreEpisodeMasterData builds StartEpisodeInfo and calls
StartEpisodeHelper.StoreMasterDataFromStartEpisode. Its async body
(0x2F2DBCC) uses the explicit episode ID when nonempty and invokes
IMasterDataManager slot56
at0x2F2E120: StoreResponseEpisodeData(episodeId, detail, detailUser,
baseVisual, staticItemExtras, fieldCoinCounts, episodeMasterGroup).
MasterDataManager.StoreResponseEpisodeData (0x2EFFCA8) retains that ID in x22,
gets or creates its episode cache at0x2EFFD18, stores scenarios at0x2F0006C,
and builds enemy and stage-event tables from the supplied layout at0x2F002AC
and0x2F003C0 using the same ID. PvE setup subsequently reads those per-episode
tables. An HTTP episode ID therefore need not equal the installed layout or
scenario file name; RaidEpisodeLoader keeps these mappings explicit. This
trace establishes response-to-cache binding, not successful Android scene
entry or absence of other global-master requirements.

Android startup refreshes the configured event with GET
`/api/pve/list?eventId=...`, then GET `/api/pve/reward-list?eventId=...`.
The event and read-only room routes accept native camelCase query fields;
room discovery parses Difficulty as a bounded decimal integer. Duplicate
query values and malformed difficulty reject. MessagePack POST remains
supported, and room mutations remain POST-only.

PveRewardListResponse contains Mission, MissionMaster, GuildMission and
GuildMissionMaster arrays. EventPublication.reward_list uses an explicit
account/event provider after publication and account-state validation,
returns detached configured collections and performs no settlement or grant.
An absent provider returns an unavailable response instead of inventing
missions. The isolated no-reward trial explicitly configures four empty
collections; production mission and guild reward policy remains separate.

Android event-detail initialization indexes one `EpisodePveEvents` entry for
 each difficulty button. Publish the complete ordered difficulty set required by
 the installed page; a single-entry diagnostic event triggers an index error
 before room discovery. The native create request places the selected
 `EpisodePveEventId` in its `EpisodeId` field. HTTP admission and start resolve
 that link identity to the installed scenario, rejecting identities that collide
 across scenarios. Schedule and account eligibility still use the installed
 scenario identity.
