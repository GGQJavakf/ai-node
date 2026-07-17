## ADDED Requirements

### Requirement: Knowledge uses three evidence-constrained types

The system SHALL classify candidates as `RULE`, `LESSON`, or `TASK_STATE` and SHALL enforce the evidence contract of the selected type.

#### Scenario: Create a rule candidate

- **WHEN** evidence contains an explicit user instruction, applicable project rule, or other authoritative project source
- **THEN** the system SHALL allow a `RULE` candidate linked to that evidence

#### Scenario: Reject an inferred rule

- **WHEN** a proposed rule is based only on an inferred habit or model speculation
- **THEN** the system SHALL block automatic acceptance of that `RULE`

#### Scenario: Create a lesson candidate

- **WHEN** evidence establishes a failure, its correction, and a successful verification result
- **THEN** the system SHALL allow a `LESSON` candidate linked to each part of that chain

#### Scenario: Reject an unverified lesson

- **WHEN** a proposed lesson lacks successful verification evidence
- **THEN** the system SHALL block automatic acceptance of that `LESSON`

#### Scenario: Create task state

- **WHEN** evidence establishes an observable status, blocker, decision, or next action
- **THEN** the system SHALL allow a `TASK_STATE` candidate with a default 14-day validity period

### Requirement: Candidate production and review are separate stages

The system SHALL use one stage to extract evidence-bound candidates and a separate stage to review candidate validity, wording, duplication, and conflict.

#### Scenario: Independent review returns a structured verdict

- **WHEN** extraction produces a candidate
- **THEN** the review stage SHALL return `ACCEPT`, `EDIT`, or `REJECT`, confidence, reason, normalized text, duplicate assessment, and conflict assessment
- **AND** the review input SHALL contain only redacted candidate and evidence data

#### Scenario: Model review is unavailable

- **WHEN** the configured model cannot complete the review
- **THEN** the system SHALL preserve the candidate as pending and retryable
- **AND** it SHALL NOT automatically accept the candidate

### Requirement: Automatic acceptance is conservative and deterministic

The system SHALL automatically accept only a reviewed `RULE` with confidence at least `0.97`, a reviewed `LESSON` with confidence at least `0.93`, or a reviewed `TASK_STATE` with confidence at least `0.90`, after every deterministic gate passes.

#### Scenario: High-confidence safe candidate

- **WHEN** a candidate meets its type threshold and all deterministic gates pass
- **THEN** the system SHALL mark it `auto_accepted`
- **AND** it SHALL record the model verdict, threshold, gate results, and evidence in the audit log

#### Scenario: Confidence is below the type threshold

- **WHEN** a reviewed candidate has confidence below its type threshold
- **THEN** the system SHALL keep it pending for human review

#### Scenario: Hard gate blocks a high-confidence candidate

- **WHEN** a candidate contains a possible secret, lacks evidence, has an unknown project, duplicates knowledge, conflicts with active knowledge, or presents speculation as fact
- **THEN** the system SHALL block automatic acceptance regardless of confidence
- **AND** it SHALL record the blocking gate

### Requirement: Users can review and edit candidate outcomes

The system SHALL allow users to inspect evidence and accept, edit, reject, or merge pending candidates.

#### Scenario: User accepts a candidate

- **WHEN** the user accepts a pending candidate
- **THEN** the system SHALL create or activate the corresponding knowledge version
- **AND** it SHALL record the user as the acceptance actor

#### Scenario: User edits a candidate

- **WHEN** the user changes candidate text, type, scope, or validity before accepting it
- **THEN** the system SHALL persist the edited version with the original evidence links
- **AND** it SHALL record the before and after hashes

#### Scenario: User rejects a candidate

- **WHEN** the user rejects a candidate
- **THEN** the system SHALL exclude it from active knowledge, synchronization, and briefing
- **AND** it SHALL retain a non-active audit record of the decision

### Requirement: Conflicts never overwrite active knowledge automatically

The system SHALL retain the existing active item when a new candidate conflicts and SHALL keep the new item pending with a merge proposal.

#### Scenario: New candidate conflicts with active knowledge

- **WHEN** review detects incompatible knowledge in the same type and scope
- **THEN** the existing knowledge SHALL remain active
- **AND** the new candidate SHALL be excluded from automatic acceptance, synchronization, and briefing
- **AND** the system SHALL create a conflict record with a merge suggestion

#### Scenario: User resolves a conflict

- **WHEN** the user applies a reviewed conflict merge
- **THEN** the system SHALL create a new knowledge version that references the superseded items
- **AND** it SHALL preserve the prior versions in audit history

### Requirement: Scope, expiry, archive, and deletion are controlled

The system SHALL default knowledge to project scope, require explicit global promotion, mark `TASK_STATE` stale after its validity period, archive ordinary removals, and require explicit confirmation for sensitive hard deletion.

#### Scenario: Promote knowledge globally

- **WHEN** the user explicitly promotes accepted project knowledge to global scope
- **THEN** the system SHALL create a global-scope version and record the promotion actor

#### Scenario: Task state expires

- **WHEN** the current time exceeds an active `TASK_STATE` validity end
- **THEN** the system SHALL mark it stale
- **AND** it SHALL exclude it from default briefs without deleting it

#### Scenario: Archive ordinary knowledge

- **WHEN** the user removes non-sensitive active knowledge without requesting hard deletion
- **THEN** the system SHALL archive it and preserve its evidence and history

#### Scenario: Hard-delete sensitive content

- **WHEN** the user explicitly confirms hard deletion of sensitive knowledge
- **THEN** the system SHALL remove persisted excerpts and synchronized content
- **AND** it SHALL retain only a content-free audit tombstone

### Requirement: Knowledge lifecycle actions are auditable

The system SHALL record capture, review, automatic acceptance, manual acceptance, edit, rejection, conflict resolution, synchronization, archive, and hard-deletion actions with actor, timestamp, entity identity, and before/after hashes where applicable.

#### Scenario: Inspect knowledge history

- **WHEN** the user views an accepted knowledge item
- **THEN** the system SHALL make its versions, evidence references, acceptance actor, and lifecycle history available without exposing redacted values
