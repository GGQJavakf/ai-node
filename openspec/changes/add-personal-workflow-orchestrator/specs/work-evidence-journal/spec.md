## ADDED Requirements

### Requirement: Evidence records support closeout and reporting

The assistant SHALL persist Evidence records attached to WorkItems for commands, tests, notes, reviews, and external references.

#### Scenario: Record command evidence

- **WHEN** the user records command evidence for a WorkItem
- **THEN** the assistant SHALL persist the command, concise result summary, optional output excerpt, timestamp, and success flag.

#### Scenario: Record evidence from CLI or Agent

- **WHEN** the user runs `/work evidence add <work-id>` or asks the Agent to record evidence
- **THEN** the assistant SHALL append an Evidence record to the referenced WorkItem
- **AND** it SHALL reject unknown WorkItem ids with a clear error.

#### Scenario: Record note evidence

- **WHEN** the user records a note for a WorkItem
- **THEN** the assistant SHALL persist the note as evidence
- **AND** it SHALL make the note available to daily review generation.

### Requirement: Evidence is append-only by default

The assistant SHALL append evidence records by default rather than overwriting prior evidence.

#### Scenario: Multiple test runs are recorded

- **WHEN** the user records multiple test results for the same WorkItem
- **THEN** the assistant SHALL preserve each evidence entry
- **AND** the latest status view SHALL identify the most recent result.

### Requirement: Evidence summaries are concise and reusable

Evidence summaries SHALL be suitable for reuse in Redmine comments, MR descriptions, closeout reports, and daily reviews.

#### Scenario: Generate evidence summary

- **WHEN** the user asks for a WorkItem evidence summary
- **THEN** the assistant SHALL group evidence by type
- **AND** it SHALL include commands and outcomes without dumping full logs by default.

#### Scenario: Generate evidence summary from CLI or Agent

- **WHEN** the user runs `/work evidence summary <work-id>` or asks the Agent for an evidence summary
- **THEN** the assistant SHALL produce the grouped concise evidence summary
- **AND** it SHALL keep full raw output excerpts out of the default summary.
