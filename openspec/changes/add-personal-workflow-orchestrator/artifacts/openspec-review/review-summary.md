# OpenSpec Review Summary

## 1. Verdict

APPROVE

## 2. Change in One Paragraph

This change turns `ai-node` from a Todo-focused assistant into a personal workflow orchestrator that reads facts from Playbook, OpenSpec, Git, and Codex daily task reports, then uses local WorkItems and Evidence to drive status, continuation, and day-review flows. The updated OpenSpec now includes explicit contracts for Codex JSON and Markdown daily summaries, completion-signal handling, manual WorkItem creation, evidence entry points, Playbook workspace/closeout facts, and OpenSpec apply instructions, so it is sufficient to support implementation and testing.

## 3. Functional Scope

### In Scope

- Read-only workflow source ingestion from Playbook, OpenSpec, Git, and Codex daily report files.
- Codex daily task reports using paired `YYYY-MM-DD.json` and `YYYY-MM-DD.md` files under `data/codex-task-reports/`.
- Completed-task classification based on concrete signals such as MR/PR merge, closeout completion, Redmine resolved state, publish success, final validation, empty task lists, or workspace closeout verification.
- Local WorkItem orchestration for manual items, Redmine imports, status summaries, stale sync markers, and next-action recommendations.
- Append-only Evidence records and concise evidence summaries for daily review, closeout, Redmine/MR drafts, and personal work tracking.
- CLI and Agent entry points for sync, manual work item creation, Redmine import, work status, evidence add/summary, Codex tasks, continue, start day, and review day.

### Out of Scope

- Direct Redmine/GitLab/MR writes, time registration, closeout apply, merge, cleanup, or other external side effects.
- Replacing Playbook, OpenSpec, Git, or Codex internal thread storage.
- Reading Codex internal session/SQLite/application state directly from `ai-node`.
- Full external issue/MR/change mirroring; external systems remain the source of truth.

## 4. Implementation Scope

- 涉及模块：`src/ai_todo_assistant/application/workflow/` for workflow services and Codex report readers; `src/ai_todo_assistant/infrastructure/connectors/` for command-backed source connectors; `src/ai_todo_assistant/presentation/cli.py` for slash commands; `src/ai_todo_assistant/application/agent/` for tool models, definitions, and dispatch.
- 数据模型：add WorkItem, Evidence, SourceSnapshot, and status enums; extend SQLite/JSON compatibility storage without changing existing Todo semantics.
- 接口 / 响应：CLI commands and Agent tools return local summaries, next actions, and evidence drafts; connector outputs use structured snapshots with success/error/captured_at metadata.
- 认证 / 鉴权 / JWT / filter / audit：N/A for direct authentication because first version only invokes local tools and reads local files; auditability is handled by recording command/source snapshots and Evidence entries.
- 迁移 / 兼容 / 回滚：additive tables/modules and ignored local report files; rollback can disable new commands/tools without affecting existing Todo data.

## 5. Review Findings

NONE

## 6. What Already Looks Good

- Specs are testable and now cover the previously missing Codex daily summary, completion-signal, manual WorkItem, Evidence, Playbook closeout, and OpenSpec apply-instruction scenarios.
- Tasks include both implementation and test coverage for each capability, including malformed Codex report handling and CLI display behavior.
- The safety boundary is clear: first version is read-only for external systems and separates automation-owned Codex thread inspection from `ai-node` file ingestion.
- `openspec validate add-personal-workflow-orchestrator --strict` passes.

## 7. Decision

- 是否可以进入开发：是。
- 进入开发前必须补什么：无阻断项。
- 可接受的后续事项：实现 remaining WorkItem/connector/Agent tasks, then run focused workflow tests, full unittest, and final command-injection/read-only review before archive.

## Appendix

### Verification Evidence

- `python -m unittest discover -s tests -p test_codex_task_reports.py`: 3 tests OK.
- `python -m unittest discover -s tests`: 88 tests OK.
- `openspec validate add-personal-workflow-orchestrator --strict`: valid.
- `openspec status --change add-personal-workflow-orchestrator --json`: proposal, specs, design, and tasks artifacts done; change is ready for apply tasks.
