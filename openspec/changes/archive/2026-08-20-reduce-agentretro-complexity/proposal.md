## Why

AgentRetro's safety-critical paths are concentrated in five modules totaling more than 8,500 lines, with CLI dispatch, SQLite migration/purge persistence, synchronization, semantic merge, and purge recovery combining orchestration with low-level mechanics. The value-loop and CI changes are now merged and archived, so this is the right point to reduce change risk without mixing the refactor into product behavior work.

## What Changes

- Add characterization and architecture checks for the existing CLI envelopes and exit codes, SQLite schema/migration/transaction boundaries, projection synchronization, merge confirmation, and purge recovery behavior.
- Split CLI parsing/bootstrap from command-family dispatch while preserving `retro` arguments, JSON and human output, recovery commands, and existing test seam compatibility.
- Extract SQLite schema/migration and purge-journal persistence responsibilities behind the existing `SQLiteRetroRepository` public import and port behavior, preserving the database schema, backup-first migration, locking, transactions, and row ordering.
- Extract focused, internal helpers from synchronization, semantic merge, and purge services so orchestration methods express state transitions while filesystem validation, plan serialization, manifest comparison, locking, and recovery mechanics have explicit owners.
- Add a scoped complexity regression gate for the refactored AgentRetro modules so the decomposed entry points do not silently grow back into monoliths.
- Preserve all public commands, Python service/repository entry points, persisted formats, audit/projection semantics, security boundaries, and dependencies; this change is not a feature or data migration.

## Capabilities

### New Capabilities

- `agentretro-maintainability`: Defines behavior-preserving modular boundaries and enforceable complexity regression constraints for AgentRetro's CLI, SQLite, synchronization, merge, and purge paths.

### Modified Capabilities

None.

## Impact

- Affected code: `src/agent_retro/presentation/cli.py`, `src/agent_retro/infrastructure/sqlite_repository.py`, `src/agent_retro/application/sync.py`, `merge.py`, and `purge.py`, plus new internal modules owned by those layers.
- Affected tests and CI: AgentRetro CLI, persistence, migration/WAL, Obsidian synchronization, merge, purge, subprocess, and architecture/complexity checks.
- Public API and persisted data: no intended change; existing import paths, constructors, return models, CLI envelopes, SQLite schema version, vault layout, backup/recovery behavior, and audit records remain compatible.
- Dependencies and operations: no new runtime dependency, hook, watcher, background process, database migration, credential flow, or external write surface.
