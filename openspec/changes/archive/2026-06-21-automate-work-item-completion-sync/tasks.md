## 1. Implementation

- [x] 1.1 Add a structured Codex import result that returns imported WorkItems plus counts for completed, blocked, reactivated, and unchanged outcomes.
- [x] 1.2 Update `WorkItemService.import_codex_report()` to apply the Codex state machine: completed wins, blocked/unfinished update non-done items, and done items do not regress.
- [x] 1.3 Record Codex completion signals/evidence as append-only snapshot Evidence with stable deduplication.
- [x] 1.4 Update `/sync` output to summarize actual Codex status changes instead of only raw report array lengths.
- [x] 1.5 Ensure `/list completed` includes Codex WorkItems marked `done` by completion sync.
- [x] 1.6 Add `/sync --dry-run` preview mode without WorkItem, Evidence, or project snapshot writes.
- [x] 1.7 Add read-only `/sync status` for latest report metadata, WorkItem counts, and latest sync timestamp.
- [x] 1.8 Add `/list completed --source codex` filtering for completed Codex work.
- [x] 1.9 Add `/work evidence timeline <work-id>` for chronological, source-aware Evidence review.

## 2. Tests

- [x] 2.1 Add or update unit tests for active/blocked to done completion sync and creation of new done Codex WorkItems.
- [x] 2.2 Add or update unit tests proving repeated sync does not duplicate completion Evidence.
- [x] 2.3 Add or update unit tests for blocked to active, active to blocked, and done anti-regression behavior.
- [x] 2.4 Add or update CLI tests for `/sync` completed/blocked/reactivated/unchanged summary.
- [x] 2.5 Add or update CLI/list tests proving `/list completed` shows completed Codex WorkItems.
- [x] 2.6 Add CLI tests proving dry-run is non-mutating, sync status is read-only, and completed source filtering works.
- [x] 2.7 Add CLI tests proving Evidence timeline displays timestamps, sources, outcomes, and commands.

## 3. Validation

- [x] 3.1 Run targeted workflow/Codex unittest modules.
- [x] 3.2 Run full unittest discovery with `python -m unittest discover -s tests`.
- [x] 3.3 Run `openspec validate automate-work-item-completion-sync --strict`.
- [x] 3.4 Review the final diff for unrelated user changes and avoid reverting or staging them.
