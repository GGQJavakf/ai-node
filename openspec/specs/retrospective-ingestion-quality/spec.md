# retrospective-ingestion-quality Specification

## Purpose
TBD - created by archiving change harden-recent-session-capture. Update Purpose after archive.
## Requirements
### Requirement: Unsupported optional-event diagnostics are bounded
The system SHALL ignore unsupported optional Codex events without failing capture and SHALL aggregate their counts by normalized event type into a stable sorted warning summary instead of emitting one warning per event.

#### Scenario: [IQ-01] Many repeated optional events are ignored
- **WHEN** a completed session contains many unsupported `reasoning`, `token_count`, or custom event records
- **THEN** capture SHALL persist all supported events and emit a bounded summary containing each ignored type and count

#### Scenario: [IQ-02] No unsupported events exist
- **WHEN** every event is supported or intentionally metadata-only
- **THEN** capture SHALL emit no unsupported-event warning summary

### Requirement: Duplicate evidence content is stored once with all locations
The system SHALL canonicalize evidence within one session by evidence kind and redacted content hash, retain one stable evidence id, and persist every unique source locator associated with that canonical evidence.

#### Scenario: [IQ-03] Identical supported events repeat
- **WHEN** two or more supported events in one session have the same kind and redacted content hash
- **THEN** the system SHALL persist one canonical evidence record
- **AND** it SHALL make every unique event locator available for inspection

#### Scenario: [IQ-04] Same content has different evidence kinds
- **WHEN** identical text appears under different evidence kinds
- **THEN** the system SHALL preserve separate canonical evidence records for those kinds

#### Scenario: [IQ-05] Repeated capture remains idempotent
- **WHEN** the same source session is captured again
- **THEN** the system SHALL create no duplicate evidence or locator rows and SHALL preserve the prior capture result

### Requirement: Model input uses canonical unique evidence
The system SHALL build extraction and review input from canonical evidence records only, without losing the stable evidence ids referenced by candidates and knowledge.

#### Scenario: [IQ-06] Review input follows evidence deduplication
- **WHEN** captured events contain duplicate content
- **THEN** model input SHALL contain one object per canonical evidence id and SHALL be deterministically ordered
