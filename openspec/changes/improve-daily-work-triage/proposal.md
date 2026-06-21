## Why

`/list` already combines Todo reminders and WorkItems, but the default view is still a flat table that does not answer the daily question "what should I handle first today?". Current local data is dominated by WorkItems from Codex reports, so the default view needs daily triage grouping, risk reasons, and stale sync markers without adding another daily command.

## What Changes

- Change default `/list` into a daily triage view that groups WorkItems and Todo reminders by actionability and delivery risk.
- Add default groups for blocked work, active work needing action, closeout waiting on MR/Redmine/OpenSpec, recently completed work, stale sync work, and lower-risk Todo reminders.
- Show a concise reason next to high-priority WorkItems, such as `blocked by Redmine`, `needs validation`, `MR merged but closeout missing`, or `Codex thread still active`.
- Mark WorkItems as `stale` when they have not been synced today.
- Rank delivery-risk WorkItems ahead of low-priority Todo reminders while still showing both Todo and WorkItem records.
- Preserve detailed filters such as `/list completed`, `/list pending`, `/list today`, and `/list completed --source codex`.
- Keep Redmine, GitLab/MR, OpenSpec, Playbook, and Codex external systems read-only.

## Capabilities

### New Capabilities

- `daily-work-triage`: Defines default `/list` daily grouping, WorkItem risk reasons, stale markers, WorkItem/Todo ordering, and compatibility with existing detailed filters.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `src/ai_todo_assistant/presentation/cli.py` for default `/list` rendering and compatibility with existing filters.
  - `src/ai_todo_assistant/application/workflow/services.py` for reusable WorkItem ranking, stale detection, and reason helpers if kept outside the CLI.
  - Existing workflow domain models are expected to remain compatible; no new persisted field is required unless implementation proves an existing field cannot represent the needed facts.
- Affected tests:
  - `tests/test_workflow_services_cli.py` for default list grouping, reasons, stale markers, Todo/WorkItem ordering, and existing completed filters.
  - Existing workflow sync tests remain relevant because stale and risk reasons depend on imported WorkItem metadata.
- No new daily command, no new automation, no external writes, no merge/push, and no Redmine/GitLab/MR writeback are in scope.
