## Why

Codex daily reports and local workflow evidence can contain concrete closeout facts even when a task still appears in `unfinished` or `blocked`. Today ai-node only treats the Codex report `completed` array as the strong completion source. That leaves already-closed Codex, Git/MR, Redmine, OpenSpec, and Playbook work visible as unfinished until the upstream report is perfectly classified.

## What Changes

- Detect strong completion signals inside Codex report entries regardless of whether they arrive under `completed`, `unfinished`, or `blocked`.
- Recognize local evidence text for MR/PR merged, Redmine resolved/closed, OpenSpec archived or tasks complete, Playbook closeout verified, final validation passed, and Codex cleanup/merge/publish/writeback complete.
- Mark matching local WorkItems `done` when strong completion evidence is present.
- Preserve local `done` as sticky: later stale unfinished or blocked reports do not reopen the item.
- Record suspected reopen candidates in local result details and `/sync` summary instead of automatically reopening done items.
- Keep all writes local to WorkItem and Evidence records.

## Capabilities

### Modified Capabilities

- `work-item-completion-sync`: Expands Codex report import and sync summary behavior to use stronger local completion signal detection and reopen review candidates.

## Impact

- Affected code:
  - `src/ai_todo_assistant/application/workflow/services.py` for signal detection, status transitions, evidence, import result counters, and dry-run parity.
  - `src/ai_todo_assistant/presentation/cli.py` for `/sync` detail visibility if the existing detail rendering is insufficient.
  - Agent tool sync output may benefit from the same import result summary through existing service APIs.
- Affected tests:
  - `tests/test_workflow_sync_services.py` for report ingestion, signal detection, status transitions, done stickiness, and preview behavior.
  - `tests/test_workflow_services_cli.py` for `/sync` summary and reopen candidate visibility.
- Out of scope:
  - No Redmine, GitLab/MR, OpenSpec, Playbook, Codex, remote Git, or automation writeback.
  - No external system polling beyond already-existing local report and project snapshot inputs.
  - No automatic reopen command or external closeout action.
