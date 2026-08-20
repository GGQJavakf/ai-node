## Why

The system CLI design lists `openspec.validate` and `playbook.workspace_status` as first-phase read-only catalog commands, but the current catalog exposes only Git commands and `openspec.list`. Completing these fixed read-only keys makes the CLI/tool-call surface useful for local verification and workspace status checks without expanding into arbitrary shell execution or write operations.

## What Changes

- Add fixed read-only catalog key `openspec.validate` for strict, non-interactive OpenSpec validation across changes and specs.
- Add fixed read-only catalog key `playbook.workspace_status` for Playbook workspace task status snapshots.
- Keep both keys available through `/system run <key>` and `run_system_cli`.
- Preserve existing policy boundaries: no shell strings, no custom argv, no local writes, no external writes, compact redacted output only.
- Preserve degraded summaries for missing commands, invalid JSON, and Playbook workspace configuration errors.

## Capabilities

### New Capabilities
- `system-cli-tool-catalog`: Additional fixed read-only catalog keys for OpenSpec validation and Playbook workspace status.

### Modified Capabilities

## Impact

- `src/ai_todo_assistant/application/system_cli/catalog.py`
- System CLI service/CLI/tool-call tests
- No database migration, no production configuration, no external write, no Git write operation.
