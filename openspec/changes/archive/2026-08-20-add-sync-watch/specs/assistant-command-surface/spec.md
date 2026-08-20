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

#### Scenario: Help describes synchronization

- **WHEN** the user reads `/help` or the startup panel
- **THEN** synchronization guidance SHALL point to `/sync`
- **AND** advanced source-specific commands such as `/codex tasks` SHALL remain available but not be presented as the primary sync path.

### Requirement: Command surface preserves external-write safety boundaries

The simplified command surface SHALL not imply or perform external writes.

#### Scenario: User reads command guidance

- **WHEN** the user reads `/help` or the startup panel
- **THEN** the guidance SHALL avoid claiming that the assistant writes Redmine/GitLab/MR, logs time, merges, pushes, closes out, cleans up, or publishes.

#### Scenario: User runs command aliases

- **WHEN** the user runs `/next`, `/continue`, `/review`, or `/review day`
- **THEN** the assistant SHALL only recommend or draft local workflow output
- **AND** it SHALL not execute external write operations.

#### Scenario: User runs sync watch

- **WHEN** the user runs `/sync watch`
- **THEN** every trigger SHALL use the same local/read-only external boundaries as `/sync`
- **AND** it SHALL not write Redmine/GitLab/MR, log time, merge, push, publish, deploy, or modify production systems.
