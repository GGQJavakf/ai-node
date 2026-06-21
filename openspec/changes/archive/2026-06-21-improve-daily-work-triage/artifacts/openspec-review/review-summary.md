# OpenSpec Review Summary

## 1. Verdict

APPROVE

## 2. Change in One Paragraph

This change turns the default `/list` command into a daily work triage view that groups local WorkItems and Todo reminders by delivery risk, explains why high-priority work matters, and marks WorkItems stale when they have not synced today. The OpenSpec documents are specific enough to support implementation, regression tests, and later archive because they define grouping, sorting, stale behavior, compatibility boundaries, failure modes, and rollback without requiring external writes.

## 3. Functional Scope

### In Scope

- Default `/list` grouping for `blocked`, `active needs action`, `waiting closeout`, `recently completed`, `stale sync`, and Todo reminders.
- Local-only WorkItem reason text such as `blocked by Redmine`, `needs validation`, `MR merged but closeout missing`, and `Codex thread still active`.
- Today-based stale markers for active or blocked WorkItems.
- Combined Todo and WorkItem display where delivery-risk WorkItems outrank low-priority reminders.
- Compatibility for existing filters such as `/list completed`, `/list completed --source codex`, and `--source todo`.

### Out of Scope

- New daily commands or a second automation.
- Live Redmine, GitLab/MR, OpenSpec, Playbook, or Codex reads during `/list`.
- External writes, Redmine/GitLab/MR writeback, merge, push, or time logging.
- Todo and WorkItem storage consolidation.
- Richer external completion detection, preference-backed ranking, or long-term memory compression.

## 4. Implementation Scope

- 涉及模块：`src/ai_todo_assistant/presentation/cli.py` for `/list` rendering, with optional helpers in `src/ai_todo_assistant/application/workflow/services.py` if reusable ranking/reason logic is extracted.
- 数据模型：不需要新增持久化字段；现有 `WorkItem.status`, `source`, `source_ref`, `source_identities`, `source_refs`, `merge_conflicts`, `next_action`, `sync_summary`, `last_synced_at`, `updated_at`, and Todo due/priority fields are enough.
- 接口 / 响应：bare `/list` changes to grouped daily triage; detailed filters retain their current command surface and source-filter behavior.
- 认证 / 鉴权 / JWT / filter / audit：N/A; this is a local CLI rendering change and must not touch auth boundaries or external systems.
- 迁移 / 兼容 / 回滚：no migration required; rollback is a code revert because all grouping and reason text are derived from existing local records.

## 5. Review Findings

NONE - No blocking or material issues found. The documents can support implementation and tests; proceed with narrow patches and preserve existing dirty worktree changes.

## 6. What Already Looks Good

- Requirements are observable and testable: each group, reason, stale rule, ordering rule, and compatibility path has at least one scenario.
- `tasks.md` maps every requirement area to implementation and tests, including compatibility checks and full validation.
- `design.md` covers goals, non-goals, sorting, stale behavior, reason heuristics, failure modes, compatibility boundaries, and rollback.
- `openspec validate improve-daily-work-triage --strict` passed.

## 7. Decision

- 是否可以进入开发：是。
- 进入开发前必须补什么：无需补充 OpenSpec 文档。
- 可接受的后续事项：实现阶段应保持本地-only、最小补丁，不改外部系统，不新增命令，并保留 `/list completed` 等已有过滤行为。

## Appendix

### Validation

- `openspec validate improve-daily-work-triage --strict`: passed.
