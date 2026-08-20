## Why

The System CLI catalog can safely run read-only commands and return compact summaries, but the results still disappear after a single CLI/tool-call response. The assistant needs an explicit way to attach those already-redacted command summaries to WorkItem Evidence so closeout, review, and sync workflows can use command facts without copying raw stdout or stderr into LLM context.

## What Changes

- Add optional Evidence recording for `run_system_cli` tool calls through `record_evidence=true` and `work_item_id`.
- Add optional `/system run <key> [--cwd <path>] [--evidence <work-id>]` support for user-driven command evidence.
- Store only structured compact fields derived from `CommandExecutionRecord`: command text, redacted/truncated output excerpt, success, source, and short summary.
- Reuse existing matching Evidence for duplicate system CLI command results on the same WorkItem.
- Do not persist raw command stdout/stderr, arbitrary shell text, or unbounded output.

## Impact

- Affected code:
  - `src/ai_todo_assistant/application/system_cli/`
  - `src/ai_todo_assistant/application/agent/tool_models.py`
  - `src/ai_todo_assistant/application/agent/tool_definitions.py`
  - `src/ai_todo_assistant/application/agent/tool_executor.py`
  - `src/ai_todo_assistant/presentation/cli.py`
- Affected tests:
  - System CLI CLI and tool-call focused tests.
- Dependencies:
  - No new Python package dependency.
  - No database migration.
  - No external write operation.
