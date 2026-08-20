## Context

AgentRetro's current safety model is well covered, but its implementation hotspots combine policy, orchestration, persistence, filesystem mechanics, and presentation. The five intended split targets total 8,554 lines: `sqlite_repository.py` (4,022), `cli.py` (1,285), `merge.py` (1,183), `purge.py` (1,123), and `sync.py` (941). A scoped Ruff McCabe scan reports fourteen violations in those files, including CLI `main`/`_run_command` at 35/40 and confirmed-merge synchronization at 28.

This change starts from merged `main` commit `5387ace88af526ba923a059cd6376545ceecc052`, after the value loop, CI gates, and value-loop archive are all on the unique mainline. The refactor crosses high-risk migration, transaction, filesystem replacement, backup, locking, and recovery paths, so observable compatibility and failure semantics are stronger constraints than reducing raw line counts.

## Goals / Non-Goals

**Goals:**

- Preserve every existing public import, constructor, command, exit code, output envelope, persisted format, ordering rule, and failure/recovery state while decomposing internal responsibilities.
- Leave `cli.py` as parser/bootstrap and compatibility wrappers, with command-family execution owned by focused presentation modules.
- Leave `SQLiteRetroRepository` as the public repository facade while moving schema/migration mechanics and purge-journal persistence to explicit internal collaborators or mixins.
- Separate synchronization, semantic-merge, and purge orchestration from plan codecs, path/manifest validation, locking, filesystem operations, and recovery-state mechanics.
- Enforce a scoped McCabe ceiling of 15 for the refactored target and newly extracted modules, plus architecture checks that prevent the facade files from reabsorbing the extracted responsibilities.

**Non-Goals:**

- No CLI feature, response-field, exit-code, recovery-command, SQLite schema, vault-layout, audit, projection, or knowledge-lifecycle change.
- No data migration, cleanup of existing user data, new dependency, performance rewrite, concurrency-policy change, or exception-policy change.
- No unrelated cleanup of `codex_sessions`, `codex_guidance`, `brief`, `review_commands`, redaction, or the ai-todo workflow modules even where the baseline scan reports complexity.
- No conversion to a dependency-injection framework, generic command bus, ORM, or repository-per-table abstraction.

## Decisions

### Preserve stable facades and extract private collaborators

Existing imports such as `agent_retro.presentation.cli.main`, `SQLiteRetroRepository`, `SyncService`, `MergeService`, and `PurgeService` remain canonical. New modules use a leading underscore or focused internal name and are not advertised as public API. Facades construct or delegate to collaborators with explicit arguments, so tests and callers do not need to migrate.

Alternative considered: rename the existing modules into packages and re-export everything. Rejected because it creates import/monkeypatch churn and makes a behavior-preserving review harder.

### Split by transaction and failure boundary, not by arbitrary size

Code moves together when it shares one invariant: CLI command-family rendering, SQLite schema/migration, SQLite purge journal, projection plan/filesystem application, merge plan/external-edit mechanics, or purge manifest/recovery mechanics. Transaction ownership, lock acquisition, backup creation, atomic replacement, and state transitions stay in the orchestration method that currently defines their ordering; extracted helpers are pure or receive all effects explicitly.

Alternative considered: move methods into broad utility modules until files meet a line target. Rejected because hidden effects and cross-module mutable state would reduce safety despite smaller files.

### Characterize observable contracts before each extraction

Tests snapshot stable JSON fields, human error/recovery behavior, public imports, SQLite schema/user-version, migration backup and rollback, concurrent/WAL behavior, projection states, merge plan identity, purge journals, and interrupted recovery. Existing focused suites are retained and architecture tests add import and ownership assertions. Each extraction is followed by the smallest relevant suite before the next hotspot is touched.

### Use a scoped complexity gate with no repository-wide expansion

CI runs Ruff `C901` with `lint.mccabe.max-complexity=15` only over the five facades and their new internal modules. This removes the known target violations without turning unrelated pre-existing hotspots into scope. Architecture tests also cap facade ownership through named-symbol/import assertions rather than relying only on total lines.

Alternative considered: enable C901 at threshold 10 for the whole repository. Rejected because it would bundle eleven unrelated existing violations and encourage superficial extraction.

### Keep rollback commit-granular and schema-neutral

The implementation is organized into independently reviewable commits: characterization/gate, CLI split, SQLite split, sync/merge split, purge split, and final verification. Because no persisted format changes, rollback is a normal revert of the relevant refactor commit; no database or vault downgrade operation is required.

## Risks / Trade-offs

- [A mechanical move changes monkeypatch or import seams] -> Retain compatibility wrappers and add tests that patch the historically used public module attributes before moving behavior.
- [SQLite extraction changes transaction or migration ordering] -> Keep connection/transaction ownership in the facade, pass effects explicitly, and rerun migration backup, WAL concurrency, rollback, and purge-journal suites after each move.
- [Filesystem helper extraction changes path validation or atomic replacement] -> Move validation and operation as one invariant-preserving unit, retain injected clock/replace/lock seams, and test preflight, failure, rollback-required, and recovery states.
- [Complexity moves into unmeasured helper modules] -> Include every new AgentRetro module owned by the change in the scoped C901 command and architecture manifest.
- [A broad refactor becomes difficult to review] -> Use responsibility-sized commits and require zero mixed product behavior; any discovered behavior defect becomes a separate change unless needed to preserve the current contract.

## Migration Plan

1. Add behavior characterization and the scoped architecture/complexity command in a failing state that identifies only the agreed hotspots.
2. Extract CLI command families and restore the gate for presentation entry points.
3. Extract SQLite schema/migration and purge-journal responsibilities while keeping the facade and schema version stable.
4. Extract synchronization and semantic-merge mechanics, then purge filesystem/recovery mechanics, validating each high-risk suite separately.
5. Run full cross-platform-equivalent local checks, strict OpenSpec validation, packaging smoke, OCR delegated review, and one fresh high-risk review before publishing.

Rollback is commit-level revert. No schema, vault, or user-data rollback is needed because stored representations do not change.

## Open Questions

None. The target modules, compatibility boundary, complexity ceiling, excluded hotspots, validation matrix, and rollback model are fixed for this change.
