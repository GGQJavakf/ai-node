## Context

`SystemCliService` already provides the execution policy for read-only commands. Extending the catalog with one fixed OpenSpec command is safer than adding a generic parameterized OpenSpec runner because it preserves the current boundary:

- stable command key
- fixed argv list
- `shell=False`
- cwd allowed-root checks
- redacted/truncated output summaries
- optional compact Evidence recording

## Decision

Add only `openspec.list` in this change.

The command uses:

```text
openspec list --json
```

This returns structured OpenSpec change state without modifying files. Parameterized commands such as `openspec validate <change> --strict` require an argument schema and should be handled in a later change.

## Non-Goals

- No arbitrary OpenSpec command execution.
- No `openspec archive` or other local writes.
- No external writes.
- No `/sync` behavior changes.
- No new tool name; existing `run_system_cli` can execute the new catalog key.
