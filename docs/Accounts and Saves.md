# Accounts and Saves

## Identity and client evidence

The original client's native `Colopl.Net.ApiHandler.SetAccessTokenIfExists` reads the response `Authorization` header. `HandleBeforeSend` sends that token as `Authorization: Bearer <token>`. `App.NetworkManager.HandleResponse` saves it in `Colopl.CryptoPrefs` under `Token`; account detection checks that saved token. The partial C# decompile supplies contracts; native instructions establish these behaviors.

`POST /api/user/register` creates an account and returns an opaque bearer token in that header. `/api/user/login` resolves the token and returns the saved user and nickname. A nickname, Android ID, advertising ID or registration `Complments` field is not used as a credential. Duplicate nicknames remain separate accounts. Server-generated IDs and player codes are independent of the nickname.

Requests marked anonymous by the original API constructors remain available before registration: provision, heartbeat, anonymous action logging, terms URL and anonymous server messages. Player endpoints require a valid token. Original account-transfer and Bandai Namco linking operations are unavailable. There is no password login or custom recovery UI; losing the client token currently loses access to the account.

## Storage and profiles

`src/accounts.py` stores accounts, hashed tokens, JSON-shaped save records and PNG icons in SQLite. Each request commits successful changes together or rolls them back on failure. Existing server save handlers resolve their player records through the authenticated account. Shared master data stays shared.

The default database is `src/data/user/top/accounts.sqlite3`; `EMBLEO_ACCOUNT_DB` overrides it. Back up the database using SQLite's backup facility or with the server stopped. Keep its directory persistent across rebuilds. Legacy shared JSON files and `checkpoint.txt` are neither imported nor used for player saves. New accounts receive generated defaults from the existing game-data generators. Setup no longer generates a shared player save.

Saved state includes the user identity/name, user parameters, characters/loadouts, equipment, items, episode progress, checkpoints, balances, presents and player settings. This preserves the existing gameplay handlers' behavior; it does not implement missing rewards or progression rules.

The original `UserChangeViewParamRequest` contains `Word`, `FavoriteChrId` and `EmblemId`. `/api/user/change-view-param` persists those fields and returns the existing response shape. The selected character portrait comes from client assets. The wire field is `FavoriteChrId`, rather than the old seed's `FavouriteChrId` spelling.

The client also has a separate rendered-icon path: `CharacterIconCapture` encodes a PNG as base64, and `/api/character-icon/upload-icon` accepts its `Icon` string. The server validates and stores the PNG, returning `IconUrl`. Other-user views expose that URL, or null so the client uses its character portrait fallback. URLs include an image revision to avoid stale cached images. Dimensions come from the uploaded PNG rather than an assumed 128-by-128 size. Android rendering still requires an in-game check.

## Scope and remaining work

| Feature | Current state | Next step |
| --- | --- | --- |
| Identity, profiles, saves | Persistent per account | Verify client registration/token restoration and gameplay |
| Character portrait selection | Favorite character saved | Verify visible portrait after restart |
| Uploaded rendered icon | Stored and served as PNG | Verify client display and upload flow |
| Other-user lookup | Real account ID or player code | Connect social flows as implemented |
| Chat, episode comments/likes, guilds/messages | Existing fixtures or incomplete handlers | Implement account-owned records using original contracts |
| Emoji/stamps | Existing client resources/contracts | Persist selections/messages with social features |
| Raids | Placeholder | Leave dummy for now |
| Purchases | Disabled; no purchase gifts created | No payment integration planned |
| Official account linking/transfer | Unavailable | No official service integration planned |

The old administrator JSON save editor does not edit this database. It needs a separate account-aware update before it can manage these saves.

## Verification

Run `python -m unittest discover -s tests -p test_accounts.py`. Tests cover separate accounts, token restoration, profile/loadout persistence, checkpoint transactions, PNG round trips and disabled purchases.

For an Android playtest, register once, change your nickname and favorite character, restart the game, and verify both remain. Reach a checkpoint, exit and restart, then continue the episode. Use a second emulator/device with separate app data to register another account and verify it starts with independent defaults. Restart the server and repeat login/continue for both. Do not clear the first device's app data: its stored token is the current credential.
