## Why

`ai-node` 目前已经具备待办管理、短期记忆、偏好记忆和 Reactor runtime，但仍主要停留在本地 Todo 助手。用户日常真实工作依赖 Playbook、OpenSpec、Git、Redmine/GitLab 等既有工具链；本 change 将 `ai-node` 定位为个人工作助手编排层，复用已有工具的事实与动作能力，避免重复实现外部系统客户端。

## What Changes

- 新增本地 `WorkItem` 工作项模型，用于记录用户当前正在推进的工作、来源、项目路径、状态、下一步和证据。
- 新增只读 source connectors，通过命令适配方式调用既有工具：
  - Playbook：读取 Redmine issue、workspace task/status、closeout 缺口。
  - OpenSpec：读取 active changes、change status、apply instructions。
  - Git：读取当前 repo、branch、dirty status、diff stat。
  - Codex daily task reports：读取 Codex 定时任务产出的本地 JSON 快照和 Markdown 每日总结，识别未完成、阻塞和已完成任务，并保留人工可读的上下文摘要。
- 新增工作流同步命令与 Agent 工具：
  - `/sync` 同步当前目录上下文。
  - `/work add <title>` 创建手工工作项。
  - `/work import redmine <id>` 通过 Playbook 导入 Redmine 工作项。
  - `/work status` 汇总本地工作项与外部只读状态。
  - `/work evidence add <work-id>` 和 `/work evidence summary <work-id>` 记录/汇总证据。
  - `/codex tasks` 查看 Codex 自动整理的未完成任务日报。
  - `/continue` 推荐下一步。
  - `/review day` 生成日报/收尾草稿。
- 新增证据日志能力，将测试命令、验证结果、人工备注、外部状态摘要挂到工作项。
- 首版只做读取、草稿生成和本地记录；不直接写 Redmine/GitLab/MR，不登记工时，不执行 Playbook closeout 写操作。
- 不替代 Playbook/OpenSpec/Git；所有外部事实以既有工具输出为准。

## Capabilities

### New Capabilities

- `workflow-source-connectors`: 通过 Playbook/OpenSpec/Git 命令读取外部工作流事实，并转换为本地统一快照。
- `codex-task-report-ingestion`: 读取 Codex 定时任务写入的日报目录，归一化未完成/阻塞/已完成任务快照，并读取每日总结 Markdown 供 ai-node 识别与复盘。
- `work-item-orchestration`: 本地维护 WorkItem，支持导入、同步、状态汇总和下一步推荐。
- `work-evidence-journal`: 为工作项记录命令、测试、评审、备注和外部链接等证据，用于 closeout、日报和 MR/Redmine 草稿。
- `daily-workflow-review`: 基于 WorkItem 与 evidence 生成启动计划、继续建议和工作日复盘草稿。

### Modified Capabilities

- None.

## Impact

- Affected code:
  - New application services under `src/ai_todo_assistant/application/workflow/`
  - New connector adapters under `src/ai_todo_assistant/infrastructure/connectors/`
  - New workflow report readers under `src/ai_todo_assistant/application/workflow/`
  - Persistence additions for work items and evidence in SQLite/JSON compatibility layers
  - CLI additions in `src/ai_todo_assistant/presentation/cli.py`
  - Agent tool additions in `src/ai_todo_assistant/application/agent/`
- External systems:
  - Uses installed Playbook CLI as the preferred source for Redmine/GitLab/workspace facts.
  - Uses installed OpenSpec CLI for change facts and apply instructions.
  - Uses local Git commands for repository facts.
- Dependencies:
  - No new Python package dependency in the first version.
  - Requires external commands to be present for corresponding connector features; missing commands must degrade to clear status messages.
  - Codex task ingestion depends on a local report directory, defaulting to `data/codex-task-reports/`, with paired `YYYY-MM-DD.json` and `YYYY-MM-DD.md` files.
