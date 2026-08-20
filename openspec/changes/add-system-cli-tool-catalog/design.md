## Overview

This change introduces a constrained System CLI layer. The assistant does not receive a shell. It receives a small catalog of read-only command keys, and application code turns those keys into `argv` lists executed by the existing `CommandRunner` with `shell=False`.

The implementation is intentionally small: it proves the end-to-end chain from slash command and LLM tool call to policy-checked execution and compact output. Evidence persistence and local write commands are left for later changes.

## Architecture

```text
TodoCLI /system command
  -> SystemCliService
  -> CommandCatalog
  -> cwd policy
  -> CommandRunner
  -> CommandExecutionRecord
  -> compact CLI text

LLM tool call run_system_cli
  -> validate_tool_calls
  -> RunSystemCliArgs
  -> ToolExecutor
  -> SystemCliService
  -> compact role=tool text
```

## Command Catalog

The first catalog contains only read-only Git commands because they are universally available in this repository and have stable, testable output:

| key | argv | risk |
| --- | --- | --- |
| `git.branch` | `git branch --show-current` | `read_only` |
| `git.status` | `git status --short` | `read_only` |
| `git.diff_stat` | `git diff --stat` | `read_only` |

Each command has a stable key, title, description, argv list, timeout, risk level, and output limit. Later changes can add OpenSpec or Playbook keys after their output parsing and timeout behavior are specified.

## Policy

The service enforces these checks before execution:

- The command key must exist in the catalog.
- The command risk must be `read_only`.
- The cwd must resolve to an existing path.
- The cwd must stay under one of the allowed roots. The default allowed root is the configured `project_root`; if that is absent, the process cwd is used.
- Commands are executed as `list[str]` with `shell=False`.

Policy rejections return a `CommandExecutionRecord` with `policy_decision="denied"` and a human-readable reason. They do not raise into the Reactor loop.

## Output Safety

The service never returns raw full stdout/stderr to the LLM or CLI formatter. It applies:

1. Redaction for common secret-bearing patterns such as `Authorization: Bearer ...`, `password=...`, `token=...`, `api_key=...`, and private-key blocks.
2. Truncation with an explicit marker showing how many characters were omitted.
3. A compact summary generated from command key, success, exit code, line counts, and the excerpt.

This change does not persist full artifacts. If future work needs full logs, it should store them as local artifact files and place only paths and hashes in Evidence.

## Tool Call Behavior

The LLM tool is named `run_system_cli`. Its arguments are:

- `command_key`: required catalog key.
- `cwd`: optional working directory.
- `reason`: optional short reason for traceability.

Unknown command keys are rejected by the service, not executed. Validation still rejects blank or unknown top-level tool fields before execution.

## CLI Behavior

`/system` is an advanced command group:

- `/system list` lists available command keys.
- `/system policy` explains allowed roots and read-only policy.
- `/system run <key> [--cwd <path>]` runs a read-only command and returns a compact summary.

`/system` is discoverable through `/help system` and command completion, but it does not change the primary daily command set.

## Compatibility

- Existing `/sync`, `/list`, `/next`, `/review`, `/continue`, `/review day`, `/help`, and workflow commands keep their behavior.
- Existing workflow connectors keep using `CommandRunner`; this change does not migrate them.
- No external writes are introduced.
- No database schema changes are introduced.
