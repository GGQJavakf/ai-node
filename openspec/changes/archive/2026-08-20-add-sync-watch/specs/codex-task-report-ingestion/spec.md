## ADDED Requirements

### Requirement: Local scheduled trigger reports each sync result

The assistant SHALL support a local scheduled trigger that repeatedly consumes the configured Codex task report directory through the existing sync workflow and reports every trigger result to the user.

#### Scenario: Watch trigger runs

- **WHEN** the local watch trigger fires
- **THEN** the assistant SHALL import the latest Codex report through the same path as `/sync`
- **AND** it SHALL synchronize read-only project context through the same path as `/sync`
- **AND** it SHALL print the trigger timestamp, sync result, and next recommended action.

#### Scenario: No Codex report exists

- **WHEN** the watch trigger fires and no Codex report exists
- **THEN** the assistant SHALL print the configured report directory in the trigger report
- **AND** it SHALL continue watching unless interrupted.

#### Scenario: Watch interval is configured

- **WHEN** the user does not provide an explicit watch interval
- **THEN** the assistant SHALL use the configured `sync_watch_interval_seconds`
- **AND** it SHALL allow the interval to be overridden by environment configuration.
