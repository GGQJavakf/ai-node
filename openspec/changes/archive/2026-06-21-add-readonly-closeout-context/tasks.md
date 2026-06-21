## 1. OpenSpec and Review

- [x] 1.1 Create `add-readonly-closeout-context` proposal, design, tasks, and delta specs.
- [x] 1.2 Run `openspec validate add-readonly-closeout-context --strict`.
- [x] 1.3 Generate `artifacts/openspec-review/review-summary.md` using `ai-decision-review`.
- [x] 1.4 Proceed to code only if review verdict is `APPROVE` or `APPROVE_WITH_NOTES`.

## 2. Regression Tests First

- [x] 2.1 Add connector parsing tests for closeout-style Playbook/OpenSpec snapshots and failure degradation.
- [x] 2.2 Add WorkflowSyncService tests proving closeout gaps are appended as Evidence and mapped by stable identity when possible.
- [x] 2.3 Add WorkflowSyncService tests proving unavailable tools are persisted as local error Evidence and do not abort sync.
- [x] 2.4 Add CLI tests proving `/list` shows closeout gap reasons from local Evidence.
- [x] 2.5 Add compatibility tests or preserve existing tests for `/sync --dry-run`, `/list completed`, and source filters.

## 3. Implementation

- [x] 3.1 Add closeout gap extraction helpers that consume existing `SourceSnapshot` facts and never call external systems directly.
- [x] 3.2 Persist closeout gap Evidence during `WorkflowSyncService._persist_project_sync()`.
- [x] 3.3 Map closeout gap Evidence to WorkItems by `redmine:<id>`, `gitlab-mr:<project>:<iid>`, or `openspec:<change>` when exactly one local match exists.
- [x] 3.4 Fall back to project sync context Evidence when a gap is ambiguous or unmapped.
- [x] 3.5 Extend `/list` reason detection to include local Evidence summaries without triggering external reads.
- [x] 3.6 Keep all runtime connector calls read-only and preserve connector failure snapshots.

## 4. Validation and Closeout

- [x] 4.1 Run targeted tests for connectors, sync service, and CLI list behavior.
- [x] 4.2 Run `python -m compileall -q src tests`.
- [x] 4.3 Run `python -m unittest discover -s tests`.
- [x] 4.4 Run `openspec validate add-readonly-closeout-context --strict`.
- [x] 4.5 Archive the change with `openspec archive add-readonly-closeout-context -y`.
- [x] 4.6 Run `openspec validate --specs --strict` and `openspec list`.
- [x] 4.7 Review diff for external write risk, sensitive data, local runtime data, and unrelated changes.
