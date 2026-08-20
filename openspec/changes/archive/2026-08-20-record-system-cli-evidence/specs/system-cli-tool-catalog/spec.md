# system-cli-tool-catalog Specification Delta

## ADDED Requirements

### Requirement: System CLI results can be recorded as WorkItem Evidence

The assistant SHALL allow callers to explicitly record a catalog command result as WorkItem Evidence without storing raw stdout or stderr.

#### Scenario: User records command evidence from slash command

- **WHEN** the user runs `/system run git.status --evidence <work-id>`
- **THEN** the assistant SHALL execute the catalog command under the existing System CLI policy
- **AND** it SHALL append command Evidence to the specified WorkItem
- **AND** the Evidence SHALL include source `system-cli`, command text, success flag, short summary, and redacted/truncated output excerpt.

#### Scenario: LLM tool call records command evidence

- **WHEN** the LLM emits `run_system_cli` with `command_key`, `record_evidence=true`, and `work_item_id`
- **THEN** local validation SHALL accept the arguments
- **AND** the tool executor SHALL append or reuse compact command Evidence for that WorkItem
- **AND** the tool result SHALL still return only the compact system CLI summary and Evidence status.

#### Scenario: LLM requests evidence without a WorkItem

- **WHEN** the LLM emits `run_system_cli` with `record_evidence=true` and no `work_item_id`
- **THEN** local validation SHALL reject the tool call before command execution.

#### Scenario: Duplicate system CLI evidence is requested

- **WHEN** the same WorkItem already has system CLI Evidence with the same command, output excerpt, and success flag
- **THEN** the assistant SHALL reuse the existing Evidence
- **AND** it SHALL not append a duplicate Evidence row.

#### Scenario: Long command output is recorded

- **WHEN** command output exceeds the configured excerpt limit
- **THEN** the Evidence output excerpt SHALL use the redacted/truncated excerpt from `CommandExecutionRecord`
- **AND** raw full stdout or stderr SHALL NOT be stored by this path.
