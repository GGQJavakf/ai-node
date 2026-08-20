## Why

`ai-node` needs a safe way to let the assistant inspect local project state through system CLI commands. The current code already has tool-call validation, a Reactor loop, workflow connectors, and a no-shell `CommandRunner`, but there is no common user-facing or LLM-facing command catalog. Without a catalog, adding CLI execution would either duplicate connector logic or risk exposing arbitrary shell execution.

## What Changes

- Add a read-only System CLI command catalog with stable command keys.
- Add a small application service that validates command keys, enforces cwd boundaries, runs commands through `CommandRunner`, redacts and truncates output, and returns compact summaries.
- Add `/system list`, `/system policy`, and `/system run <key> [--cwd <path>]` as advanced slash commands.
- Add `run_system_cli` as an LLM tool-call entry that can execute only read-only catalog commands.
- Keep `/sync`, `/list`, `/next`, `/review`, and `/help` as the primary daily command surface.
- Do not add arbitrary shell execution, external writes, Git writes, Playbook apply operations, Redmine writes, GitLab writes, pushes, merges, or cleanup actions.

## Capabilities

### New Capabilities

- `system-cli-tool-catalog`: Defines safe read-only command catalog behavior, command execution summaries, slash-command access, tool-call access, output safety, and command-surface compatibility.

### Modified Capabilities

- `assistant-command-surface`: Advanced system commands remain discoverable through `/help system`, but they do not become primary daily commands.

## Impact

- Affected code:
  - `src/ai_todo_assistant/application/system_cli/` new application package.
  - `src/ai_todo_assistant/application/agent/tool_models.py`
  - `src/ai_todo_assistant/application/agent/tool_definitions.py`
  - `src/ai_todo_assistant/application/agent/tool_executor.py`
  - `src/ai_todo_assistant/presentation/cli.py`
- Affected tests:
  - New focused system CLI service, tool-call, and CLI tests.
  - Existing tool validation and command surface tests should continue to pass.
- Dependencies:
  - No new Python package dependency.
  - No database migration.
  - No external API or external write operation.
