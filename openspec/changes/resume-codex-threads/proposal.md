# Resume Codex Threads

## Why

`/sync watch` can keep local WorkItems current, but it still stops at reporting. Some Codex development threads pause after a safe intermediate step even though their latest report already contains enough information to continue. The assistant should be able to resume only those explicitly continueable threads and report what happened, while preserving the existing manual and external-write safety boundaries.

## What Changes

- Add a Codex thread resume workflow that reads the latest Codex task report and selects only entries marked as safe to continue.
- Add short `/r` and `/resume` commands for listing, indexed targeting, bulk resume, and manual skip/unskip.
- Add persistent manual exclusions so selected Codex threads are skipped by bulk and watch auto-resume until explicitly included again.
- Record every attempted resume as local Evidence against the matching Codex WorkItem.
- Allow `/sync watch --resume` to run the existing sync trigger and then resume safe candidates each cycle.
- Keep the actual Codex thread sender behind an injectable client so local tests and future Codex app bridges can use the same service without coupling to Codex internal storage.

## Out of Scope

- Inspecting Codex internal session storage directly.
- Resuming blocked, completed, ambiguous, missing-thread-id, or user-input-required threads.
- Writing Redmine/GitLab/MR, logging time, merging, pushing, publishing, deploying, or modifying production systems.
- Creating a persistent OS scheduler or Windows Task Scheduler entry.
- Claiming full Codex app integration when no resume client is configured.

## Impact

- Users can preview and trigger continuation for safe Codex paused threads from `ai-node` with short indexed commands.
- Existing `/sync`, `/sync watch`, `/codex tasks`, `/list`, `/next`, and `/review` behavior remains compatible.
- Deployments without a configured Codex thread client fail closed with a local report instead of attempting unsafe work.
