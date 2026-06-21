# assistant-command-surface Specification

## Purpose
TBD - created by archiving change simplify-assistant-command-surface. Update Purpose after archive.
## Requirements
### Requirement: Primary daily command surface is concise

The assistant SHALL present `/list`, `/sync`, `/next`, `/review`, and `/help` as the primary daily command set.

#### Scenario: User asks for help

- **WHEN** the user runs `/help`
- **THEN** the help output SHALL show the primary daily commands before categorized help topics
- **AND** it SHALL describe `/list` as the unified task view
- **AND** it SHALL describe `/sync` as the unified synchronization entry point
- **AND** it SHALL describe `/next` as the preferred next-action command
- **AND** it SHALL describe `/review` as the preferred daily review command
- **AND** it SHALL not expose Rich markup syntax as literal output.

#### Scenario: User starts the CLI

- **WHEN** the CLI startup panel is displayed
- **THEN** the startup panel SHALL show the primary daily commands before categorized help topics
- **AND** it SHALL not present `/continue` or `/review day` as the preferred daily commands.

### Requirement: Unified list command remains the task overview

The assistant SHALL keep `/list` as the unified task view for local Todo items and synchronized WorkItems.

#### Scenario: User runs the default list command

- **WHEN** the user runs `/list`
- **THEN** the assistant SHALL display the unified task view
- **AND** it SHALL preserve existing Todo and WorkItem list behavior.

#### Scenario: User runs list filters

- **WHEN** the user runs existing list filters such as `/list today`, `/list pending`, or `/list completed`
- **THEN** the assistant SHALL preserve the existing filter behavior.

### Requirement: Sync command remains the only manual synchronization entry point

The assistant SHALL keep `/sync` as the single manual command for synchronizing Codex report data and current project context.

#### Scenario: User runs sync

- **WHEN** the user runs `/sync` with or without a path
- **THEN** the assistant SHALL preserve existing synchronization behavior
- **AND** it SHALL not introduce a second synchronization command or background scheduler.

#### Scenario: Help describes synchronization

- **WHEN** the user reads `/help` or the startup panel
- **THEN** synchronization guidance SHALL point to `/sync`
- **AND** advanced source-specific commands such as `/codex tasks` SHALL remain available but not be presented as the primary sync path.

### Requirement: Next-action command has a preferred alias

The assistant SHALL support `/next` as the preferred command for recommending the next action.

#### Scenario: User runs next command

- **WHEN** the user runs `/next`
- **THEN** the assistant SHALL return the same next-action recommendation behavior as `/continue`.

#### Scenario: User runs legacy continue command

- **WHEN** the user runs `/continue`
- **THEN** the assistant SHALL preserve the existing next-action recommendation behavior
- **AND** it SHALL not fail or require migration.

### Requirement: Daily review command has a preferred alias

The assistant SHALL support bare `/review` as the preferred command for generating the daily review draft.

#### Scenario: User runs preferred review command

- **WHEN** the user runs `/review`
- **THEN** the assistant SHALL return the same daily review behavior as `/review day`.

#### Scenario: User runs legacy review day command

- **WHEN** the user runs `/review day`
- **THEN** the assistant SHALL preserve the existing daily review behavior
- **AND** it SHALL not fail or require migration.

### Requirement: Advanced commands remain discoverable and compatible

The assistant SHALL keep advanced and legacy commands available while grouping them below primary commands in help and completions.

#### Scenario: Help shows categorized advanced groups

- **WHEN** the user runs `/help`
- **THEN** advanced commands SHALL be discoverable through categorized help topics
- **AND** the topics SHALL include Todo management, workflow/evidence, preferences, and system/history commands when available.

#### Scenario: User opens workflow help

- **WHEN** the user runs `/help work`
- **THEN** workflow and evidence commands SHALL be listed
- **AND** compatibility commands such as `/continue` and `/review day` SHALL remain discoverable.

#### Scenario: Completion includes primary and compatible commands

- **WHEN** the user requests slash-command completions
- **THEN** completions SHALL include `/next`, `/review`, `/continue`, `/review day`, `/sync`, and `/list`
- **AND** completions SHALL include categorized help entries such as `/help todo`, `/help work`, `/help prefs`, and `/help system`
- **AND** legacy commands SHALL continue to resolve to their existing behavior.

### Requirement: Command surface preserves external-write safety boundaries

The simplified command surface SHALL not imply or perform external writes.

#### Scenario: User reads command guidance

- **WHEN** the user reads `/help` or the startup panel
- **THEN** the guidance SHALL avoid claiming that the assistant writes Redmine/GitLab/MR, logs time, merges, pushes, closes out, cleans up, or publishes.

#### Scenario: User runs command aliases

- **WHEN** the user runs `/next`, `/continue`, `/review`, or `/review day`
- **THEN** the assistant SHALL only recommend or draft local workflow output
- **AND** it SHALL not execute external write operations.

