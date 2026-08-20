## Why

The system CLI design identifies OpenSpec state as one of the first read-only facts the assistant should be able to inspect. The current catalog covers Git state, but it does not yet expose the read-only OpenSpec change list through the same safe command boundary.

## What Changes

- Add `openspec.list` to the read-only System CLI catalog.
- Map `openspec.list` to the fixed argv `openspec list --json`.
- Keep execution under the existing catalog-only, allowed-root, no-shell, redaction, truncation, and optional Evidence rules.
- Do not add parameterized OpenSpec validation, OpenSpec archive, local writes, external writes, or automatic `/sync` writes in this slice.

## Impact

- Affected code:
  - `src/ai_todo_assistant/application/system_cli/catalog.py`
- Affected tests:
  - System CLI service and CLI focused tests.
- Dependencies:
  - No new Python package dependency.
  - No database migration.
  - No external write operation.
