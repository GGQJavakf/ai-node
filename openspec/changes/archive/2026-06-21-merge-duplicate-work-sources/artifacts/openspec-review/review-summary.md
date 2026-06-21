# OpenSpec Review Summary

## 1. Verdict

APPROVE_WITH_NOTES

## 2. Change in One Paragraph

This change defines a local WorkItem source-identity layer so Codex, Redmine, OpenSpec, GitLab MR, and thread observations that describe the same real work item can merge into one actionable WorkItem. The OpenSpec documents are sufficient to enter implementation because they define exact merge keys, source preservation, ambiguity boundaries, rollback expectations, `/list` de-duplication, `/sync` summary output, persistence compatibility, and regression-test coverage.

## 3. Functional Scope

### In Scope

- Derive canonical identities for Redmine ids, OpenSpec changes, GitLab MR ids, and Codex thread ids.
- Automatically merge exact stable identity matches into one local WorkItem.
- Preserve all contributing source refs, source identities, and evidence.
- Detect ambiguous or weak matches and require manual confirmation instead of auto-merging.
- Record merge audit data and provide rollback or manual split support for mistaken merges.
- Make duplicate handling visible in `/sync`, `/codex tasks`, `/work status`, and `/list`.

### Out of Scope

- Writing to Redmine, GitLab, OpenSpec, Playbook, Codex, or any external production system.
- Fuzzy title-similarity auto-merge.
- Destructive deletion as the merge mechanism.
- A broad one-way migration that prevents legacy JSON/SQLite records from loading.
- Advanced interactive conflict-resolution UI beyond the documented manual confirmation/split path.

## 4. Implementation Scope

- 涉及模块：`src/ai_todo_assistant/domain/workflow.py`, `src/ai_todo_assistant/application/workflow/services.py`, workflow repository ports, JSON/SQLite workflow persistence, and CLI handlers in `src/ai_todo_assistant/presentation/cli.py`.
- 数据模型：新增或兼容扩展 WorkItem metadata for canonical identities, observed source refs, merge audit records, and conflict flags; old records must load with empty defaults.
- 接口 / 响应：`/sync` must report `merged`, `created`, `updated`, `skipped`; `/list` and `/work status` must show one active row per exact identity group and expose associated source refs or conflicts.
- 认证 / 鉴权 / JWT / filter / audit：N/A; this is a local CLI/workflow persistence change with read-only external connectors.
- 迁移 / 兼容 / 回滚：compatible JSON/SQLite migration, lazy identity backfill, no external writes, and merge audit-based rollback or manual split.

## 5. Review Findings

| Severity | Issue | Impact | Recommendation |
|---|---|---|---|
| MINOR | Rollback exposure is intentionally left as an implementation choice. | Developers could satisfy the minimum with a service method but leave users without an obvious CLI path. | During implementation, either add a small CLI/help path for split/rollback or explicitly document the service-level manual path in README/help. |
| MINOR | MR project scoping has a safe default but the final source of project scope is not fully fixed. | Incorrect MR scoping could skip valid merges more often than necessary, though it should not cause unsafe automatic merges. | Prefer git remote URL when available and fall back to normalized project path; keep unknown scope ambiguous as specified. |

## 6. What Already Looks Good

- Specs are testable and cover identity extraction, exact merge behavior, evidence preservation, ambiguity handling, rollback/split, and observable CLI outcomes.
- Tasks map to each requirement and include focused workflow tests, CLI tests, full unittest, OpenSpec validation, and self-review.
- Proposal, design, and specs agree on the local-only/read-only external boundary.
- `openspec validate merge-duplicate-work-sources --strict` passed.

## 7. Decision

- 是否可以进入开发：可以，但带注意事项。
- 进入开发前必须补什么：无需阻断性补充；implementation must keep rollback/split and MR scoping decisions aligned with the notes above.
- 可接受的后续事项：advanced interactive conflict UI can remain out of scope if ambiguous candidates are reported and a documented manual resolution path exists.

## Appendix

### Validation Evidence

- `openspec validate merge-duplicate-work-sources --strict`: passed with `Change 'merge-duplicate-work-sources' is valid`.
- OpenSpec CLI also emitted a PostHog `Blob is not defined` flush error after completion; this is telemetry cleanup noise and did not invalidate the change.

### Requirement-to-Task Coverage

- Stable identity extraction is covered by tasks 1.1, 1.2, 3.1, and 3.2.
- Exact merge and source association are covered by tasks 1.3, 4.1, 4.2, and 4.3.
- Source ref and evidence preservation are covered by tasks 1.3, 2.4, and 4.4.
- Ambiguous-match confirmation is covered by tasks 1.4, 3.4, and 5.3.
- Rollback/manual split is covered by tasks 1.5, 4.5, and 5.4.
- `/list` and `/sync` observable outcomes are covered by tasks 1.6, 5.1, and 5.2.
