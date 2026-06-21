## ADDED Requirements

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
