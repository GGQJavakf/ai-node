## ADDED Requirements

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
