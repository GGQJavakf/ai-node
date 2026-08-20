## ADDED Requirements

### Requirement: Exhausted structured-response failure has one bounded fresh retry
The system SHALL perform at most one fresh service-level retry for the same canonical review input after the strict adapter exhausts its structured-response repair, and SHALL NOT automatically retry authentication, configuration, permission, persistence, or unknown failures.

#### Scenario: [RR-01] Fresh structured retry succeeds
- **WHEN** the first strict review attempt ends with an exhausted structured-response error and the fresh attempt returns a valid result
- **THEN** the system SHALL apply the valid result once using unchanged thresholds and deterministic gates

#### Scenario: [RR-02] Fresh structured retry also fails
- **WHEN** both strict review attempts fail structured validation
- **THEN** the candidate SHALL remain pending and manually retryable with no accepted knowledge

#### Scenario: [RR-03] Non-retryable model error occurs
- **WHEN** review fails because of configuration, authentication, permission, persistence, or an unclassified error
- **THEN** the system SHALL stop without a fresh automatic attempt and expose a stable failure category

### Requirement: Every candidate review attempt is observable
The system SHALL audit every candidate review attempt with attempt number, canonical input hash, status, stable error category, and non-negative duration in milliseconds without persisting raw model errors or secrets.

#### Scenario: [RR-04] Failed then successful review is inspected
- **WHEN** a candidate has one failed attempt followed by one completed attempt
- **THEN** inspection SHALL return both attempts in order with distinct attempt numbers, statuses, durations, and redacted categories

#### Scenario: [RR-05] Existing attempts are migrated
- **WHEN** a pre-change database is migrated
- **THEN** existing review attempts SHALL remain readable with neutral duration and error-category defaults

### Requirement: Review recovery remains idempotent
The system SHALL reuse a completed result for the same candidate and canonical input hash and SHALL NOT create duplicate candidates, accepted knowledge, or projection events across automatic or manual retry.

#### Scenario: [RR-06] Completed review is retried
- **WHEN** the same candidate and input hash already have a completed attempt
- **THEN** the system SHALL reuse that result without another model call or duplicate acceptance
