## 1. OpenSpec and Review

- [x] 1.1 Create `improve-daily-work-triage` OpenSpec proposal, design, tasks, and `daily-work-triage` spec.
- [x] 1.2 Run `openspec validate improve-daily-work-triage --strict`.
- [x] 1.3 Generate `artifacts/openspec-review/review-summary.md` using `ai-decision-review`.
- [x] 1.4 Proceed to implementation only if review verdict is `APPROVE` or `APPROVE_WITH_NOTES`.

## 2. Regression Tests First

- [x] 2.1 Add CLI tests proving bare `/list` includes grouped daily triage sections for blocked, active needs action, waiting closeout, recently completed, stale sync, and Todo reminders.
- [x] 2.2 Add tests proving concise reason text appears for Redmine blockers, validation needs, merged-MR closeout gaps, and active Codex threads.
- [x] 2.3 Add tests proving stale markers appear for active or blocked WorkItems not synced today and do not appear for WorkItems synced today or old completed items.
- [x] 2.4 Add tests proving delivery-risk WorkItems rank before low-priority Todo reminders.
- [x] 2.5 Add compatibility tests, or preserve existing tests, for `/list completed` and `/list completed --source codex`.

## 3. Daily Triage Implementation

- [x] 3.1 Add default `/list` triage grouping while keeping existing detailed filter behavior intact.
- [x] 3.2 Implement local-only WorkItem reason detection from status, source refs, identities, title, `next_action`, `sync_summary`, and merge conflict metadata.
- [x] 3.3 Implement today-based stale marker logic for active and blocked WorkItems.
- [x] 3.4 Implement group-first ordering and single-group assignment for WorkItems that match multiple groups.
- [x] 3.5 Ensure Todo reminders remain visible and lower-risk Todos do not outrank delivery-risk WorkItems.

## 4. Compatibility and Documentation Touches

- [x] 4.1 Keep command completion and help text aligned with `/list` as the unified daily view; do not add new daily commands.
- [x] 4.2 Avoid schema migrations and avoid external Redmine/GitLab/MR/OpenSpec writes.
- [x] 4.3 Review output wording to ensure reason text does not claim live external truth beyond local evidence.

## 5. Validation

- [x] 5.1 Run targeted workflow CLI unittest module.
- [x] 5.2 Run full unittest discovery with `python -m unittest discover -s tests`.
- [x] 5.3 Run `openspec validate improve-daily-work-triage --strict`.
- [x] 5.4 Self-review the final diff for unrelated user changes, external writes, and compatibility gaps.
