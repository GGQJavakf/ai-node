# system-cli-tool-catalog Specification Delta

## ADDED Requirements

### Requirement: OpenSpec change listing is available as a read-only catalog command

The assistant SHALL expose an `openspec.list` command key that reads OpenSpec change state without allowing arbitrary OpenSpec command execution.

#### Scenario: User lists catalog commands

- **WHEN** the user runs `/system list`
- **THEN** the assistant SHALL include `openspec.list`
- **AND** it SHALL describe the command as a read-only OpenSpec change listing command.

#### Scenario: User runs OpenSpec list command

- **WHEN** the user runs `/system run openspec.list`
- **THEN** the assistant SHALL execute the fixed argv `openspec list --json`
- **AND** it SHALL use the existing System CLI no-shell execution path
- **AND** it SHALL return only the compact redacted/truncated command summary.

#### Scenario: LLM tool call runs OpenSpec list command

- **WHEN** the LLM emits `run_system_cli` with `command_key` set to `openspec.list`
- **THEN** local validation and policy SHALL route the command through the existing read-only catalog path
- **AND** the model SHALL NOT be able to provide arbitrary OpenSpec subcommands or shell text.
