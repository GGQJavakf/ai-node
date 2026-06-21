# workflow-source-connectors Specification

## Purpose
TBD - created by archiving change add-personal-workflow-orchestrator. Update Purpose after archive.
## Requirements
### Requirement: Read external workflow facts through existing tools

The assistant SHALL read external workflow facts by invoking existing local tools rather than implementing duplicate Redmine, GitLab, Playbook, or OpenSpec clients.

#### Scenario: Read Playbook Redmine issue

- **WHEN** the user imports a Redmine issue by id
- **THEN** the assistant SHALL invoke Playbook as the preferred source of Redmine issue facts
- **AND** it SHALL convert the result into a structured source snapshot.

#### Scenario: Read Playbook workspace task status

- **WHEN** the assistant synchronizes Playbook workspace context for a project path
- **THEN** it SHALL invoke Playbook read-only workspace task/status commands
- **AND** it SHALL expose active tasks, task progress, and workspace health as structured facts.

#### Scenario: Read Playbook closeout gaps

- **WHEN** the assistant synchronizes project context for a Playbook-managed workspace
- **THEN** it SHALL read Playbook closeout or closure gap facts with a dry-run/read-only command
- **AND** it SHALL expose those facts as structured source snapshots
- **AND** it SHALL label those facts as observations or recommendations, not completed actions.

#### Scenario: Read OpenSpec changes

- **WHEN** the assistant synchronizes OpenSpec context for a project path
- **THEN** it SHALL invoke `openspec list --json` and change-specific status commands
- **AND** it SHALL expose active change names, task progress, and artifact status as structured facts.

#### Scenario: Read OpenSpec apply instructions

- **WHEN** the assistant recommends implementation work for an active OpenSpec change
- **THEN** it SHALL read OpenSpec apply instructions when available
- **AND** it SHALL expose the next implementation guidance as structured facts without mutating OpenSpec files.

#### Scenario: Read Git status

- **WHEN** the assistant synchronizes Git context for a project path
- **THEN** it SHALL read the current branch and dirty status using local Git commands
- **AND** it SHALL return a structured summary without mutating the repository.

#### Scenario: Read Codex task report snapshots

- **WHEN** the assistant synchronizes Codex task context
- **THEN** it SHALL read the configured local report directory
- **AND** it SHALL NOT inspect or mutate Codex internal state directly.

#### Scenario: Read closeout context without external writes

- **WHEN** the assistant reads Redmine, MR, OpenSpec, Git, or Playbook facts for closeout context
- **THEN** it SHALL use existing read-only connectors or existing local snapshot files
- **AND** it SHALL NOT write Redmine, GitLab/MR, OpenSpec, Playbook, Git branches, time entries, or remote repositories.

### Requirement: Connector failures degrade to explicit unavailable snapshots

Connectors SHALL return explicit unavailable snapshots when commands are missing, fail, or return unparsable output.

#### Scenario: Missing external command

- **WHEN** a required command is not available on PATH
- **THEN** the connector SHALL return `success=false`
- **AND** the snapshot SHALL include a clear error message naming the missing command.

#### Scenario: Invalid JSON output

- **WHEN** a command expected to return JSON emits invalid JSON
- **THEN** the connector SHALL preserve a concise output excerpt
- **AND** it SHALL not raise an uncaught exception to the CLI or Agent loop.

#### Scenario: Closeout tool unavailable

- **WHEN** Playbook, OpenSpec, or Git is unavailable while synchronizing closeout context
- **THEN** the connector SHALL return `success=false`
- **AND** the snapshot SHALL include a concise error and output excerpt when available
- **AND** the CLI SHALL continue by persisting the unavailable snapshot as local Evidence instead of aborting the whole sync.

### Requirement: Connector operations are read-only

The first version of workflow connectors SHALL perform only read-only operations.

#### Scenario: Redmine import is requested

- **WHEN** the user runs `/work import redmine <id>`
- **THEN** the assistant SHALL read Redmine issue facts through Playbook
- **AND** it SHALL NOT write Redmine comments, update issue fields, or register time entries.

#### Scenario: Project sync reads closeout context

- **WHEN** the user runs `/sync [path]`
- **THEN** the assistant MAY run read-only Git, OpenSpec, and Playbook commands
- **AND** it SHALL NOT run Playbook `closeout --apply`, OpenSpec archive/sync mutation commands, GitLab/MR writes, Redmine writes, time logging, merge, finalize, cleanup, publish, or push commands.
