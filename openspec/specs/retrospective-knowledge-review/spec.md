# retrospective-knowledge-review Specification

## Purpose
TBD - created by archiving change add-agentretro-mvp. Update Purpose after archive.
## Requirements
### Requirement: Knowledge uses three evidence-constrained types

The system SHALL classify candidates as `RULE`, `LESSON`, or `TASK_STATE` and SHALL enforce the evidence contract of the selected type.

#### Scenario: [KR-01] Create a rule candidate

- **WHEN** evidence contains an explicit user instruction, applicable project rule, or other authoritative project source
- **THEN** the system SHALL allow a `RULE` candidate linked to that evidence

#### Scenario: [KR-02] Reject an inferred rule

- **WHEN** a proposed rule is based only on an inferred habit or model speculation
- **THEN** the system SHALL block automatic acceptance of that `RULE`

#### Scenario: [KR-03] Create a lesson candidate

- **WHEN** evidence establishes a failure, its correction, and a successful verification result
- **THEN** the system SHALL allow a `LESSON` candidate linked to each part of that chain

#### Scenario: [KR-04] Reject an unverified lesson

- **WHEN** a proposed lesson lacks successful verification evidence
- **THEN** the system SHALL block automatic acceptance of that `LESSON`

#### Scenario: [KR-05] Create task state

- **WHEN** evidence establishes an observable status, blocker, decision, or next action
- **THEN** the system SHALL allow a `TASK_STATE` candidate with a default 14-day validity period

### Requirement: Candidate production and review are separate stages

The system SHALL use one stage to extract evidence-bound candidates and a separate stage to review candidate validity, wording, duplication, and conflict.

#### Scenario: [KR-06] Independent review returns a structured verdict

- **WHEN** extraction produces a candidate
- **THEN** the review stage SHALL return `ACCEPT`, `EDIT`, or `REJECT`, confidence, reason, normalized text, duplicate assessment, and conflict assessment
- **AND** the review input SHALL contain only redacted candidate and evidence data

#### Scenario: [KR-07] Model review is unavailable

- **WHEN** the configured model cannot complete the review
- **THEN** the system SHALL preserve the candidate as pending and retryable
- **AND** it SHALL NOT automatically accept the candidate

### Requirement: Automatic acceptance is conservative and deterministic

The system SHALL automatically accept only a reviewed `RULE` with confidence at least `0.97`, a reviewed `LESSON` with confidence at least `0.93`, or a reviewed `TASK_STATE` with confidence at least `0.90`, after every deterministic gate passes.

#### Scenario: [KR-08] High-confidence safe candidate

- **WHEN** a candidate meets its type threshold and all deterministic gates pass
- **THEN** the system SHALL mark it `auto_accepted`
- **AND** it SHALL record the model verdict, threshold, gate results, and evidence in the audit log

#### Scenario: [KR-09] Confidence is below the type threshold

- **WHEN** a reviewed candidate has confidence below its type threshold
- **THEN** the system SHALL keep it pending for human review

#### Scenario: [KR-10] Hard gate blocks a high-confidence candidate

- **WHEN** a candidate contains a possible secret, lacks evidence, has an unknown project, duplicates knowledge, conflicts with active knowledge, or presents speculation as fact
- **THEN** the system SHALL block automatic acceptance regardless of confidence
- **AND** it SHALL record the blocking gate

### Requirement: Users can review and edit candidate outcomes

The system SHALL allow users to inspect evidence and accept, edit, reject, or merge pending candidates.

#### Scenario: [KR-11] User accepts a candidate

- **WHEN** the user accepts a pending candidate
- **THEN** the system SHALL create or activate the corresponding knowledge version
- **AND** it SHALL record the user as the acceptance actor

#### Scenario: [KR-12] User edits a candidate

- **WHEN** the user changes candidate text, type, scope, or validity before accepting it
- **THEN** the system SHALL persist the edited version with the original evidence links
- **AND** it SHALL record the before and after hashes

#### Scenario: [KR-13] User rejects a candidate

- **WHEN** the user rejects a candidate
- **THEN** the system SHALL exclude it from active knowledge, synchronization, and briefing
- **AND** it SHALL retain a non-active audit record of the decision

### Requirement: Conflicts never overwrite active knowledge automatically

The system SHALL retain the existing active item when a new candidate conflicts and SHALL keep the new item pending with a merge proposal.

#### Scenario: [KR-14] New candidate conflicts with active knowledge

- **WHEN** review detects incompatible knowledge in the same type and scope
- **THEN** the existing knowledge SHALL remain active
- **AND** the new candidate SHALL be excluded from automatic acceptance, synchronization, and briefing
- **AND** the system SHALL create a conflict record with a merge suggestion

#### Scenario: [KR-15] User resolves a conflict

- **WHEN** the user applies a reviewed conflict merge
- **THEN** the system SHALL create a new knowledge version that references the superseded items
- **AND** it SHALL preserve the prior versions in audit history

### Requirement: Scope, expiry, archive, and deletion are controlled

The system SHALL default knowledge to project scope, require explicit global promotion, mark `TASK_STATE` stale after its validity period, archive ordinary removals, and require an immutable impact plan plus exact operation confirmation for sensitive purge.

#### Scenario: [KR-16] Promote knowledge globally

- **WHEN** the user explicitly promotes accepted project knowledge to global scope
- **THEN** the system SHALL create a global-scope version and record the promotion actor
- **AND** the global version SHALL be available to every project's brief according to its type-specific category and relevance rules
- **AND** the system SHALL trigger same-command projection of the originating project so the superseded project-scoped entry is removed from its managed aggregate

#### Scenario: [KR-17] Task state expires

- **WHEN** the current time exceeds an active `TASK_STATE` validity end
- **THEN** the system SHALL mark it stale
- **AND** it SHALL exclude it from default briefs without deleting it

#### Scenario: [KR-18] Archive ordinary knowledge

- **WHEN** the user removes non-sensitive active knowledge without requesting hard deletion
- **THEN** the system SHALL archive it and preserve its evidence and history

#### Scenario: [KR-19] Plan sensitive purge

- **WHEN** the user requests sensitive purge for one knowledge item
- **THEN** the system SHALL produce a no-write plan containing every known AgentRetro-owned SQLite, audit-detail, managed-vault, log, model-trace, migration-backup, synchronization-backup, and merge-backup location that contains the content
- **AND** it SHALL assign an exact operation ID to every removal

#### Scenario: [KR-20] Apply a fully confirmed sensitive purge

- **WHEN** the user applies a current purge plan and confirms every operation ID
- **THEN** the system SHALL remove and verify every planned AgentRetro-owned copy through transactional or journaled writes
- **AND** it SHALL retain only entity identity, actor, timestamps, status, and non-reversible content-free tombstone metadata

#### Scenario: [KR-21] A known sensitive copy cannot be removed

- **WHEN** any planned location cannot be cleaned or its cleanup cannot be verified
- **THEN** the system SHALL mark the purge `purge_incomplete`
- **AND** it SHALL NOT report success or automatically re-project that item
- **AND** it SHALL identify residual locations without exposing the sensitive value

### Requirement: Knowledge lifecycle actions are auditable

The system SHALL record capture, review, automatic acceptance, manual acceptance, edit, rejection, conflict resolution, synchronization, archive, and sensitive-purge actions with actor, timestamp, entity identity, and before/after hashes where applicable.

#### Scenario: [KR-22] Inspect knowledge history

- **WHEN** the user views an accepted knowledge item
- **THEN** the system SHALL make its versions, evidence references, acceptance actor, and lifecycle history available without exposing redacted values

### Requirement: Failed model review is retryable without duplicate extraction

The system SHALL allow review retry for one candidate or all pending candidates from one captured session, SHALL reuse stored redacted candidate/evidence, and SHALL audit every attempt.

#### Scenario: [KR-23] Retry one candidate review

- **WHEN** the user retries a pending candidate after a model failure
- **THEN** the system SHALL create one review attempt over the existing review-input hash
- **AND** it SHALL NOT repeat extraction or create duplicate session, evidence, or candidate rows
- **AND** repeating retry after a terminal result SHALL reuse that result and create no duplicate accepted knowledge

#### Scenario: [KR-24] Retry all pending reviews for one session

- **WHEN** the user retries review for one captured session
- **THEN** the system SHALL retry only its pending model-dependent candidates
- **AND** successful results SHALL pass through the normal thresholds and gates
- **AND** failed results SHALL remain pending and retryable with an audited failure reason

### Requirement: Review inbox is concise, project-aware, bounded, and content-safe

The system SHALL provide a read-only review inbox that summarizes pending review work by canonical project, candidate status, and age without returning candidate text, evidence excerpts, source paths, model-error details, or credentials. The injected current time SHALL be used for all age and expiry calculations.

#### Scenario: [KR-25] List the cross-project review inbox

- **WHEN** the user runs `retro review inbox` without a project or awaiting selector
- **THEN** the system SHALL return one row per canonical project sorted by canonical project ID with `pending_count`, `retryable_count`, and `oldest_pending_age_seconds`
- **AND** age SHALL be a non-negative whole number of elapsed seconds or `null` when the count is zero
- **AND** it SHALL return `awaiting_unknown_count` and `awaiting_ambiguous_count` for captured sessions that cannot yet be routed

#### Scenario: [KR-26] List one project's next review actions

- **WHEN** the user runs `retro review inbox --project <reference> [--limit <count>]` and the reference resolves uniquely
- **THEN** the system SHALL return pending candidate IDs ordered by `created_at` ascending then candidate ID ascending, with a default limit of 20 and an allowed range of 1 through 50
- **AND** it SHALL return `total_count`, `returned_count`, and `truncated`, plus exact `show`, `accept`, `edit`, `reject`, and eligible `retry` command templates using the canonical project ID
- **AND** `retryable_count` and retry commands SHALL include only `pending_review` candidates with no saved review result whose latest attempt failed or which have no attempt; running or completed attempts SHALL not be retryable

#### Scenario: [KR-27] Review inbox project is unknown or ambiguous

- **WHEN** the project reference cannot resolve to exactly one canonical project
- **THEN** the system SHALL fail with `unknown_project_reference` or `ambiguous_project_reference` and the same safe resolver diagnostics used by brief
- **AND** it SHALL NOT fall back to an empty inbox

#### Scenario: [KR-28] List awaiting project routing work

- **WHEN** the user runs `retro review inbox --awaiting [--limit <count>]`
- **THEN** the system SHALL return safe source session IDs ordered by capture time ascending then session ID ascending, their `unknown` or `ambiguous` routing status, the same 1 through 50 limit contract, and `total_count`, `returned_count`, and `truncated`
- **AND** it SHALL return `retro project list` and `retro project reclassify --session <session-id> --mapping <mapping-id>` command templates without returning a source path or remote value

### Requirement: Read summaries report effective task-state expiry consistently

The system SHALL report an active `TASK_STATE` whose validity end is at or before the injected current time as expired in brief and review-inbox health summaries, while keeping those commands read-only.

#### Scenario: [KR-29] Active stored task state is past validity

- **WHEN** a task state is stored as active but its `valid_until` is at or before the injected current time
- **THEN** brief and inbox health summaries SHALL count it as expired rather than eligible or active
- **AND** neither command SHALL update SQLite, audit, projection, or Obsidian state

#### Scenario: [KR-30] Task state is still current

- **WHEN** an active task state has no validity end or its validity end is after the injected current time
- **THEN** summaries SHALL count it as active and eligible according to the existing project/global scope rules
