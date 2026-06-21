## Why

Codex daily task reports already classify unfinished, blocked, and completed threads, but local WorkItems need an explicit completion sync contract so finished Codex work closes automatically without losing evidence or regressing active blockers.

This change makes Codex report ingestion authoritative enough for local workflow closeout while keeping ai-node decoupled from Codex internal storage.

## What Changes

- Import `completed` Codex report entries as local WorkItems with status `done`.
- Append completion signals and evidence from Codex reports as WorkItem Evidence.
- Make repeated `/sync` and `/codex tasks` imports idempotent for the same completion evidence.
- Define a status transition policy for `active`, `blocked`, and `done` WorkItems when later reports disagree.
- Extend `/sync` output with a Codex status-change summary for completed, blocked, reactivated, and unchanged items.
- Ensure completed Codex WorkItems appear in `/list completed`.
- Add `/sync --dry-run` so users can preview Codex status/evidence outcomes without writing local state.
- Add `/sync status` so users can inspect latest report metadata and local WorkItem status counts.
- Allow `/list completed --source codex` to focus the completed list on Codex-closed work.

## Capabilities

### New Capabilities

- `work-item-completion-sync`: Sync local WorkItem status and evidence from Codex report completion, blocker, and reactivation signals.

### Modified Capabilities

- `codex-task-report-ingestion`: Codex report ingestion now has observable WorkItem status side effects and idempotent evidence recording.
- `work-item-orchestration`: WorkItem state transitions now include Codex-driven completion, blocking, reactivation, and done anti-regression rules.
- `work-evidence-journal`: Evidence journal now accepts Codex completion signals as append-only, deduplicated snapshot evidence.

## Impact

- Affected code:
  - `src/ai_todo_assistant/application/workflow/codex_reports.py`
  - `src/ai_todo_assistant/application/workflow/services.py`
  - `src/ai_todo_assistant/presentation/cli.py`
  - workflow repository read/write paths under `src/ai_todo_assistant/infrastructure/persistence/`
  - `/list completed` rendering path if completed WorkItems are not already included
- Affected tests:
  - `tests/test_codex_task_reports.py`
  - `tests/test_workflow_services_cli.py`
  - `tests/test_workflow_sync_services.py`
- No external Codex storage reads, automation creation, Redmine updates, GitLab/MR actions, merge, or push are in scope.
