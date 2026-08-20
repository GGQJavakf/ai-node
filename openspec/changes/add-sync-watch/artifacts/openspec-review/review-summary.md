# OpenSpec Review Summary

## 1. Verdict

APPROVE_WITH_NOTES

## 2. Change in One Paragraph

This change adds a local `/sync watch` mode that periodically triggers the existing `/sync` workflow and prints a report for every trigger. It is suitable to enter development because the scope is constrained to a local foreground loop, reuses existing Codex report ingestion and read-only project sync paths, and explicitly excludes Codex thread mutation, external writeback, merge, push, publish, deploy, and persistent OS scheduling.

## 3. Functional Scope

### In Scope

- Periodically run the existing `/sync` workflow from a local watch command.
- Print a timestamped trigger report containing sync results and next recommended action.
- Use configured default interval when the user does not supply one.
- Stop cleanly on user interruption.

### Out of Scope

- Direct Codex internal session inspection.
- Sending continuation messages to Codex threads from `ai-node`.
- Redmine/GitLab/MR writes, time logging, merge, push, publish, deploy, or production changes.
- Installing a persistent OS scheduler, daemon, or Codex app automation.

## 4. Implementation Scope

- 涉及模块：`src/ai_todo_assistant/presentation/cli.py` for command dispatch and reporting; `src/ai_todo_assistant/infrastructure/config/settings.py` for interval configuration; optionally `src/ai_todo_assistant/application/workflow/` for a small reusable watch runner if CLI-only code becomes too dense.
- 数据模型：不新增持久化模型；复用 existing WorkItem and Evidence data written by `/sync`.
- 接口 / 响应：新增 `/sync watch [interval-seconds] [path]`; existing `/sync`, `/sync --dry-run`, `/sync status`, `/codex tasks`, `/list`, `/next`, and `/review` remain compatible.
- 认证 / 鉴权 / JWT / filter / audit：N/A; this is a local CLI workflow and does not add authenticated network endpoints.
- 迁移 / 兼容 / 回滚：additive command and config default only; rollback is deleting the watch command path and config key, with no data migration.

## 5. Review Findings

| Severity | Issue | Impact | Recommendation |
|---|---|---|---|
| MINOR | The feature name can sound like a background automation even though the design is a foreground local loop. | Users may expect it to keep running after the CLI exits. | Make help/output say it is a local foreground watch and must be kept running. |

## 6. What Already Looks Good

- `openspec validate add-sync-watch --strict` passed.
- The specs update the previous no-background-scheduler constraint without creating a second sync command family.
- Safety boundaries are explicit and testable.
- The task list includes implementation, configuration, help text, and bounded tests.

## 7. Decision

- 是否可以进入开发：可以，带注意事项。
- 进入开发前必须补什么：无阻塞项。
- 可接受的后续事项：若后续要真正创建 Codex app automation 或 Windows Task Scheduler，需要另开 change，因为本 change 只覆盖本地前台 watch。
