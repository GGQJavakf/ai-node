## Context

The project already reads stable JSON reports from `codex_task_report_dir` through `CodexTaskReportService`. Reports expose `unfinished`, `blocked`, `completed`, and optional per-entry `completion_signals` / `evidence`. `WorkItemService.import_codex_report()` is the local integration point because it already maps report entries to `WorkItem(source="codex", source_ref=<thread/source id>)`.

## Goals / Non-Goals

Goals:

- Treat Codex `completed` entries as completion signals for matching local WorkItems.
- Persist completion evidence in the same Evidence journal used by daily review and closeout summaries.
- Keep imports repeatable: repeated `/sync` or `/codex tasks` must not duplicate the same evidence.
- Make conflict handling deterministic and testable.
- Return a concise sync summary that distinguishes completed, blocked, reactivated, and unchanged items.

Non-goals:

- Do not inspect Codex session internals.
- Do not create, update, or schedule Codex automations.
- Do not write Redmine, GitLab, MR comments, or remote systems.
- Do not delete or rewrite existing Evidence records.
- Do not archive completed WorkItems automatically.

## Completion Signals

For a Codex report entry, ai-node considers the entry completed when it appears in the report `completed` array. Completion evidence is collected from:

- `completion_signals` when it is a list.
- `evidence` when it is a list or string.
- `status` / `summary` as fallback context when no explicit signal exists.

Each completion evidence record must preserve enough source context to audit why the WorkItem was closed: report path or generated time when available, thread/source reference, title, and the concise signal text.

## State Machine

Codex sync applies only to WorkItems with `source="codex"` and a matching `source_ref`.

Allowed transitions:

- Missing item + `unfinished`: create `active`.
- Missing item + `blocked`: create `blocked`.
- Missing item + `completed`: create `done`.
- `active` + `blocked`: transition to `blocked`.
- `blocked` + `unfinished`: transition to `active` and retain the next action.
- `active` or `blocked` + `completed`: transition to `done`.
- `done` + `completed`: remain `done`; append only new evidence.
- `done` + `unfinished` or `blocked`: remain `done`; record no status regression. The sync summary may count this as unchanged or conflict-preserved, but must not reopen the WorkItem automatically.

The anti-regression rule is intentional: once local closeout is recorded, reopening requires explicit user action or a future dedicated reopen command.

## Idempotency

Evidence deduplication key:

- WorkItem id
- Evidence source `codex`
- Evidence type `snapshot`
- Normalized summary text

Normalization trims whitespace and joins multi-value signals in stable order. Re-importing the same report or another report containing the same completion signal must not append duplicate Evidence. New distinct signals for the same completed WorkItem may append new Evidence.

WorkItem status saves are idempotent: if title, project path, next action, sync summary, and status do not materially change, the item is counted as unchanged.

## Conflict Handling

- Completed wins over active/blocked for the same `source_ref` within one report.
- Blocked wins over unfinished for the same `source_ref` within one report, unless the item is already done.
- Done WorkItems do not regress from later unfinished or blocked reports.
- If an entry lacks `thread_id`, `id`, and a stable title, ai-node may still import it using the title fallback, but tests should prefer stable `thread_id` fixtures.
- Malformed report files keep the existing behavior: skip invalid files and load the latest valid report.

## Sync Output

`/sync` should keep the existing source snapshot output and add a Codex status-change summary, for example:

```text
[OK] codex: completed=1, blocked=1, reactivated=1, unchanged=2
```

The summary should be derived from the import result rather than from raw report array lengths so it reflects actual local state changes and idempotent repeats.

`/sync --dry-run` uses the same Codex report classification and matching logic but returns a preview result without saving WorkItems, appending Evidence, or persisting project snapshot evidence. Project context sync is skipped in dry-run mode because git/OpenSpec/Playbook probes can create confusing side effects or slow down a quick preview.

`/sync status` is read-only. It loads the latest valid Codex report metadata and summarizes local WorkItem counts by status plus the newest `last_synced_at` timestamp. It must not import the report.

`/list completed --source codex` filters completed WorkItems by exact source and suppresses Todo rows unless the requested source is `todo`.

## Data / Migration

No schema migration is required if existing WorkItem and Evidence fields can represent the state and evidence. If current repository APIs cannot query existing evidence, extend repository behavior minimally without changing persisted data shape.

## Security / Privacy

Codex reports are local files. The sync must not read Codex internal session storage or external systems. Evidence summaries should remain concise and avoid dumping raw logs by default.

## Failure Modes

- Missing report directory: `/sync` reports Codex unavailable and continues other source sync.
- Malformed report: invalid files are skipped; latest valid report is used.
- Duplicate report import: no duplicate evidence and status counts show unchanged.
- Conflicting done vs blocked/unfinished: local `done` is preserved.
- Repository write failure: surface the exception through the CLI/test path; do not partially fake success.

## Rollback

Rollback is local and reversible:

- Revert the code change to stop automatic completion sync.
- Existing WorkItems and Evidence remain in the local repository.
- If a user needs to reopen an item after rollback, they can edit local WorkItem status through existing or future workflow commands; this change does not delete source data.
