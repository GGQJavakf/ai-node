## ADDED Requirements

### Requirement: Local WorkItem records personal workflow context

The assistant SHALL persist local WorkItem records that represent the user's active work items and their personal execution context.

#### Scenario: Create manual work item

- **WHEN** the user creates a manual work item
- **THEN** the assistant SHALL persist title, status, priority, next action, project path, and timestamps.

#### Scenario: Create manual work item from CLI or Agent

- **WHEN** the user runs `/work add <title>` or asks the Agent to create a work item
- **THEN** the assistant SHALL create a WorkItem with source `manual`
- **AND** it SHALL return the WorkItem id for later status, evidence, and continuation commands.

#### Scenario: Import Redmine work item

- **WHEN** the user imports a Redmine issue
- **THEN** the assistant SHALL create or update a WorkItem with source `redmine`
- **AND** it SHALL store the issue id as `source_ref`
- **AND** it SHALL keep the external issue facts as a sync summary, not as the authoritative issue copy.

### Requirement: Work status summarizes local and synchronized facts

The assistant SHALL provide a work status view that combines local WorkItem state with recent connector snapshots.

#### Scenario: List active work items

- **WHEN** the user runs `/work status`
- **THEN** the assistant SHALL show active WorkItems ordered by priority, status, and recency
- **AND** each item SHALL show source, project path, next action, and last sync time.

#### Scenario: Work item has stale sync data

- **WHEN** a WorkItem has external source data older than the configured stale threshold
- **THEN** the status view SHALL mark the sync data as stale
- **AND** it SHALL suggest running `/sync`.

### Requirement: Continue recommendation selects a next action

The assistant SHALL recommend a concrete next action from active WorkItems and available evidence.

#### Scenario: Active work item has next action

- **WHEN** the user runs `/continue`
- **THEN** the assistant SHALL choose the highest-priority unclosed WorkItem with a concrete next action
- **AND** it SHALL explain why that action is recommended.

#### Scenario: No active work item exists

- **WHEN** the user runs `/continue` and no active WorkItems exist
- **THEN** the assistant SHALL say no active workflow item is available
- **AND** it SHALL suggest importing or creating one.
