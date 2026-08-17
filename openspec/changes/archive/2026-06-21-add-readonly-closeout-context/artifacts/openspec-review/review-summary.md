# OpenSpec Review Summary

## 1. Verdict

APPROVE_WITH_NOTES

## 2. Change in One Paragraph

This change adds read-only closeout context to `ai-node`: `/sync` will parse existing Git/OpenSpec/Playbook snapshots for Redmine/MR/OpenSpec closeout gaps, persist those gaps as local Evidence, and `/list` will surface the resulting local reasons. The OpenSpec is sufficient to enter implementation because it defines the external read-only boundary, Evidence attachment rules, failure degradation, list behavior, tests, validation, archive, and diff review.

## 3. Functional Scope

### In Scope

- Parse existing read-only snapshot facts for closeout gaps.
- Persist closeout gaps and unavailable-tool summaries as local Evidence.
- Attach gap Evidence to exactly matching WorkItems by stable identity, or to the project sync context when ambiguous.
- Show closeout-specific `/list` reasons from local WorkItem and Evidence data.
- Degrade connector failures without interrupting CLI sync.

### Out of Scope

- Redmine, GitLab/MR, OpenSpec, Playbook, Git, time logging, merge, closeout, archive, publish, or push writes.
- New daily commands or new external clients.
- Marking WorkItems done solely from gap observations.
- Schema migration or fuzzy matching.

## 4. Implementation Scope

- 涉及模块：`src/ai_todo_assistant/application/workflow/services.py` for gap extraction and Evidence persistence; `src/ai_todo_assistant/infrastructure/connectors/*.py` only if parsing summaries need small improvements; `src/ai_todo_assistant/presentation/cli.py` for `/list` local Evidence reason detection.
- 数据模型：no schema change; use existing append-only `Evidence` fields with `snapshot` type, source, command, output excerpt, and success flag.
- 接口 / 响应：`/sync` continues returning snapshot summaries; `/list` reason text expands to closeout gaps found in local Evidence.
- 认证 / 鉴权 / JWT / filter / audit：N/A; local CLI feature only, no authentication surface changes.
- 迁移 / 兼容 / 回滚：no migration; existing WorkItems/Evidence remain readable; rollback is code revert and any created local Evidence can remain as harmless observations.

## 5. Review Findings

| Severity | Issue | Impact | Recommendation |
|---|---|---|---|
| MINOR | Gap extraction is intentionally heuristic and conservative, but the docs do not require Evidence de-duplication explicitly. | Repeated `/sync` may append duplicate closeout gap Evidence if implementation does not guard it. | During implementation, de-duplicate closeout gap Evidence by normalized summary plus source/command context before appending. |
| INFO | GitLab MR project scoping is left to existing stable identity behavior. | Unknown project scope may attach MR gaps to project context rather than a specific WorkItem, which is safe but less precise. | Keep ambiguous MR gaps on the project sync context and do not introduce fuzzy matching in this change. |

## 6. What Already Looks Good

- Requirements are observable and testable across connector parsing, WorkflowSyncService Evidence writes, CLI `/list` reason display, and failure degradation.
- The proposal, specs, and design consistently preserve the external read-only boundary.
- Tasks cover OpenSpec review, tests-first implementation, validation, archive, and final diff/security review.
- `openspec validate add-readonly-closeout-context --strict` passed.

## 7. Decision

- 是否可以进入开发：是，可以进入开发，带上述注意事项。
- 进入开发前必须补什么：无阻断项。
- 可接受的后续事项：如果 future live MR/Redmine APIs are needed, they should be handled by a separate OpenSpec change with an explicit external-write and credential boundary review.

## Appendix

### Requirement-to-Task Coverage

- `workflow-source-connectors` read-only closeout context and unavailable snapshots are covered by tasks 2.1, 2.3, 3.1, 3.6, and 4.7.
- `work-evidence-journal` closeout gap Evidence, identity mapping, ambiguous fallback, and failure Evidence are covered by tasks 2.2, 2.3, 3.2, 3.3, and 3.4.
- `daily-work-triage` Evidence-based closeout reasons and local-only `/list` behavior are covered by tasks 2.4, 2.5, 3.5, and 3.6.
