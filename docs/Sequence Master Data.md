# Sequence Master Data

## Scope

`src/data/extract/masterdatadebug/SequenceMasterDataObject.json` is a Unity-serialized combat sequence database. It describes character and enemy attack clips, movement, and per-sequence parameter overrides. It is not episode progression data: it has no episode IDs, episode gimmick IDs, scenario numbers, or gate statuses. Ana-Maria's Chapter 4 gates come from episode gimmick and scenario master data instead.

This reference describes the extracted file and the adapter in `src/scripts/adapt/master_data/sequence.py`. Counts below describe the current local extraction and can change when game data is refreshed.

## File Shape

The root object contains Unity metadata (`m_GameObject`, `m_Enabled`, `m_Script`, `m_Name`) and four data members:

| Member | Current shape | Purpose |
| --- | --- | --- |
| `attackList` | 30 wrappers; 479 settings | Attack definitions, grouped under `AttackSetting` |
| `moveList` | 29 wrappers; 387 settings | Movement definitions, grouped under `MoveSetting` |
| `updateParameterList` | 20 wrappers; 876 settings | Per-sequence parameter overrides, grouped under `UpdateParameterSetting` |
| `noUse` | Integer (`1`) | Present in the source; runtime meaning unknown |

Each wrapper has one category key whose value is an array of settings. A setting is commonly identified by `id` and `sequenceName`. In this extraction, IDs containing `pl` are treated as character IDs; other IDs are adapted as enemy IDs. This is the adapter's substring-based convention, not a universal type system.

## Setting Types

### Attack

An `AttackSetting` contains:

| Field | Meaning |
| --- | --- |
| `id` | Character or enemy sequence owner |
| `sequenceName` | Action/animation sequence key |
| `baseInfo` | Sequence-wide behavior and targeting modifiers |
| `totalClipCount` | Declared clip count |
| `clipCount` | Additional count data; often empty in observed records |
| `clipDatas` | Per-clip data, including hit settings and action-specific payloads |

`baseInfo` fields in the current data:

| Field | Interpretation |
| --- | --- |
| `ChargeType` | Charge behavior/type enum; values are not defined here |
| `IsInvincible`, `IsSuperArmor`, `IsArmor`, `IsStrongAttack`, `IsFloating`, `IsForceDamageAction`, `NoSetTarget`, `IsForceMultiTarget`, `KeepExistTarget`, `IsWeakInvincible` | Boolean-like behavior switches stored as integers |
| `SearchDistance`, `ValidSearchLayerDistance` | Target-search distance controls |
| `OffsetFront`, `OffsetSide`, `OffsetRear` | Directional targeting offsets |
| `PriorityType`, `PriorityFlag`, `ServiceFlags` | Priority/service enum or flag values; definitions are not included |
| `DamageCutRate` | Damage-cut modifier; precise formula is not defined here |
| `MultiTargetKey`, `BuffKey`, `ActionUniqueKey` | Keys associated with multi-target behavior, buffs, or unique actions |

Each `clipDatas` item has a `hitSetting` object and typed payload slots. `hitSetting` contains `HitStopPower`, `HitStopTime`, `HitStopFlag`, `AttackShakePower`, `AttackShakeTime`, and `IsForceAttackShake` (hit pause and shake controls, inferred from the names).

The action payload slots include `clip_Attack`, `clip_Gun`, `clip_DeathBall`, `clip_Summon`, `clip_Laser`, `clip_ThrowWeapon`, `clip_HomingGun`, `clip_Charging`, `clip_Grenade`, `clip_PutShoot`, `clip_LookGun`, `clip_Plunging`, `clip_MinionOrder`, `clip_MinionAttack`, `clip_MinionDecoyBomb`, `clip_SpecialSkillMagic`, `clip_RegisterBuff`, and `clip_AreaGuard`. Enemy-oriented slots include `enemy_Hit`, `enemy_ColliderHit`, `enemy_Throw`, `enemy_LinkThrow`, `enemy_AdditionalLinkThrow`, `enemy_Intermittent`, `enemy_Laser`, `enemy_Grab`, and `enemy_CatchAttack`; `general` is also present. These are typed slots, not a promise that every slot is active for every clip.

Common payload fields include:

| Field/group | Interpretation |
| --- | --- |
| `ClipIndex` | Clip index within the sequence |
| `AttackDamageRate`, `DamageRate`, `AddDamageRate` | Damage modifiers for the containing attack/effect |
| `AttackCenter`, `AttackRadius`, `AttackSize`, `AttackDirection` | Hit-volume position, size, and direction controls |
| `ReactionType`, `BlowAwayRate`, `StunTime`, `StrongAttack`, `ForceReaction` | Hit reaction and knockback controls; enum values need external definitions |
| `HitSE`, `HitEffect`, `EffectPath`, `EffectName` | Sound/effect resource references |
| `MainAttribute`, `CriticalRate`, `BadStatusList`, `BuffKey` | Damage attribute and attached status/buff controls |
| `IsNoDamage`, `IsNoReactionDamage`, `IsIgnoreGuard`, `IsForceHit` | Boolean-like hit-resolution switches |
| `Delay`, `Interval`, `IterationNum`, `Duration`, `LifeTime` | Timing/repetition controls in applicable projectile or sustained-effect payloads |
| `Offset`, `Direction`, `Scale`, `Rotate` and vector-valued members | Spatial values; vectors are objects with `x`, `y`, and `z` components |

Payloads contain additional specialized fields. Projectile, laser, and throw slots include trajectory, homing, lifetime, collision, effect, and target-selection controls. Enemy hit slots include damage, hit reaction, guard, and hit-history controls. Interpret a field in the context of its containing payload; the same name in two payloads is not guaranteed to have identical behavior.

### Movement

A `MoveSetting` contains `id`, `sequenceName`, `totalMoveCount`, `moveCount`, `direction`, and `speed`. `direction` is an array of `{x, y, z}` vectors; `speed` is an array of numeric values. `moveCount` holds per-step values. The arrays correspond by index in observed records, but units and value codebooks are not supplied.

### Update parameters

An `UpdateParameterSetting` contains `id`, `sequenceName`, `totalClipCount`, `clipCount`, and `clipDatas`. Its clip entries use:

| Field | Purpose |
| --- | --- |
| `attackBaseInfo` | Same base parameter set as `AttackSetting.baseInfo` |
| `clip_SpecialSkillMagic` | Special-skill clip index and buff list |
| `clip_EnemyReceiveDamage` | Incoming damage modifier and guard switch (`DamageRate`, `IsGuard`) |

These settings adjust combat behavior; they do not describe episode map gimmicks or chapter progression.

## Reading Values Safely

- Integer fields named `Is...` are generally boolean-like, but preserve their original values unless the client enum is verified.
- Integer fields such as `...Type`, `...Flag`, `...Attribute`, and `...Direction` are enums or bit fields until proven otherwise. This JSON does not define their numeric codebooks.
- Floats are raw game parameters. Units, coordinate spaces, clamping, and multiplier-vs-absolute semantics are not documented here; use the containing field name and verified runtime behavior, not magnitude alone.
- `totalClipCount`/`totalMoveCount`, `clipCount`/`moveCount`, and the data arrays are separate source fields. Do not assume their lengths always match: observed `clipCount` arrays can be empty while `clipDatas` is populated.
- Empty/default payload slots are structural alternatives. Their presence does not imply that the slot participates in that attack.

## Adapter Output

`adapt_debug_sequences_master_data` combines the top-level category lists and writes `CharacterSequenceMasterData.json` and `EnemySequenceMasterData.json`. It creates one adapted row per wrapper (normally one owner/category), not one row per `sequenceName`. Each row contains `CharacterId` or `EnemyId`, `Category`, and `Data`. `Data` is a JSON-encoded string containing the original category wrapper and its settings, rather than a normalized nested object. The adapter splits character from enemy records using the `id` substring check and sorts each output by owner ID.

## Relevance To Episode Gates

Do not edit this Sequence file to open an episode gate. Gate initialization is assembled from `EpisodeGimmickMasterDataObject.json` into `EpisodeDetail.LayoutGroup`; scenario-time state changes come from the adapted episode scenario's `Gimmicks` operations. Those scenario operations are transitions at specific progress IDs, not copies of initial layout state, and should retain their authored `Status` and `Flag` values.