# system-cli-tool-catalog Specification

## Purpose

Provide a safe, read-only system CLI command catalog that can be used from advanced slash commands and LLM tool calls without exposing arbitrary shell execution or long raw command output.

## ADDED Requirements

### Requirement: System CLI commands are catalog based

The assistant SHALL expose only predefined read-only command keys for system CLI execution.

#### Scenario: User lists available commands

- **WHEN** the user runs `/system list`
- **THEN** the assistant SHALL list available command keys
- **AND** each listed command SHALL include a short description
- **AND** the list SHALL include `git.branch`, `git.status`, and `git.diff_stat`.

#### Scenario: Unknown command is requested

- **WHEN** a user or tool call requests a command key that is not in the catalog
- **THEN** the assistant SHALL not execute a process
- **AND** it SHALL return a policy rejection message.

### Requirement: System CLI execution is read-only and no-shell

System CLI commands SHALL execute through fixed `argv` lists and SHALL not expose arbitrary shell strings.

#### Scenario: Catalog command is executed

- **WHEN** the user runs `/system run git.status`
- **THEN** the assistant SHALL execute the catalog command for `git.status`
- **AND** it SHALL use `shell=False`
- **AND** it SHALL return exit code and compact output excerpt.

#### Scenario: Command cwd is outside allowed roots

- **WHEN** a user or tool call provides a cwd outside the configured allowed roots
- **THEN** the assistant SHALL reject the command
- **AND** it SHALL not execute a process.

### Requirement: System CLI output is compact and redacted

The assistant SHALL not return complete raw stdout or stderr to LLM tool results or CLI summaries.

#### Scenario: Command output contains a secret

- **WHEN** stdout or stderr contains a bearer token, password, API key, token, secret, cookie, or private key block
- **THEN** the assistant SHALL redact that value before returning an excerpt.

#### Scenario: Command output is long

- **WHEN** stdout or stderr exceeds the configured excerpt limit
- **THEN** the assistant SHALL truncate the output
- **AND** it SHALL include a truncation marker.

### Requirement: LLM tool call can run catalog commands

The assistant SHALL provide a `run_system_cli` tool that accepts only structured arguments and executes only catalog commands.

#### Scenario: LLM requests a valid command key

- **WHEN** the LLM emits a `run_system_cli` tool call with `command_key` set to `git.status`
- **THEN** local validation SHALL accept the arguments
- **AND** the tool executor SHALL return a compact system CLI summary.

#### Scenario: LLM provides blank command key

- **WHEN** the LLM emits a `run_system_cli` tool call with a blank `command_key`
- **THEN** local validation SHALL reject the tool call before execution.

### Requirement: System CLI remains an advanced command group

The assistant SHALL keep `/system` commands discoverable without making them part of the primary daily command set.

#### Scenario: User reads system help

- **WHEN** the user runs `/help system`
- **THEN** the assistant SHALL include `/system list`, `/system policy`, and `/system run <key>`
- **AND** the main daily command set SHALL still prioritize `/list`, `/sync`, `/next`, `/review`, and `/help`.
