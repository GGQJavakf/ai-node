# agentretro-maintainability Specification

## Purpose

Define maintainability guardrails for completing AgentRetro hotspot decomposition while preserving public contracts, observable behavior, persistence and input-boundary safety, and independently verifiable delivery evidence.

## Requirements

### Requirement: AgentRetro hotspot modules have explicit internal owners

The system SHALL retain the existing public CLI, repository, synchronization, merge, purge, briefing, merge-planning, Codex-session, Codex-guidance, redaction, and review-command entry points while assigning command-family dispatch, SQLite schema and purge persistence, projection mechanics, merge mechanics, purge recovery mechanics, selection and validation, parsing, mutation, scanning, and outcome rendering to focused internal owners. Dependency direction SHALL remain presentation to application to infrastructure/domain, except for explicit application ports, and the split SHALL NOT introduce a circular import.

#### Scenario: Import stable public entry points after decomposition
- **WHEN** callers import `main`, `SQLiteRetroRepository`, `SyncService`, `ProjectionCoordinator`, `MergeService`, or `PurgeService` from their existing module paths
- **THEN** every import and constructor contract SHALL remain available
- **AND** importing the AgentRetro package and the extracted internal modules SHALL complete without a circular-import error

#### Scenario: Import stable public entry points after complete decomposition
- **WHEN** callers import the existing AgentRetro CLI, repository, service, planner, session-source, guidance, redactor, or review-command entry points
- **THEN** every import, public signature, constructor contract, and historical monkeypatch seam SHALL remain available
- **AND** importing the AgentRetro package and every declared private collaborator SHALL complete without a circular-import error

#### Scenario: Enforce extracted responsibility ownership
- **WHEN** the architecture regression test inspects the refactored facades and their declared internal collaborators
- **THEN** each extracted responsibility SHALL have exactly one declared owner
- **AND** the facade SHALL delegate through an explicit boundary instead of duplicating the extracted implementation

### Requirement: Complexity reduction is measurable and scoped

Every AgentRetro function and each internal module introduced by either complexity phase SHALL pass Ruff `C901` with `lint.mccabe.max-complexity=15`. The shared complexity manifest SHALL cover every affected facade and private collaborator, SHALL reject an imported private collaborator omitted from the manifest, and SHALL NOT suppress individual violations or expand this change to ai-todo baseline hotspots.

#### Scenario: Refactored code passes the scoped complexity gate
- **WHEN** CI evaluates the declared AgentRetro refactor manifest with the configured McCabe ceiling
- **THEN** the command SHALL report no `C901` finding in the target or extracted modules
- **AND** every new internal module introduced by this change SHALL be included in the manifest

#### Scenario: All AgentRetro code passes the scoped ceiling
- **WHEN** CI evaluates the declared refactor manifest and a full `src/agent_retro` C901 scan with the configured McCabe ceiling
- **THEN** both commands SHALL report no `C901` finding
- **AND** every private module introduced by the two complexity changes SHALL be included in the manifest

#### Scenario: A hotspot is reintroduced
- **WHEN** a future change makes a covered function exceed the ceiling or adds an uncovered internal module owned by a declared responsibility
- **THEN** the complexity or architecture check SHALL fail with the affected module or function

#### Scenario: A hotspot or uncovered collaborator is introduced
- **WHEN** a future change makes an AgentRetro function exceed the ceiling or imports an uncovered private collaborator from a covered module
- **THEN** the complexity or architecture check SHALL fail with the affected module or function

### Requirement: Decomposition preserves observable behavior

The system SHALL preserve existing CLI arguments, JSON and human envelopes, exit codes, recovery commands, Python return models, ordering, idempotency, audit records, projection states, merge plan identity, purge journals, plan and session identity, budgets, deadlines, bounded discovery, credential redaction, path containment, SQLite schema and user version, vault layout, backup-first behavior, lock ordering, and failure recovery semantics throughout the decomposition.

#### Scenario: Brief and merge planning remain deterministic
- **WHEN** briefing or semantic-merge planning succeeds or encounters budget, deadline, input-limit, path, model, stale, or sensitive-input failures
- **THEN** selected content, ordering, rendered output, plan identity, gateway inputs, errors, and zero-write behavior SHALL match the pre-refactor contract

#### Scenario: Codex session parsing remains bounded and stable
- **WHEN** a session is valid, malformed, oversized, truncated, mixed-encoding, symlinked, replayed, or processed at a discovery deadline
- **THEN** event ordering, normalized identity, bounds, rejection reason, and persistence behavior SHALL match the pre-refactor contract
- **AND** no path outside the configured Codex-session boundary SHALL be read

#### Scenario: Sensitive-header scanning remains fail-closed and bounded
- **WHEN** content contains Authorization, Proxy-Authorization, Cookie, Set-Cookie, folded or flattened headers, quoted delimiters, escaped bytes, long whitespace, or non-sensitive similarly named headers
- **THEN** reusable credentials SHALL not reach model or persistence boundaries
- **AND** non-sensitive content and idempotency SHALL be preserved
- **AND** scanner work SHALL remain bounded linearly by input length

#### Scenario: Guidance and review command behavior remains compatible
- **WHEN** Codex guidance or review commands preview, apply, remove, retry, succeed, fail validation, encounter model unavailability, projection pending, write failure, or rollback failure
- **THEN** backups, mutations, rollback state, exit codes, stable envelopes, warnings, and recovery commands SHALL match the pre-refactor contract

#### Scenario: Existing SQLite, synchronization, merge-apply, and purge behavior remains compatible
- **WHEN** existing repository, projection, confirmed-merge, or purge flows run after the complete decomposition
- **THEN** persisted formats, transaction and lock ordering, backups, atomic replacement, state transitions, containment, and recovery outcomes SHALL remain unchanged

#### Scenario: CLI behavior remains compatible
- **WHEN** existing success, validation failure, synchronization pending, rollback required, merge, purge, review, capture, project, doctor, and brief commands run after the split
- **THEN** their exit codes and stable output fields SHALL match the pre-refactor contract
- **AND** JSON output SHALL remain one parseable content-safe envelope without ANSI or exception detail leakage

#### Scenario: SQLite migration and transaction behavior remains compatible
- **WHEN** a repository opens a current database, upgrades a supported prior schema, encounters migration failure, or competes with a WAL writer
- **THEN** schema version, committed rows, backup consistency, transaction rollback, and fail-closed recovery SHALL match the pre-refactor behavior
- **AND** the change SHALL create no new migration or stored representation

#### Scenario: Synchronization and merge failure behavior remains compatible
- **WHEN** projection or confirmed merge succeeds, is already applied, fails preflight or backup/write, or requires rollback
- **THEN** state transitions, backups, atomic replacement, warnings, recovery commands, and persisted plan identity SHALL remain unchanged

#### Scenario: Interrupted purge behavior remains compatible
- **WHEN** purge is previewed, applied, interrupted at any journaled stage, retried, or recovered with residual files or database entities
- **THEN** confirmation identity, journal transitions, registered targets, residual classification, idempotency, and recovery outcome SHALL remain unchanged
- **AND** no target outside the existing containment and registration boundary SHALL be modified

### Requirement: Refactor delivery is independently verifiable

The change SHALL provide focused characterization, architecture, full AgentRetro complexity, full regression, strict OpenSpec, lint, compile, type, package, Windows encoding, and independent review evidence before it is marked ready. High-risk SQLite concurrency, destructive recovery, session parsing, sensitive-header redaction, backup and rollback, and path-containment boundaries SHALL receive dedicated validation rather than relying only on the full suite.

#### Scenario: Produce ready-for-review evidence
- **WHEN** implementation tasks are complete
- **THEN** the recorded evidence SHALL identify the exact commit and include focused CLI, SQLite/WAL/migration, sync, merge, purge, brief, merge-planner, session-hardening, capture/redaction, Codex-guidance, review/CLI, UTF-8/GBK, full-suite, branch-coverage, Ruff, scoped-manifest and full AgentRetro C901, mypy, compileall, package, strict OpenSpec, and OCR results
- **AND** OCR accounting SHALL include every changed file or explain unsupported exclusions
- **AND** any unavailable high-risk check or unresolved material finding SHALL keep the change from being marked ready
