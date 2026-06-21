# work-item-completion-sync Specification

## Purpose
TBD - created by archiving change automate-work-item-completion-sync. Update Purpose after archive.
## Requirements
### Requirement: Codex completed entries close local WorkItems

The assistant SHALL mark a local Codex WorkItem as `done` when the latest Codex report contains a matching entry in `completed`.

#### Scenario: Existing unfinished thread becomes completed

- **GIVEN** a local WorkItem with source `codex`, source reference `thread-1`, and status `active`
- **WHEN** the latest Codex report contains `thread-1` under `completed`
- **THEN** the assistant SHALL update the WorkItem status to `done`
- **AND** it SHALL preserve the source reference and title.

#### Scenario: Completed report entry has no prior WorkItem

- **GIVEN** no local WorkItem exists for Codex source reference `thread-new`
- **WHEN** the latest Codex report contains `thread-new` under `completed`
- **THEN** the assistant SHALL create a WorkItem with source `codex`
- **AND** it SHALL set the WorkItem status to `done`.

### Requirement: Completion evidence is appended idempotently

The assistant SHALL append Codex completion signals and evidence to the WorkItem Evidence journal without duplicating the same evidence on repeated imports.

#### Scenario: Completion signals are recorded as evidence

- **GIVEN** a Codex completed entry contains `completion_signals`
- **WHEN** the assistant imports the report
- **THEN** it SHALL append Evidence with source `codex`
- **AND** the Evidence summary SHALL include the completion signal text.

#### Scenario: Same report is synced twice

- **GIVEN** a WorkItem already has Evidence for a Codex completion signal
- **WHEN** the same report is imported again
- **THEN** the assistant SHALL NOT append a duplicate Evidence record for that same signal.

#### Scenario: New completion signal arrives later

- **GIVEN** a WorkItem already has Evidence for one Codex completion signal
- **WHEN** a later report contains a different completion signal for the same completed WorkItem
- **THEN** the assistant SHALL append the new distinct Evidence record.

#### Scenario: User reviews evidence in chronological order

- **GIVEN** a WorkItem has multiple Evidence records from different sources
- **WHEN** the user runs `/work evidence timeline <work-id>`
- **THEN** the output SHALL list Evidence in chronological order
- **AND** each row SHALL include timestamp, evidence type, source, outcome, summary, and command when available.

### Requirement: Codex sync applies deterministic status transitions

The assistant SHALL use a deterministic state machine when Codex reports classify a WorkItem as unfinished, blocked, or completed.

#### Scenario: Blocked item becomes active again

- **GIVEN** a local Codex WorkItem has status `blocked`
- **WHEN** the latest Codex report contains the same source reference under `unfinished`
- **THEN** the assistant SHALL update the WorkItem status to `active`.

#### Scenario: Active item becomes blocked

- **GIVEN** a local Codex WorkItem has status `active`
- **WHEN** the latest Codex report contains the same source reference under `blocked`
- **THEN** the assistant SHALL update the WorkItem status to `blocked`.

#### Scenario: Done item appears unfinished later

- **GIVEN** a local Codex WorkItem has status `done`
- **WHEN** a later Codex report contains the same source reference under `unfinished` or `blocked`
- **THEN** the assistant SHALL keep the WorkItem status as `done`
- **AND** it SHALL NOT reopen or downgrade the WorkItem automatically.

#### Scenario: Entry appears in multiple report sections

- **GIVEN** the same source reference appears in multiple sections of one Codex report
- **WHEN** one section is `completed`
- **THEN** the assistant SHALL apply the `completed` state before `blocked` or `unfinished`.

### Requirement: Sync output summarizes actual status changes

The assistant SHALL report actual Codex WorkItem sync outcomes in `/sync` output.

#### Scenario: Sync changes multiple Codex WorkItem statuses

- **WHEN** `/sync` imports a Codex report that completes one item, blocks one item, reactivates one item, and leaves one item unchanged
- **THEN** the output SHALL include counts for `completed`, `blocked`, `reactivated`, and `unchanged`.

#### Scenario: Repeated sync is idempotent

- **GIVEN** a report has already been imported
- **WHEN** `/sync` imports it again
- **THEN** status-change counts SHALL show no repeated completion transition for already-closed items
- **AND** unchanged count SHALL include unchanged imported items.

### Requirement: Completed Codex WorkItems are visible in completed list

The assistant SHALL include done WorkItems created or updated by Codex completion sync in completed task listings.

#### Scenario: User lists completed work

- **GIVEN** a Codex WorkItem was marked `done` by report sync
- **WHEN** the user runs `/list completed`
- **THEN** the completed list SHALL include that WorkItem title
- **AND** it SHALL identify the item as a Codex-sourced work item.

#### Scenario: User filters completed work by Codex source

- **GIVEN** completed WorkItems exist from multiple sources
- **WHEN** the user runs `/list completed --source codex`
- **THEN** the completed list SHALL include Codex-sourced done WorkItems
- **AND** it SHALL exclude completed WorkItems from other sources.

### Requirement: Sync preview is non-mutating

The assistant SHALL support a dry-run sync mode that previews Codex report outcomes without writing WorkItems, Evidence, or project sync snapshots.

#### Scenario: User previews a completion sync

- **GIVEN** a local Codex WorkItem is currently `active`
- **AND** the latest Codex report would mark it `done`
- **WHEN** the user runs `/sync --dry-run <path>`
- **THEN** the output SHALL summarize the expected completion outcome
- **AND** it SHALL state that no writes were performed
- **AND** the local WorkItem status SHALL remain `active`
- **AND** no completion Evidence SHALL be appended.

### Requirement: Sync status explains local sync health

The assistant SHALL provide a read-only `/sync status` view for local sync health.

#### Scenario: User checks sync status

- **GIVEN** local WorkItems and a latest Codex report exist
- **WHEN** the user runs `/sync status`
- **THEN** the output SHALL show the latest Codex report path and generation time
- **AND** it SHALL show local WorkItem counts by status
- **AND** it SHALL show the most recent WorkItem sync timestamp when one exists.

