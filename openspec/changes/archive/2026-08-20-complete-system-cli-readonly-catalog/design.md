## Context

The system CLI layer already has a catalog, cwd allowlist, no-shell execution, redacted/truncated summaries, `/system` commands, `run_system_cli`, Evidence recording, and Windows PATH shim resolution. The original design's first read-only catalog still lists two fixed keys that are not implemented: `openspec.validate` and `playbook.workspace_status`.

Both commands are useful for the assistant's local workflow facts:

- `openspec.validate` proves local OpenSpec changes and specs are structurally valid.
- `playbook.workspace_status` reads Playbook task state when the repository is attached to a Playbook workspace and degrades to a structured error otherwise.

## Goals / Non-Goals

**Goals:**
- Add the remaining fixed read-only stage-1 catalog keys.
- Keep the command surface catalog-only and no-shell.
- Preserve compact summaries for success and failure.
- Verify both slash command and LLM tool-call paths.

**Non-Goals:**
- Do not add parameterized commands.
- Do not add `local_write` or `external_write` policy.
- Do not run Git write commands, OpenSpec archive, Playbook mutation commands, deploy, or release flows.
- Do not require a configured Playbook workspace for the catalog key to be usable; a structured read-only failure is acceptable.

## Decisions

1. Use fixed argv for `openspec.validate`.
   - Chosen argv: `openspec validate --all --strict --json --no-interactive`.
   - Rationale: this covers changes and specs, avoids prompts, and returns machine-readable output that can be safely excerpted.
   - Rejected: `openspec validate <change>` because it requires parameters not yet supported by the catalog.

2. Use the existing connector argv for `playbook.workspace_status`.
   - Chosen argv: `playbook workspace task status --output json --full`.
   - Rationale: this matches the existing PlaybookConnector read path and is read-only.
   - Rejected: adding `--workspace-id` support because parameterized catalog entries need a separate design.

3. Keep failures as normal command records.
   - Playbook may return `WORKSPACE_ID_REQUIRED` when no workspace is configured. The catalog should report that as exit code and compact stderr/stdout excerpt, not as an exception.
   - Rationale: the system CLI layer describes local facts; "workspace not configured" is a useful fact.

## Risks / Trade-offs

- Playbook output can include structured errors on unconfigured repositories -> keep the command read-only, summarized, and non-fatal.
- `openspec.validate --all` can produce more output than single-change validation -> keep output limits and JSON/no-interactive flags.
- The catalog remains non-parameterized -> later per-change validation should be a separate, typed parameter design.
