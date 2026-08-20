# Add Sync Watch

## Why

Multiple Codex development threads may pause after an intermediate phase even when the next step is safe to continue. `ai-node` already reads Codex task reports and synchronizes local WorkItems through `/sync`, but the user still has to trigger that flow manually. A lightweight local watch mode should periodically run the same sync path and report each trigger result.

## What Changes

- Add a scheduled local watch mode for `/sync` that repeatedly triggers the existing sync workflow at a configured interval.
- Print a timestamped report for every trigger, including Codex import status, project snapshot status, and the next recommended action.
- Keep external systems read-only: the watch mode only consumes local report files and existing read-only project snapshots.
- Keep `/sync` as the single synchronization behavior; watch mode is a wrapper around that behavior, not a separate source ingestion path.

## Out of Scope

- Directly inspecting Codex internal session storage.
- Sending messages to Codex threads from inside `ai-node`.
- Writing Redmine/GitLab/MR, merge, push, publish, deploy, or production changes.
- Creating a persistent OS service or Windows Task Scheduler entry.

## Impact

- CLI users can run a long-lived local watch command when they want periodic summaries.
- Existing `/sync`, `/codex tasks`, `/list`, `/next`, and `/review` behavior remains compatible.
