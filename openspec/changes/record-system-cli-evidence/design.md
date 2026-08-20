## Context

`SystemCliService` already enforces the command catalog, allowed roots, no-shell execution, redaction, truncation, and compact formatting. Existing workflow code already has `EvidenceService` and WorkItem Evidence timelines.

The new behavior should connect those two surfaces without weakening either boundary.

## Decisions

### Evidence recording stays outside `SystemCliService`

`SystemCliService` remains responsible for command execution policy and safe summaries only. ToolExecutor and CLI orchestration decide whether to attach the command result to a WorkItem.

### Evidence uses compact derived fields

Evidence fields are derived from `CommandExecutionRecord`:

- `summary`: `system_cli <command_key> <outcome> (exit_code=<code>)`
- `command`: joined fixed argv from the catalog
- `output_excerpt`: `stdout_excerpt` or `stderr_excerpt`, already redacted/truncated
- `success`: command success flag
- `source`: `system-cli`

Raw stdout/stderr is never stored by this path.

### Tool-call recording requires an explicit WorkItem

`record_evidence=true` requires `work_item_id`. This prevents accidental side effects where a model asks for evidence recording but the runtime cannot determine the destination.

### Duplicate evidence is reused

For the same WorkItem, system CLI Evidence is reused when `evidence_type`, `source`, `command`, `output_excerpt`, and `success` match. This keeps repeated status checks from polluting timelines while preserving different outputs or failures as separate facts.

## Non-Goals

- No arbitrary command execution.
- No shell strings.
- No raw long stdout/stderr persistence.
- No automatic WorkItem inference.
- No external Redmine, GitLab, GitHub, Playbook, push, merge, or deployment writes.
