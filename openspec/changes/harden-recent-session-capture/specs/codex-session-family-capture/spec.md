## ADDED Requirements

### Requirement: Valid parent-child metadata chains are captured conservatively
The system SHALL accept one or more consecutive leading `session_meta` records only when they form a verifiable ordered child-to-parent chain, and SHALL use the first record as the effective leaf session identity and working directory.

#### Scenario: [SF-01] Capture a nested subagent session
- **WHEN** each metadata record names the next record as its parent or fork source and non-empty family session ids agree
- **THEN** the system SHALL capture the completed leaf session and its supported events
- **AND** it SHALL retain the complete source hash for idempotency

#### Scenario: [SF-02] Capture a single metadata session
- **WHEN** a completed session contains exactly one valid leading `session_meta`
- **THEN** the system SHALL preserve the existing capture behavior

### Requirement: Unverifiable repeated metadata remains rejected
The system SHALL reject repeated metadata that is unrelated, cyclic, conflicting, duplicated, or appears after a non-metadata event, without persisting partial capture state.

#### Scenario: [SF-03] Repeated metadata is unrelated
- **WHEN** a second metadata record is not the declared parent or fork source of the previous record
- **THEN** the system SHALL report a format error and persist no session, event, evidence, candidate, or knowledge row

#### Scenario: [SF-04] Metadata appears after events
- **WHEN** any `session_meta` record appears after an ordinary event
- **THEN** the system SHALL reject the file as identity-ambiguous

#### Scenario: [SF-05] Family identity conflicts
- **WHEN** non-empty metadata family session ids disagree or the ancestry chain repeats an id
- **THEN** the system SHALL reject the file as identity-conflicting

### Requirement: Discovery can locate a valid leaf in a metadata chain
The system SHALL use the first leading metadata record for direct session-id lookup and SHALL NOT skip a valid nested subagent file merely because verified ancestor metadata follows it.

#### Scenario: [SF-06] Load a nested session by leaf id
- **WHEN** the user captures a completed nested session by the first metadata record id
- **THEN** discovery SHALL locate and parse that file within the configured size, candidate, and time bounds
