# Accounts and Saves

## Running locally

Accounts are enabled for the whole server. Run the existing setup and server scripts; no separate database installation or opt-in setting is required. Python includes SQLite support.

The default database is `src/data/user/top/accounts.sqlite3`. Set `EMBLEO_ACCOUNT_DB` to use another file location. The database directory must be writable and persistent. Shared legacy JSON saves and `checkpoint.txt` are not imported or used for player state.

Opening the database automatically initializes its tables. Schema version 3 is recorded in SQLite's `PRAGMA user_version`. Unversioned, version 1 and version 2 databases are upgraded while preserving accounts, saves, tokens, icons and existing activity/history. Version 2 adds login history and last activity; version 3 adds directed follows and blocks. Migration does not invent historical logins or relationships from old counters. Initialization runs in one transaction under a write lock. A database with a newer unsupported version is rejected without alteration. Older servers cannot open version 3 databases.

## Account identity

`POST /api/user/register` creates an account and returns its bearer token in the response `Authorization` header. The original client's `Colopl.Net.ApiHandler.SetAccessTokenIfExists` reads that header; `HandleBeforeSend` sends the token as `Authorization: Bearer <token>`. `App.NetworkManager.HandleResponse` stores it in `Colopl.CryptoPrefs` under `Token`. Account detection checks the saved token.

`/api/user/login` resolves the bearer token and returns the saved user and nickname. Nicknames, Android IDs, advertising IDs and the registration `Complments` field are not credentials. Duplicate nicknames belong to distinct accounts. Account IDs and player codes are generated independently of the nickname. Only token hashes are stored on the server.

Anonymous startup routes remain accessible before registration: provision, heartbeat, anonymous action logging, terms URL and anonymous server messages. Player-data endpoints require a valid token.

There is no implemented account-recovery flow. Clearing app data or losing the client token removes access to that account. Official account linking and transfer endpoints are unavailable; the server does not integrate with Bandai Namco accounts.

## Save storage

`src/accounts.py` stores account identities, hashed tokens, JSON-shaped save records and PNG icons in SQLite. Records are keyed by account ID. Existing gameplay handlers access player records through the authenticated request; shared master data remains independent of accounts.

A request owns a transaction. Successful requests commit their changes together; failed requests roll them back. Write transactions are serialized to prevent concurrent read-modify-write requests from losing updates.

The saved records include:

- User identity and nickname.
- `UserParameter`: mission rank/EXP, currencies, profile comment, favorite character, emblem and other existing parameter fields.
- Characters and loadouts, equipment and items.
- Episode state and checkpoint positions.
- Balances, presents and player settings.

New accounts receive defaults from the existing game-data generators. Persisting these records does not implement missing reward, progression or social rules.

## Player-data endpoints

| Endpoint group | Account-owned data |
| --- | --- |
| User registration, login, info and top | Identity, nickname and the account's saved records |
| Name and view-parameter changes | `User.json` and `UserParameter.json` |
| Character updates | Existing character loadouts; level and EXP remain server-owned |
| Episode list and chronology | `UserEpisode.json` combined with shared master data |
| Episode start and continue | The account's checkpoint position |
| Episode checkpoint and reset | Checkpoint positions and episode status |
| Episode retire and reward-result payloads | Current account parameters, characters, items, equipment and balances |
| Present list, history and receive | The account's presents; reward application remains incomplete |
| Billing list | Account settings and balances; purchasable products are disabled |
| Other-user info | Explicitly requested account profiles, looked up by ID or player code |
| Friend follow, unfollow, follower removal, block/unblock, list and search | Persistent relationships; counts and viewer-relative profile flags derived from SQLite |
| Rendered-icon upload | The authenticated account's icon |

Authentication does not make fixture-backed routes fully functional. Cooking-market purchases, gacha rewards, calendar rewards, missions and social endpoints still contain incomplete gameplay behavior. They must not be treated as a complete economy or progression implementation.

## Profiles and images

### Follows and blocks

`src/accounts.py` stores directed account pairs in `follows` and `blocks`, with foreign keys, uniqueness constraints and indexes for both directions. `FollowCount`, `FollowerCount` and `BlockCount` are calculated whenever account parameters are loaded for game responses, so stale saved counters do not determine relationships. `IsFollow`, `IsFollower` and `IsBlock` are calculated relative to the authenticated viewer in every profile response.

The existing client API contracts are implemented as follows:

| Endpoint | Behavior |
| --- | --- |
| `/api/friend/follow` | Add outgoing follows; duplicate follows are harmless |
| `/api/friend/follow-release` | Remove outgoing follows |
| `/api/friend/follower-release` | Remove incoming follows without removing the caller's outgoing follows |
| `/api/friend/block` | Add an outgoing block and remove follows in both directions |
| `/api/friend/block-release` | Remove only the caller's block; previous follows are not restored |
| `/api/friend/list` | Return `FollowUsers`, `FollowerUsers` and `BlockUsers` as current profile views |
| `/api/friend/search` | Exact lookup by account ID or player code; return `User` and `Users`, or null/empty when absent |

Mutations accept `targetUserIds`; search accepts `searchId`. Mutations are authenticated POST requests with at most 32 targets per batch. Missing players, malformed targets and self-targeting are rejected; duplicate targets are processed once. A failure rolls back the whole batch. Follow requests are rejected if either account has blocked the other. A player cannot remove another player's block. These block semantics are emulator policy, not a claim about recovered official rules. No total follow cap or mission rewards are implemented. Profile equipment/items and incomplete messaging remain unchanged; blocking currently enforces follow relationships rather than a full social system.

Verify with `python -m unittest discover -s tests -p test_social.py`, alongside `test_accounts.py` for existing save and authentication behavior.

Successful registration and login requests append account-owned records to SQLite's `login_history` table. Registration entries have `source=register`; subsequent logins have `source=login`. Each record contains `logged_in_at`, the latest `last_action_at` observed after that login, and a nullable `logged_out_at`. Authenticated registration retries do not append login events. Failed requests do not append events or advance activity. These records contain account IDs, not tokens, and are not exposed through public game APIs.

Every successful authenticated API request updates `account_activity.last_action_at`. Other-user `IsLogin` means activity occurred within `ONLINE_TIMEOUT_SECONDS` (300 seconds by default), or the profile belongs to the current requester. `LastLoginAt` comes from the most recent recorded login/registration. Old accounts without a recorded login retain the epoch fallback until their next login.

There is no recovered logout API, so `logged_out_at` remains null. Inactivity is an approximation of going offline, not an observed logout. A player who remains in offline gameplay or an idle screen may appear offline. The general `/api/game/heartbeat` has no account identity in its request contract and disables client authorization; anonymous/public requests do not refresh account activity. The recovered profile UI directly reads `UserView.IsLogin`; it does not calculate online status from `LastLoginAt`.

Noble membership is enabled for every account in responses. `UserParameter` receives a start in 2000 and an end ten years beyond the current response time; profile views receive the matching dates. The end moves forward on subsequent requests, so there is no purchase or renewal requirement. Existing saves are not rewritten to grant membership. This supplies membership dates, not otherwise missing premium gameplay rules.

`/api/user/top` derives available emblems from the installed `data/extract/manifest.json` using `profiles.py`. Every matching emblem asset is provided as usable, with its asset resource path and category 2 (Wappen). Native `updateUserStampBadge` routes category 2 into the emblem list; category 0 from the old fixture is not a valid emblem category. Sorting and grant metadata use emulator defaults because official badge master metadata is not installed. Unrelated stamps and deck data are preserved. If the manifest is absent or has no matching assets, the existing fixture remains the fallback. The asset inventory stays local; no extracted asset list is checked into source.

`/api/user/change-name` saves the nickname. `/api/user/change-view-param` saves `Word`, `FavoriteChrId` and `EmblemId` in `UserParameter`, using the original request/response contract. Fixed character portraits are client assets; favorite-character selection is represented by `FavoriteChrId`.

The client also has a rendered-icon path. `CharacterIconCapture` encodes a PNG as base64 and `/api/character-icon/upload-icon` accepts the `Icon` field. The server validates the image, stores its original bytes and returns an absolute `IconUrl`. Image dimensions are read from the PNG, with a maximum of 1024 by 1024 pixels. Eight-bit RGB/RGBA, noninterlaced PNGs are accepted.

`/account-icons/<account_id>/<revision>.png` serves the stored image. Its revision is derived from the image content. Other-user views expose `IconUrl`, or null so the client uses its character-portrait fallback. Other-user lookup accepts an account ID or player code.

## Multiple server instances and backups

All instances that should share accounts must be configured to open the same persistent database. Sharing is a hosting configuration, not a requirement for local installations. The server has no Main/Dev-specific storage logic and does not copy or synchronize separate databases.

SQLite file sharing requires a single host with working filesystem locks. Keep the persistent directory outside disposable container filesystems and mount it into each instance. Every instance must support the database schema. This implementation does not support sharing SQLite through network storage across multiple hosts.

Back up the database with SQLite's backup facility or while every server using it is stopped. Replacing or restoring the file requires stopping all users of the database. A container rollback must retain the current database and use a compatible server version; restoring an older database also restores older player progress.

## Current feature scope

| Feature | Implementation |
| --- | --- |
| Identity, profiles and saves | Persistent per account |
| Favorite-character selection | Saved in `UserParameter`; fixed portraits supplied by the client |
| Rendered icons | Validated PNG upload, storage and serving |
| Emblems | All matching installed manifest assets supplied to everyone; no individual unlock requirements |
| Noble membership | Always enabled in account parameters and profile views |
| Login history and presence | Recorded successful logins and last authenticated activity; online status inferred from recent activity, no observed logout |
| Other-user lookup | Account ID or player code |
| Follows and blocks | Persistent directed relationships, derived counts/flags, lists and exact player search |
| Chat, episode comments/likes, guilds and guild messages | Fixtures or incomplete handlers; no complete persistent social system |
| Emoji/stamps | Existing client resources/contracts; no complete persistent messaging system |
| Raids | Placeholder |
| Purchases | Disabled; purchase attempts do not create gifts |
| Official linking and account recovery | Unavailable |

An administrator editor must select an account and edit its database save records. Editing shared JSON files does not affect account saves. News is independent of the account database.
