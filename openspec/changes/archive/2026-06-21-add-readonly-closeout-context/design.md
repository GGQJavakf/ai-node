## Context

The current workflow layer already has the right trust boundary:

- `GitConnector`, `OpenSpecConnector`, and `PlaybookConnector` run local commands with `shell=False` and return `SourceSnapshot` objects.
- `WorkflowSyncService.sync_project()` reads Git, OpenSpec, Playbook workspace status, and Playbook closeout dry-run snapshots, then persists them as Evidence.
- `WorkItemService.import_codex_report()` extracts stable identities such as Redmine issue ids, OpenSpec changes, GitLab MR ids, and Codex thread ids.
- Bare `/list` derives daily triage groups and reasons from WorkItem fields, but it does not inspect Evidence.

This change should connect those existing pieces instead of creating new Redmine or GitLab clients.

## Data Model

No persisted schema change is required.

Closeout context is represented as existing `Evidence` rows:

- `evidence_type`: `snapshot`
- `source`: source snapshot name such as `playbook`, `openspec`, or `git`
- `summary`: concise closeout gap text, prefixed with `closeout gap:`
- `command`: the read-only command that produced the source snapshot
- `output_excerpt`: compact JSON excerpt or failure summary
- `success`: source snapshot success flag

The Evidence row attaches to:

1. A matching WorkItem found by stable identity.
2. The matching source/source_ref pair if identity lookup is not available.
3. The project sync context WorkItem as a safe fallback.

## Gap Extraction

The extractor consumes only local `SourceSnapshot` objects already produced by connectors.

It should detect these conservative cases:

- MR merged but Redmine not closed:
  - snapshot facts contain a merged MR indicator and an open/unresolved Redmine indicator; or
  - Playbook closeout gaps mention MR merged plus Redmine close/open/unresolved/missing.
- Redmine resolved but validation evidence missing:
  - facts or gap text mention Redmine resolved/closed and missing local validation/test/review evidence.
- OpenSpec completed but not archived:
  - facts or gap text mention OpenSpec tasks/artifacts complete/done and archive missing/not archived.

The first implementation may be heuristic, but it must be conservative and local-only:

- Do not infer live external truth beyond the snapshot facts.
- Prefer structured fields such as `gaps`, `redmine`, `issue`, `mr`, `merge_request`, `openspec`, `change`, `status`, `state`, `archived`, `tasks`, and `validation` when present.
- Fall back to lower-cased JSON text scanning only within the captured snapshot.

## Failure Handling

Connector failures already return `SourceSnapshot(success=False)`. `WorkflowSyncService` should persist those as Evidence on the project sync context with:

- source name
- command
- concise error
- output excerpt when available

No connector failure should abort `/sync` unless the project path itself is invalid before snapshot collection.

## `/list` Integration

Bare `/list` should remain local and cheap:

- It may read Evidence for the WorkItems being rendered from the local repository.
- It must not run Playbook, Git, OpenSpec, GitLab, Redmine, or Codex commands.
- Reason detection should include recent Evidence summaries and output excerpts in the local context text.

Reason priority should prefer specific closeout gap reasons:

1. `MR merged but Redmine not closed`
2. `Redmine resolved but validation evidence missing`
3. `OpenSpec completed but not archived`
4. Existing reasons such as `MR merged but closeout missing`, `needs validation`, or `Codex thread still active`

These reasons map to the existing `waiting closeout` group.

## Compatibility

- Existing WorkItems load unchanged.
- Existing Evidence rows remain valid.
- Existing source identity merging is reused; no fuzzy merge is introduced.
- `/sync --dry-run` remains non-mutating and must not write closeout Evidence.
- `/list completed`, `/list completed --source codex`, and source filters keep their current behavior.

## Security and External Write Boundary

Runtime commands allowed by this feature are only the existing read commands:

- `git branch --show-current`
- `git status --short`
- `git diff --stat`
- `openspec list --json`
- `openspec status --change <change> --json` when explicitly provided
- `openspec instructions apply --change <change> --json` when explicitly provided
- `playbook redmine pm issue <id> --output json --full`
- `playbook workspace task status --output json --full`
- `playbook workspace task closeout --dry-run --output json`

Runtime must not invoke:

- Redmine update or time logging commands
- GitLab/MR write commands
- OpenSpec archive/sync/apply mutation commands
- Playbook closeout `--apply`
- merge/finalize/cleanup/publish commands

## Rollback

Rollback is a code revert. Existing Evidence rows created by this feature are harmless local observations and can remain in the local database; no external state is changed.
