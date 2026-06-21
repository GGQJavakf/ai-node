# Codex Task Reports

`ai-node` consumes daily Codex task reports from `data/codex-task-reports/`.
Codex automation owns thread inspection; `ai-node` only reads the stable files
below and does not read Codex internal session storage.

## Files

Each daily snapshot should use paired files:

- `YYYY-MM-DD.json`: structured task facts used by `ai-node`.
- `YYYY-MM-DD.md`: human-readable daily summary used for planning and review context.

`data/codex-task-reports/` is local runtime state and is ignored by Git.

## JSON Schema

The JSON root must be an object. Required fields:

- `generated_at`: ISO-like timestamp for the snapshot.
- `total_unfinished`: count of unfinished plus blocked work.
- `unfinished`: tasks that still need implementation, validation, merge, publish, writeback, or closeout.
- `blocked`: tasks waiting for credentials, user decision, external system state, or manual confirmation.
- `completed`: tasks with concrete completion evidence.
- `summary`: short user-facing summary.

Task entries should include these fields when known:

- `thread_id`
- `title`
- `status`
- `cwd`
- `source`
- `next_action`
- `evidence`
- `last_seen`
- `completion_signals`

Completion signals include MR/PR merge, closeout or cleanup completion, Redmine
resolved or closed status, publish or draft success, final validation with no
required follow-up, empty task list, or workspace closeout verification.

## Markdown Summary

The paired Markdown file should include these sections:

- Need follow-up today
- Blocked
- Recently completed
- Uninspected risks

The Markdown summary is context, not the source of truth for counts or status.
Structured task classification comes from the JSON file.

## Retention

Keep recent daily reports long enough for weekly review. A practical default is
30 days locally. Older files can be archived or deleted without affecting Todo
storage.
