## Context

`ai-node` 当前具备 DDD 分层、SQLite 默认持久化、短期会话记忆、长期偏好、Agent tool validation 和 Reactor runtime。用户的真实工作流已经由 Playbook、OpenSpec、Git、Redmine/GitLab、Codex 线程共同支撑；其中 Playbook 已经封装 Redmine/GitLab/workspace/closeout 等关键能力。

本 change 不把 `ai-node` 做成新的项目管理系统，也不重新实现 Redmine/GitLab 客户端。它只作为个人工作助手编排层：把现有工具的只读事实同步成个人工作上下文，维护本地 WorkItem 与 Evidence，并通过 Agent 工具生成下一步建议、工作日启动计划和复盘草稿。

## Goals / Non-Goals

**Goals:**

- 建立本地 `WorkItem` 与 `Evidence` 模型，表达用户正在推进的工作项、来源、状态、下一步和证据。
- 提供只读 connectors，复用 Playbook/OpenSpec/Git 命令获取外部事实。
- 提供 CLI 与 Agent 工具入口，支持 `/sync`、`/work add <title>`、`/work import redmine <id>`、`/work status`、`/work evidence add <work-id>`、`/work evidence summary <work-id>`、`/codex tasks`、`/continue`、`/review day`。
- 支持读取 Codex 每日自动整理的未完成任务快照目录，包括结构化 JSON 和 Markdown 每日总结，作为个人工作上下文输入。
- 允许缺少外部命令时降级为清晰的不可用状态，而不是让整个助手失败。
- 所有同步结果可追溯：记录来源命令、时间、摘要和错误。

**Non-Goals:**

- 不直接写 Redmine/GitLab/MR 评论。
- 不登记工时。
- 不执行 Playbook closeout、merge、cleanup 等有副作用动作。
- 不替代 OpenSpec 的 artifact 工作流。
- 不在 ai-node 内实现后台调度器；Codex App automation 或系统计划任务负责产出日报快照。
- 不引入新的外部 Python 依赖。

## Decisions

### 1. 使用命令适配器而非 API 客户端

`PlaybookConnector`、`OpenSpecConnector`、`GitConnector` 只负责运行已有命令、解析 JSON/文本输出并返回统一快照。Playbook 覆盖 Redmine issue、workspace task/status 和 closeout gaps；OpenSpec 覆盖 active changes、change status 和 apply instructions。这样可以复用用户已经信任的工具链，避免在 `ai-node` 里重复维护 Redmine/GitLab 鉴权、字段映射和 closeout 规则。

Rejected alternative: 直接接 Redmine/GitLab API。原因是第一版会引入凭据、副作用边界和重复实现风险。

### 2. WorkItem 是个人编排模型，不是外部系统副本

WorkItem 只保存推进工作所需的本地字段：标题、来源、来源引用、项目路径、状态、优先级、下一步、最近同步时间和摘要。Redmine issue、MR、OpenSpec change 的完整事实仍由外部工具按需读取。

Rejected alternative: 把外部 issue/MR/change 全量镜像到本地。原因是同步复杂，容易产生事实漂移。

### 3. Evidence 是 closeout 和日报的共同原料

Evidence 记录命令结果、测试摘要、人工备注、外部链接和评审结论。`/review day`、MR/Redmine 草稿和 closeout 检查都应从 Evidence 聚合，而不是临时拼接日志。

### 4. 同步只读，建议可执行但不自动执行

`/continue` 可以给出下一步建议，例如“先运行 openspec status”、“阅读 OpenSpec apply instructions”或“检查 Playbook workspace closeout gaps”，但不自动执行写入性命令。后续若需要写 Redmine 或登记工时，应另开 change 并通过 Playbook 的受控写能力实现。

### 5. Connector 结果必须结构化

每个 connector 返回 `SourceSnapshot`，包含 `source`、`project_path`、`summary`、`facts`、`command`、`success`、`error`、`captured_at`。上层服务只消费快照，不直接解析 shell 输出。

### 6. 先服务当前目录，再扩展多项目索引

首版 `/sync` 默认面向当前工作目录，也允许传入路径。全局扫描所有项目、自动发现所有 workspace 和线程索引不在首版范围。

### 7. Codex 任务分析采用文件交接

Codex App automation 每天读取最近线程并生成稳定文件：`data/codex-task-reports/YYYY-MM-DD.json` 和 `data/codex-task-reports/YYYY-MM-DD.md`。`ai-node` 读取该目录中的 JSON 作为任务识别事实，读取同名 Markdown 作为每日总结上下文；它不直接读取 Codex 内部 session/SQLite/应用状态。这样把“如何检查 Codex 线程”的不稳定部分留给 Codex 自动化，把“如何纳入个人助手上下文”的稳定部分留给 ai-node。

Report JSON 首版字段：

- `generated_at`: 生成时间。
- `total_unfinished`: 未完成与阻塞任务总数。
- `unfinished`: 需要继续推进的任务数组。
- `blocked`: 被凭据、人工确认或外部状态阻塞的任务数组。
- `completed`: 当日确认已完成的任务数组。
- `summary`: 面向用户的简短摘要。

Markdown 每日总结首版用途：

- 作为 `/codex tasks`、`/start day`、`/review day` 的可读上下文来源。
- 保留自动化对线程的判断依据、未深挖风险和人工阻塞。
- 不作为唯一事实来源；任务分类、计数和完成判定以同名 JSON 的结构化字段为准。

## Risks / Trade-offs

- [Risk] 外部命令不可用或输出格式变化 → Mitigation: connector 捕获错误，返回不可用快照；测试覆盖 missing command 和 invalid JSON。
- [Risk] 本地 WorkItem 与外部事实漂移 → Mitigation: 保存 `last_synced_at` 和 source snapshot summary，状态页明确显示同步时间。
- [Risk] 第一版命令过多导致实现发散 → Mitigation: 只实现核心 CLI 命令和对应 Agent 工具，Codex 日报首版仅做只读快照识别。
- [Risk] Codex 内部线程存储格式变化 → Mitigation: ai-node 不读内部存储，只消费自动化产出的稳定 JSON 和 Markdown 每日总结。
- [Risk] Playbook/OpenSpec 命令较慢 → Mitigation: 同步显式触发，不在每次 prompt 自动执行；后续可加缓存。
- [Risk] 用户误以为建议已经执行 → Mitigation: 输出区分“建议动作”和“已执行动作”，Evidence 只记录明确完成的事实。

## Migration Plan

1. 新增 workflow application 模块和 persistence 表，不改变现有 Todo 表。
2. 实现 connectors 的只读命令调用与错误降级。
3. 增加 Codex report reader，读取 `data/codex-task-reports/` 中的 JSON 日报快照和同名 Markdown 每日总结。
4. 增加 CLI 命令和 Agent tools。
5. 保持现有 Todo 功能和 Reactor runtime 兼容。
6. 通过单元测试验证 WorkItem、Evidence、connector parsing、Codex report parsing、CLI 命令和 tool execution。

Rollback strategy: 本 change 新增模块和表，不需要迁移现有 Todo 数据；若需回滚，可停用新增命令和工具，不影响原待办功能。

## Open Questions

- Codex thread 可作为 WorkItem source，但首版通过日报快照导入，不直接深耦合线程存储。
- 是否需要为 Redmine/GitLab 写操作建立独立 approval gate。
- 是否将 `/review day` 直接输出 Redmine 日志格式，还是先输出通用 Markdown 草稿。
