Level Up Camp is handled separately from episodes by pinging `api/training-mission/` during loading.

To make Level Up Camp tile appear, add orderdId to user/top with MasterDataId - "LvUpCamp" and Type of 99 (Abstract).

To make levels selectable `api/training-mission/list` needs to be populated with three levels (from "exp_mission_001" to "exp_mission_006"). Adding more than three will confuse the game, but stages are interchangable and can be present in any order, not specifically 001-003 or 004-006.

Only one Level Up Camp tile can be present in the main menu.

Stage ID that is put into "LocationId" in TrainingMissions list is not the location that the game loads, but is used only for displaying the area name on the buttons.

`DISABLE_LEVELUPCAMP` in `src/server.py` controls the menu tile and defaults to `False`.
The installed asset manifest supplies checkpoint/enemy/gimmick layouts for all six
training missions, but no scenario asset. `training_mission.checkpoint_scenario`
uses the same initial checkpoint bootstrap as secret missions, with the checkpoint
ID and starting scenario number taken from the selected installed layout. An
authored scenario, if present, takes priority. Ordinary episodes still require
their scenario files.

The start response uses the selected owned character and saved equipment, level
and experience, plus HP from the existing native combat-stat calculator. The
checkpoint party is replaced with that selected character. The mission keeps the
existing server's five-minute training settings and the selected stage identity.
These paths use setup's normal installed data and need no Docker-specific files.

Camp startup also builds its party directly from `CharacterDetail.Characters`:
the native `SecretMissionManager.<RequestLvUpCampStartApi>d__172.MoveNext`
(thunk RVA `0x1690E88`, body `0x2F62BCC`) selects each appearance's CharacterId
into its party array at `0x2F637A4`–`0x2F638F0`; the selector at `0x2F5DF28`
returns that ID. This list must contain only the selected character, rather than
the entire character master list starting with Leo. Checkpoint `PartyPlayers`
and `LoadPlayers` must also retain the selected character. Both scenario-list
and scenario-group assembly use the shared `load_adapted_episode_scenario`
helper, whose bootstrap condition handles `sc` and `exp` mission IDs.

Camp finish conditions use the native `SecretMissionFinishType` values: `Dead`
(1, failure flag 1), `Killed` (3, success flag 0), and `TimeIsUp` (2, failure flag
1). `None` (0) is ignored and cannot finish a battle. Native
`SecretMissionManager.StartMission` accumulates each installed enemy's
`AppearanceNum` into `_defeatTargetNum` at `0x17EE298`–`0x17EE2A8`.
`CheckMissionEnd`'s Killed branch at `0x17F108C`–`0x17F128C` compares the native
`IPlayLogManager.GetMissionKillCount()` against that total, covering future waves
without a guessed group ID or kill count. `GetJudgment` at `0x17F2474` reads
failure flag bit 0. The death, kill and timeout branches do not use `Option`.

End and retire return current account state and zero added experience. Training
playlog rewards and XP settlement remain unimplemented; these responses do not
modify saves. The signed mission token binds the selected character to the
authenticated account and stage. Tokens are valid for the current server process;
a server restart requires starting a new training battle.

Run `python -m unittest discover -s tests -p test_training_mission.py` from the
repository root. These checks cover response assembly and preservation of saved
state; Android gameplay still needs verification.
