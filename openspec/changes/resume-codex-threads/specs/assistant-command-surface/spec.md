## MODIFIED Requirements

### Requirement: Sync command remains the only manual synchronization entry point

The assistant SHALL keep `/sync` as the single synchronization command family for synchronizing Codex report data and current project context.

#### Scenario: User runs sync

- **WHEN** the user runs `/sync` with or without a path
- **THEN** the assistant SHALL preserve existing synchronization behavior
- **AND** it SHALL not introduce a second synchronization command family.

#### Scenario: User runs sync watch

- **WHEN** the user runs `/sync watch`
- **THEN** the assistant SHALL periodically trigger the existing sync workflow
- **AND** it SHALL print a timestamped report for each trigger
- **AND** it SHALL include the next recommended action after each trigger
- **AND** it SHALL stop cleanly when interrupted.

#### Scenario: User runs sync watch with resume

- **WHEN** the user runs `/sync watch --resume`
- **THEN** the assistant SHALL periodically trigger the existing sync workflow
- **AND** it SHALL run Codex resume after each trigger only for safe candidates
- **AND** it SHALL print sync and resume results for each trigger.

#### Scenario: Help describes synchronization

- **WHEN** the user reads `/help` or the startup panel
- **THEN** synchronization guidance SHALL point to `/sync`
- **AND** Codex continuation guidance SHALL point to short `/r` commands instead of long source-specific command paths.

### Requirement: Command surface preserves external-write safety boundaries

The simplified command surface SHALL not imply or perform external writes except explicitly requested Codex thread resume through a configured resume client.

#### Scenario: User reads command guidance

- **WHEN** the user reads `/help` or the startup panel
- **THEN** the guidance SHALL avoid claiming that the assistant writes Redmine/GitLab/MR, logs time, merges, pushes, closes out, cleans up, or publishes.

#### Scenario: User runs command aliases

- **WHEN** the user runs `/next`, `/continue`, `/review`, or `/review day`
- **THEN** the assistant SHALL only recommend or draft local workflow output
- **AND** it SHALL not execute external write operations.

#### Scenario: User runs Codex resume shortcut

- **WHEN** the user runs `/r <序号>` or `/r all`
- **THEN** the assistant SHALL only send Codex continuation prompts through the configured resume client
- **AND** it SHALL not write Redmine/GitLab/MR, log time, merge, push, publish, deploy, or modify production systems.
