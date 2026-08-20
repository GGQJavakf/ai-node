## REMOVED Requirements

### Requirement: Capture is explicit and limited to one completed Codex session

**Reason**: Single-session capture remains supported, but the requirement is superseded by a bounded preview/apply batch mode.

**Migration**: Existing `retro capture --last` and `retro capture --session <session-id>` commands retain their behavior.

## ADDED Requirements

### Requirement: Capture is explicit and bounded

The system SHALL capture local Codex session data only after an explicit `retro capture` command and SHALL NOT install a hook, watcher, scheduled task, or background capture process. Single-session commands SHALL capture only one completed session. Recent batch capture SHALL be bounded, preview-first, explicitly confirmed, and fail closed when its ordered source or project-resolution identity changes.

#### Scenario: [CR-01] Capture the last completed session

- **WHEN** the user runs `retro capture --last` and at least one completed Codex session is discoverable
- **THEN** the system SHALL select the newest completed session
- **AND** it SHALL create a capture result for only that session

#### Scenario: [CR-02] Capture a named session

- **WHEN** the user runs `retro capture --session <session-id>` for a completed discoverable session
- **THEN** the system SHALL capture only the named session

#### Scenario: [CR-03] Active session is not captured

- **WHEN** a requested or recently discovered session is still active or lacks a completed-session marker
- **THEN** the system SHALL refuse to extract knowledge from it
- **AND** it SHALL report that the session is incomplete

#### Scenario: [CR-04] Capture does not enable automation

- **WHEN** AgentRetro is installed or any capture command completes
- **THEN** the system SHALL NOT add hooks, scheduled tasks, watchers, or background services

#### Scenario: [CR-23] Preview recent completed sessions

- **WHEN** the user runs `retro capture --recent <count> --dry-run` and `count` is within the configured bound
- **THEN** the system SHALL select completed sessions newest first and return `requested_count`, `recent_capture_max`, a plan schema version, and an ordered list of safe session IDs
- **AND** each list item SHALL include `source_hash`, `resolution_status`, `canonical_project_id`, `mapping_id`, and `reuse_status`, using empty identifiers only when resolution is not successful
- **AND** the deterministic plan ID SHALL hash the plan schema version, requested count, effective maximum, and every ordered item field
- **AND** the command SHALL NOT write session, evidence, candidate, knowledge, audit, projection, or vault state

#### Scenario: [CR-24] Apply an unchanged recent capture plan

- **WHEN** the user runs `retro capture --recent <count> --apply <plan-id>` and the recomputed complete plan exactly matches the supplied plan ID
- **THEN** the system SHALL process resolved items newest first through the existing idempotent per-session transaction
- **AND** it SHALL classify each planned session exactly once as `captured`, `reused`, `failed`, or `skipped`
- **AND** unresolved or ambiguous project items SHALL be `skipped` with a stable routing reason and SHALL NOT be written

#### Scenario: [CR-25] Recent capture plan changed

- **WHEN** the requested count, effective maximum, ordered session IDs, source hash, resolution status, canonical project ID, mapping ID, or reuse status differs from the supplied plan
- **THEN** the system SHALL refuse the complete batch before the first write with `capture_plan_changed`
- **AND** it SHALL return `retro capture --recent <count> --dry-run` as the recovery command

#### Scenario: [CR-26] Recent capture count is unsafe

- **WHEN** the requested count is less than one or exceeds the positive configured `recent_capture_max`, which defaults to 20
- **THEN** the system SHALL return `recent_capture_count_out_of_bounds`
- **AND** it SHALL perform no session discovery or persistence

#### Scenario: [CR-27] A per-session capture fails during apply

- **WHEN** a resolved planned session fails after one or more earlier sessions were committed or reused
- **THEN** the system SHALL keep the earlier per-session commits, put only the attempted failing session in `failed`, stop processing, and put every unattempted remaining session in `skipped` with reason `batch_stopped`
- **AND** it SHALL return the four disjoint ordered result lists and the exact dry-run recovery command without claiming cross-session rollback or atomicity

#### Scenario: [CR-28] Re-preview after a partial failure

- **WHEN** the user runs a new dry-run after a partial apply
- **THEN** the new plan SHALL report already committed sessions as `reused` and remaining eligible sessions according to current source and mapping state
- **AND** applying that new plan SHALL NOT duplicate session, evidence, candidate, audit, or projection records
