# 每日工作助手优化路线

本文档记录 `ai-node` 作为个人每日工作助手的后续优化方向。内容基于当前仓库能力、本地运行数据，以及围绕 Codex、OpenSpec、Redmine、Git/MR 和 Playbook 的日常工作习惯。

## 当前快照

截至 2026-06-21，本地运行数据如下：

- `data/todos.db` 已存在。
- `todos`：1 条。
- `work_items`：22 条。
- `work_evidence`：103 条。
- WorkItem 状态分布：4 条 active，4 条 blocked，14 条 done。
- WorkItem 来源分布：21 条 codex，1 条 playbook。
- `data/codex-task-reports/` 下已有 `2026-06-20` 和 `2026-06-21` 的 Codex 报告文件。

这说明当前工具已经不只是 TodoList。你的真实每日工作负载已经主要沉淀在 `WorkItem` 和 `Evidence` 中，并且大部分由 Codex 每日任务快照驱动。

## 功能开发闭环

后续每个功能默认采用 OpenSpec 驱动开发，并在测试完成后执行统一收尾：

1. OpenSpec 提案先行：明确 proposal、design、spec 和 tasks 后再动代码。
2. 开发实现：按 tasks 小步完成，完成一项勾选一项。
3. 测试验证：至少运行相关单测；影响面较大时运行完整 `python -m unittest discover -s tests`。
4. OpenSpec 归档：功能完成后运行 `openspec archive <change> -y`，同步主 specs，确保 `openspec list` 不再残留已完成未归档变更。
5. 代码审核：提交前检查 diff、规范符合度、边界风险、敏感信息和测试覆盖；发现问题先修复再提交。
6. GitHub 提交：确认不包含 `data/`、临时输出、认证文件和本地数据库后，再提交并推送到 `origin/main`。

这个闭环是默认交付标准。除非明确说明“只写文档”或“只做分析”，否则功能开发完成不能停在测试通过，还必须完成 OpenSpec 归档、代码审核和 GitHub 推送。

## 日常命令面

日常命令应继续保持简单：

| 命令 | 日常用途 |
| --- | --- |
| `/sync` | 同步 Codex 报告和项目上下文中的本地工作事实 |
| `/list` | 查看统一任务和工作视图 |
| `/next` | 推荐下一步行动 |
| `/review` | 生成当日工作复盘草稿 |
| `/help` | 查看简化后的命令入口 |

高级命令可以保留，但不应成为日常默认路径。新增能力优先挂到现有命令下，尤其是 `/sync` 和 `/list`，不要轻易增加新的常用命令。

## 边界：Todo 与 WorkItem

`Todo` 和 `WorkItem` 应继续分层：

- `Todo` 用于个人提醒、短任务、杂项事项和带时间点的轻量记录。
- `WorkItem` 用于交付型工作，需要证据、来源身份、状态同步和闭环判断。

不要把 Todo 数量少理解为 Codex 工作没有导入。Codex、Redmine、OpenSpec、MR 和 Playbook 的事实应进入 `WorkItem`，并通过 `/list` 查看。

## 已具备能力

- SQLite 已作为默认本地存储。
- Codex 每日报告从 `data/codex-task-reports/YYYY-MM-DD.json` 和 `.md` 读取。
- `/sync` 可以导入 Codex 报告和项目快照。
- `/list` 已作为统一日常视图。
- `/next` 和 `/review` 提供精简日常入口。
- WorkItem 可以根据 Codex completed 报告同步完成状态。
- 完成信号会写入去重后的 Evidence。
- 已支持稳定身份：`codex-thread:<id>`、`redmine:<id>`、`openspec:<change>`、`gitlab-mr:<project>:<id>`。
- 重复来源可以合并到同一个 WorkItem。
- 对误合并已有 merge audit、split 和 rollback 路径。

## 优先级 1：优化每日分诊

目标：让 `/list` 能直接回答“今天该先处理什么”，不用再手动过滤。

需要补充：

- 为 `/list` 增加默认每日分组：
  - blocked
  - active 且需要行动
  - 等待 MR/Redmine/OpenSpec closeout
  - 最近完成
  - 同步已过期
- 在高优先级条目旁显示简短原因，例如 `blocked by Redmine`、`needs validation`、`MR merged but closeout missing`、`Codex thread still active`。
- 当 WorkItem 今天未同步时增加 `stale` 标记。
- `/list completed` 等详细过滤继续作为高级视图保留。

验收标准：

- 早上运行 `/sync` 后，再运行 `/list` 就足够开始一天工作。
- Todo 提醒和 WorkItem 都应出现，但有交付风险的 WorkItem 应排在低优先级提醒之前。

## 优先级 2：增强完成识别

目标：避免已经完成的 Codex 工作继续显示为未完成。

需要补充：

- 将以下信号视为完成信号：
  - MR/PR 已合并。
  - Redmine 已解决或关闭。
  - OpenSpec change 已归档或 tasks 已完成。
  - Playbook closeout 已验证。
  - 最终验证通过且没有后续必做项。
  - Codex 线程明确报告 cleanup、merge、publish 或 writeback 已完成。
- 默认保持 `done` 不回退。
- 如果已完成项后续又出现在未完成报告中，只记录证据，不自动重开，除非有强显式 reopen 信号。
- `/sync` 摘要中增加“疑似需要人工复核的 reopen 候选项”。

验收标准：

- MR 已合并且 closeout 已验证的 Codex 任务，在下次同步时应转为 done。
- 已 done 的 WorkItem 不应被过期或不完整报告自动重新打开。

## 优先级 3：Redmine 与 MR 只读上下文

目标：让 `ai-node` 能辅助每日交付闭环，但不直接写外部系统。

需要补充：

- 通过 Playbook 读取 Redmine issue 状态、指派人、标题和最新处理字段。
- 通过已有项目工具或 Playbook 读取 Git/MR 状态。
- 将 Redmine 和 MR 事实追加为 Evidence。
- 在 `/list` 中显示 closeout 缺口，例如：
  - MR 存在但未合并。
  - MR 已合并但 Redmine 仍未关闭。
  - Redmine 已解决但缺少本地验证证据。
  - OpenSpec 已完成但尚未归档。
- 除非未来独立 OpenSpec 明确批准写操作，否则外部系统保持只读。

验收标准：

- 即使代码工作看似完成，`/sync` 也能说明某个 WorkItem 为什么仍然 active。

## 优先级 4：早晨计划与晚上复盘

目标：让助手在每天开始和结束时都能提供直接可用的工作视图。

需要补充：

- 早晨计划：
  - 消费昨天和今天的 Codex 报告。
  - 展示最高优先级 active 和 blocked WorkItem。
  - 标出需要用户决策的事项。
  - 推荐现实可执行的第一步。
- 晚上复盘：
  - 按 Evidence 列出已完成事实。
  - 列出阻塞项及原因。
  - 列出明天需要继续同步的事项。
  - 生成普通语言的日报草稿。
- 仍然复用现有命令：
  - `/next` 用于当前下一步。
  - `/review` 用于当日复盘。
  - `/sync` 在二者之前执行。

验收标准：

- 晚上运行 `/review` 的输出，应能作为日常工作记录草稿，而不需要手动打开多个 Codex 线程。

## 优先级 5：周复盘

目标：从多天工作中总结模式，而不是只看单个任务。

需要补充：

- 使用近期 `data/codex-task-reports/` 文件和 WorkItem Evidence。
- 按项目、Redmine issue、OpenSpec change 和 MR 分组。
- 展示：
  - 已完成交付。
  - 长期阻塞工作。
  - 重复出现的失败模式。
  - 在 active 和 blocked 之间反复变化的任务。
  - 多天没有证据更新的 stale WorkItem。

验收标准：

- 周复盘应能帮助判断哪些事项需要关闭、升级、补文档或拆分。

## 优先级 6：个人偏好与工作习惯

目标：让助手适配你的工作习惯，但不要过早引入复杂记忆系统。

需要补充：

- 保留当前短期会话记忆。
- 只保存明确、稳定的偏好，例如：
  - 默认命令风格。
  - 偏好的日报结构。
  - 默认 Redmine closeout 表述风格。
  - 需要关注的项目。
  - 偏好的排序规则。
- 暂不引入复杂总结压缩层。
- 优先使用透明、可编辑的偏好配置，而不是隐藏推断。

验收标准：

- 只有在用户明确表达或稳定重复的工作流中，助手才应记住长期偏好。

## 优先级 7：基于 Playbook 的行动建议

目标：推荐正确的本地下一步命令，但不重复实现 Playbook。

需要补充：

- 根据 WorkItem 上下文识别何时应建议 Playbook 命令。
- 不重新实现 Redmine、workspace、MR 或 closeout 逻辑，这些仍由 Playbook 负责。
- 建议命令默认只读或 dry-run。
- 当用户通过助手执行命令时，将输出追加为 Evidence。

验收标准：

- `/next` 可以给出“运行 Playbook workspace status”或“检查 Redmine issue”这类具体命令，但默认不执行写回动作。

## 优先级 8：数据卫生

目标：让本地状态长期保持可用。

需要补充：

- 为 `data/codex-task-reports/` 制定保留策略。
- 按可配置天数归档或隐藏旧 done WorkItem。
- 检测孤儿 source ref 或 identity。
- 检测因歧义未自动合并的重复 WorkItem。
- 后续可以增加安全的本地清理命令，但不要放入日常命令面。

验收标准：

- 即使积累多周 Codex 报告，`/list` 仍然保持聚焦。

## 建议的 OpenSpec 变更

后续建议拆成小型 OpenSpec change：

| Change id | 目标 | 优先级 |
| --- | --- | --- |
| `improve-daily-work-triage` | 优化 `/list` 分组、stale 标记和下一步原因 | High |
| `strengthen-completion-signal-detection` | 从 MR、Redmine、OpenSpec、Playbook 证据中增强完成识别 | High |
| `add-readonly-closeout-context` | 将 Redmine/MR/OpenSpec closeout 缺口写入 Evidence 并显示在列表中 | High |
| `add-morning-evening-workflow` | 基于 `/sync` 状态生成早晨计划和晚上复盘 | Medium |
| `add-weekly-work-rollup` | 基于报告、WorkItem 和 Evidence 生成周复盘 | Medium |
| `add-preference-backed-prioritization` | 用显式偏好驱动排序和复盘风格 | Medium |
| `add-playbook-action-suggestions` | 推荐已有 Playbook 命令，而不是重复实现 | Medium |
| `add-work-data-hygiene` | 归档或隐藏旧完成项，报告 stale 和重复本地状态 | Low |

## 非目标

- 不新增更多日常命令，除非现有命令无法自然承载该行为。
- 不为 ai-node 导入再创建第二个 Codex 定时任务。
- 没有独立明确提案前，不写 Redmine、GitLab、MR 或远端仓库。
- 不把 Todo 和 WorkItem 存储合并成一张表。
- 在基础日常工作流稳定前，不引入重型记忆压缩层。

## 下一步建议

建议优先启动 `improve-daily-work-triage`。

原因：当前本地数据里 WorkItem 已明显多于 Todo，而你需要的是一个能说明“现在什么最重要”的日常视图。该变更能直接提升每天可用性，同时不会增加外部写风险，也不会增加日常命令数量。
