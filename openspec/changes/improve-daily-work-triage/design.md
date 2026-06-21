## Context

`docs/DAILY_WORK_ASSISTANT_ROADMAP.md` identifies daily triage as the next high-priority improvement. The current `/list` path in `TodoCLI._handle_list_command()` already reads Todos from the Todo repository and WorkItems from the workflow repository. WorkItems already carry status, source refs, source identities, merge conflicts, next actions, sync summaries, `last_synced_at`, and completion state, which is enough to derive daily grouping and reason text without a schema migration.

## Goals / Non-Goals

Goals:

- Make bare `/list` answer "what should I handle first today?".
- Show both WorkItems and Todo reminders in one default view.
- Put delivery-risk WorkItems ahead of low-priority Todo reminders.
- Make urgency explainable with short risk reasons and stale markers.
- Preserve existing detailed filters and source filters.

Non-goals:

- Do not add a new daily command.
- Do not read or write Redmine, GitLab/MR, OpenSpec, Playbook, or Codex during `/list`.
- Do not merge Todo and WorkItem storage.
- Do not implement richer completion detection from external systems; that belongs to later changes such as `strengthen-completion-signal-detection` and `add-readonly-closeout-context`.
- Do not introduce preference-backed ranking or long-term memory compression.

## Daily Triage Model

Bare `/list` is the only command whose default behavior changes. It should return a daily triage table or equivalent Rich renderable with these group labels:

1. `blocked`
2. `active needs action`
3. `waiting closeout`
4. `recently completed`
5. `stale sync`
6. `todo reminders`

The implementation may omit an empty group from the rendered output, but tests should prove the expected group label appears when matching data exists.

Existing detailed filters keep their current semantics:

- `/list completed` shows completed Todos and done WorkItems.
- `/list completed --source codex` shows only done Codex WorkItems.
- `/list pending`, `/list today`, `/list week`, `/list month`, `/list overdue`, and `/list upcoming` keep Todo-focused filtering and may continue to suppress WorkItems when the filter is time-specific.
- `--source todo` suppresses WorkItems, and other `--source <source>` filters suppress Todos.

## Sorting Rules

The default triage order is group-first, then item priority, then recency:

1. `blocked` WorkItems.
2. `active needs action` WorkItems with `next_action`, merge conflicts, or validation-like summary text.
3. `waiting closeout` WorkItems where local text or identities indicate MR/Redmine/OpenSpec closeout remains.
4. High and medium priority Todo reminders that are overdue, due today, or upcoming.
5. `stale sync` active or blocked WorkItems not synced today and not already displayed in a higher group.
6. `recently completed` done WorkItems, limited to a small recent slice.
7. Remaining low-priority Todo reminders.

Within a group:

- Priority order is `high`, `medium`, `low`.
- Blocked items rank before active items when they otherwise tie.
- More recently updated WorkItems rank before older WorkItems.
- Todo reminders rank by overdue first, then priority, then due time, then created time.

If an item matches multiple WorkItem groups, it appears only in the highest-ranked group and keeps the most actionable reason.

## Risk Reasons

Default `/list` must show a short reason for high-priority or delivery-risk WorkItems. Reason text is derived from local fields only:

- `blocked by Redmine`: status is blocked and source refs or identities contain `redmine`, or text mentions Redmine.
- `blocked by MR`: status is blocked and source refs, identities, title, next action, or sync summary mention MR/GitLab.
- `blocked by OpenSpec`: status is blocked and source refs, identities, title, next action, or sync summary mention OpenSpec.
- `needs validation`: next action or sync summary mentions validation, verify, test, unittest, review, or acceptance evidence.
- `MR merged but closeout missing`: title, next action, sync summary, source refs, or identities mention a merged MR and closeout still missing.
- `Redmine closeout missing`: text mentions Redmine and closeout/closed-loop/resolution is still pending.
- `OpenSpec closeout missing`: text mentions OpenSpec and archive/validate/tasks closeout remains.
- `Codex thread still active`: source is Codex or identities include a Codex thread and status is active.
- `merge conflict needs manual resolution`: `merge_conflicts` is not empty.
- `sync stale`: WorkItem did not sync today.

If multiple reasons match, pick the first reason from the list above. If no reason matches but the item is still shown in a risk group, use `needs action` for active items and `blocked` for blocked items.

## Stale Marker

A WorkItem is stale for the default `/list` when:

- `last_synced_at` is missing, invalid, or earlier than the local current date.
- The item status is `active` or `blocked`.

Done or archived WorkItems should not show `stale` just because they were completed on an earlier day. The marker should be visible in the row text, for example `[stale]`, while the reason may remain the more specific delivery reason when one exists.

## Todo / WorkItem Combined Display

Default `/list` should include both data types:

- WorkItems show source, priority, title, status, reason, stale marker, and next action or sync summary.
- Todos show `todo` as source, priority, title, completion state, and due time.
- Delivery-risk WorkItems rank ahead of low-priority Todo reminders even when the Todo is present.
- Todo rows must remain visible so `/list` stays a unified daily view instead of becoming a workflow-only view.

## Compatibility Boundaries

- Existing command names and filters remain valid.
- No persisted schema migration is required.
- Existing WorkItems with missing `last_synced_at` remain readable and are marked stale only in the default daily triage view.
- Reason detection is heuristic and local; it must not claim live Redmine/MR/OpenSpec truth unless that fact is already in local WorkItem text, source refs, identities, or evidence summaries.
- `/list` must not trigger `/sync` or perform external probes.

## Failure Modes

- Workflow repository unavailable: `/list` still shows Todo rows and does not crash.
- Todo repository unavailable: existing behavior should surface the underlying error; no special swallowing is required.
- Invalid `last_synced_at`: mark the WorkItem stale rather than failing rendering.
- Unknown source or priority: preserve existing fallback behavior and render a neutral priority marker.
- Very long titles or reasons: keep row text concise and rely on existing Rich table wrapping.
- Empty repositories: keep the current empty-list style message.

## Rollback

Rollback is local and straightforward:

- Revert the code and tests for the new default `/list` triage rendering.
- No data migration or cleanup is required because the change derives grouping and reasons from existing fields.
- Existing WorkItems, Evidence, Todos, Codex reports, and configuration remain unchanged.

## Acceptance Criteria

- Running `/list` after `/sync` provides a grouped daily view that identifies the first risky or blocked WorkItem.
- The default view includes blocked, active-action, waiting-closeout, recently-completed, stale-sync, and Todo reminder groups when matching data exists.
- High-priority WorkItems display concise reason text.
- WorkItems not synced today display a stale marker.
- Delivery-risk WorkItems sort before low-priority Todo reminders.
- `/list completed` and `/list completed --source codex` continue to show completed WorkItems as before.
