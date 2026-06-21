## Context

`WorkItemService.import_codex_report()` already imports Codex report entries into local WorkItems, records completion evidence, and preserves `done` when later reports list an item as unfinished or blocked. The gap is classification: strong completion facts can appear in report text fields or `completion_signals` while the entry still sits in a non-completed report section.

## Goals / Non-Goals

Goals:

- Classify report entries with strong closeout evidence as local `done` even when the report section is stale.
- Keep `done` sticky and surface possible reopen candidates for manual review.
- Reuse current WorkItem and Evidence fields; avoid schema migration.
- Keep dry-run and real import behavior consistent.
- Keep all side effects local to WorkItems, Evidence, and CLI output.

Non-goals:

- Do not query or write Redmine, GitLab/MR, OpenSpec, Playbook, Codex sessions, or remote Git.
- Do not infer completion from weak pending language alone.
- Do not automatically reopen previously done WorkItems.
- Do not create a new daily command.

## Completion Signal Policy

Strong completion signals are local text facts found in Codex report entries, local Codex completion signals, report evidence, summaries, next actions, or status fields. The detector should recognize conservative patterns including:

- MR/PR merged, merge request merged, branch merged, or publish/release succeeded.
- Redmine resolved, closed, done, or issue status indicates resolved/closed.
- OpenSpec archived, change archived, tasks complete, or all tasks checked.
- Playbook closeout verified, closeout complete, finalize completed, or writeback complete.
- Final validation, tests, build, compile, or review passed with no follow-up.
- Codex cleanup, merge, publish, or writeback completed.

When a strong signal is found, the import should treat the target status as `done` and record the signal as Evidence. The original report section remains a local detail; ai-node does not rewrite the report file.

## Reopen Candidate Policy

`done` remains sticky. If a done WorkItem later appears in `unfinished` or `blocked` without strong completion evidence, ai-node records a local reopen candidate detail and increments a review-only counter. It does not change status to `active` or `blocked`.

Only a future explicit reopen workflow may change this behavior. This change intentionally avoids hidden state regression.

## Data / Migration

No schema migration is required. The existing `WorkItem.status`, `sync_summary`, `last_synced_at`, and Evidence journal can represent the result.

`CodexImportResult` may add an in-memory `reopen_candidates` count. This is a return/result field only and does not require persistence.

## CLI Output

`/sync` should continue to show existing Codex counts and detail lines. When reopen candidates exist, the summary should include the count, and detail lines should name the candidate WorkItem so the user can inspect it with `/work show`.

Dry-run output should include the same would-be completion and reopen candidate counts while performing no writes.

## Security / Privacy

The detector consumes local strings already present in report entries or WorkItem sync data. Evidence summaries must stay concise and should not dump raw logs. The implementation must not include credentials, tokens, local databases, or report data under `data/` in the commit.

## Failure Modes

- Ambiguous or weak completion wording: keep the existing reported status and do not mark done.
- Done item reappears as unfinished or blocked: keep done and add a reopen candidate detail.
- Entry appears in multiple report sections: strong completion still wins.
- Repeated imports: no duplicate completion Evidence.
- Dry-run: no WorkItem or Evidence writes.

## Rollback

Rollback is local and reversible. Reverting the code stops stronger detection; already-written local WorkItems and Evidence remain inspectable and can be edited through existing local workflow paths if necessary.
