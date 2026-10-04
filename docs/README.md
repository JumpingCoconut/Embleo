# Embleo Documentation

This folder contains reusable project and game-data knowledge for contributors. Prefer topic references that explain a durable data model, code path, or verification workflow. Keep one-off test results in the relevant issue or change description; promote a finding here when it generalizes to future work.

When documenting behavior, distinguish verified code/data facts from inferred game semantics. Include the owning source path and a way to verify changes. Avoid treating a value observed in one episode or asset version as a universal rule.

## Project And Data

- [Accounts and Saves](Accounts%20and%20Saves.md): client identity, per-player storage, profiles and verification.

- [Sequence Master Data](Sequence%20Master%20Data.md): combat sequence structure, adapter behavior, and safe editing workflow.
- [Sequence Master Data Further Information](Sequence%20Master%20Data%20Further%20Information.md): adapter details, ownership, and editing workflow.
- [Errors](Errors.md): known errors and troubleshooting notes.
- [Server News](Server%20News.md): setup welcome notice, built-in sprite pictures, and atlas discovery.

## Episode Systems

- [Episode Gimmicks and Scenario Progression](episode/Episode%20Gimmicks%20and%20Scenario%20Progression.md): layout state, scripted gimmick operations, and battle-skip behavior.
- [Checkpoint and Save System](episode/checkpoint%20and%20save%20system.md): episode checkpoints and save handling.

## Other Game Systems

- [Level Up Camp](Level%20Up%20Camp.md)
- [Daily Rewards](calendar/Daily%20Rewards.md)
- [Events](calendar/Events.md)
