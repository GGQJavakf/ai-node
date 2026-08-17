# work-evidence-journal Specification

## Purpose
TBD - created by archiving change add-personal-workflow-orchestrator. Update Purpose after archive.
## Requirements
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

### Requirement: Closeout gaps are persisted as local Evidence

The assistant SHALL persist closeout context gaps as local Evidence attached to WorkItems without writing external workflow systems.

#### Scenario: MR merged but Redmine not closed gap

- **GIVEN** a read-only source snapshot contains facts indicating an MR is merged and the related Redmine issue is not closed
- **WHEN** `/sync` persists project context
- **THEN** the assistant SHALL append Evidence with a summary equivalent to `closeout gap: MR merged but Redmine not closed`
- **AND** the Evidence SHALL include the read-only command or local source that produced the fact.

#### Scenario: Redmine resolved but validation evidence missing gap

- **GIVEN** a read-only source snapshot contains facts indicating Redmine is resolved or closed but local validation/test/review evidence is missing
- **WHEN** `/sync` persists project context
- **THEN** the assistant SHALL append Evidence with a summary equivalent to `closeout gap: Redmine resolved but validation evidence missing`.

#### Scenario: OpenSpec completed but not archived gap

- **GIVEN** a read-only source snapshot contains facts indicating an OpenSpec change has completed tasks or artifacts but is not archived
- **WHEN** `/sync` persists project context
- **THEN** the assistant SHALL append Evidence with a summary equivalent to `closeout gap: OpenSpec completed but not archived`.

#### Scenario: Gap maps to matching WorkItem

- **GIVEN** a detected closeout gap contains a stable identity such as `redmine:<id>`, `gitlab-mr:<project>:<iid>`, or `openspec:<change>`
- **AND** exactly one non-archived WorkItem matches that identity
- **WHEN** the Evidence is persisted
- **THEN** the Evidence SHALL be attached to that WorkItem instead of only the project sync context item.

#### Scenario: Gap is ambiguous or unmapped

- **GIVEN** a detected closeout gap has no stable identity or matches multiple WorkItems
- **WHEN** the Evidence is persisted
- **THEN** the Evidence SHALL be attached to the project sync context WorkItem
- **AND** the summary or excerpt SHALL preserve enough local context for manual review.

#### Scenario: Connector unavailable evidence

- **GIVEN** a read-only connector returns an unavailable snapshot
- **WHEN** `/sync` persists project context
- **THEN** the assistant SHALL append local Evidence describing the unavailable connector
- **AND** it SHALL NOT interrupt CLI execution solely because that connector failed.

