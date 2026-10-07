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

A TCP-first local Prizm emulator is therefore a plausible first prototype,
using the client's negotiated fallback. This is an implementation inference
from the native path, not a tested compatibility result. Omitting UDP simply
takes a different early-return path and is not proof of a working fallback.
No original Prizm backend has been shown necessary to reproduce the protocol;
no compatible replacement is implemented in this repository yet. Preserve
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

## Verification

From the repository root, use the project's Python environment:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_multiplayer.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_accounts.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_social.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_profiles.py
```

Tests cover schema preservation/rollback, conversation isolation, unread state,
blocks, message likes, membership permissions, applications, batch rollback,
concurrent admission, capacity, cursor precision and explicit raid unavailability.
These establish server behavior. Android UI compatibility still needs a
two-account playtest; no transport/battle compatibility is claimed.
