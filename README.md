# AI 日常待办管家

一个本地 Python 待办事项管理工具，支持智能命令行、图形界面和本地 SQLite 持久化。命令行模式集成 LLM，可以用自然语言创建、查询、更新和总结待办事项。

## 功能特性

- 自然语言管理待办：例如“明天下午三点提醒我开会”“我今天还有哪些没做完”。
- 斜杠命令：在 CLI 中快速执行 `/list`、`/add`、`/stats`、`/delete` 等操作。
- 双入口：`ai_todo_assistant.presentation.cli` 提供智能命令行，`ai_todo_assistant.presentation.gui` 提供 tkinter 图形界面。
- 本地持久化：任务默认保存在 `data/todos.db`，兼容旧版 `todos.json` 自动迁移。
- 状态与统计：支持完成状态、截止时间、优先级、过期任务、即将到期任务和完成率统计。
- LLM 后端默认使用 OpenAI 兼容 API Key，也保留 Codex 登录态作为可选后备。
- 本地工具参数校验：AI 返回的工具参数必须通过本地校验，失败会自动重试，默认最多重试 3 次。

## 环境准备

推荐 Python 3.10+。

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

开发模式推荐安装为 editable 包：

```powershell
python -m pip install -e .
```

依赖列表：

- `rich>=13.0.0`
- `prompt_toolkit>=3.0.0`
- `pydantic>=2.7,<3`

## 配置 AI 后端

默认配置模板位于：

```text
config/settings.example.json
```

本地运行配置位于：

```text
config/settings.local.json
```

首次配置时复制模板：

```powershell
Copy-Item config/settings.example.json config/settings.local.json
```

`config/settings.local.json` 已加入 `.gitignore`，用于本机运行和测试，不提交。也可以使用环境变量覆盖本地配置。旧的 `config/settings.json` 仍作为兼容入口，但不建议继续把真实 API Key 写在可提交文件中。

### 方式一：OpenAI 兼容 API（默认）

`config/settings.local.json` 示例：

```json
{
  "auth_mode": "openai_api",
  "api_key": "REPLACE_WITH_YOUR_API_KEY",
  "api_base": "https://api.openai.com/v1/chat/completions",
  "model": "gpt-4o-mini",
  "validation_retry_limit": 3,
  "session_memory_limit": 20,
  "storage_backend": "sqlite",
  "sqlite_path": "data/todos.db",
  "auto_migrate_json": true,
  "log_level": "ERROR"
}
```

PowerShell 环境变量示例：

```powershell
$env:AI_AUTH_MODE="openai_api"
$env:AI_API_KEY="REPLACE_WITH_YOUR_API_KEY"
$env:AI_API_BASE="https://api.openai.com/v1/chat/completions"
$env:AI_MODEL="gpt-4o-mini"
$env:AI_VALIDATION_RETRY_LIMIT="3"
$env:AI_SESSION_MEMORY_LIMIT="20"
$env:TODO_STORAGE_BACKEND="sqlite"
$env:TODO_SQLITE_PATH="data/todos.db"
```

### 方式二：Codex 登录态

先完成 Codex 登录：

```powershell
codex login
```

`config/settings.local.json` 示例：

```json
{
  "auth_mode": "codex_cli",
  "model": "gpt-5.3-codex-spark",
  "codex_command": "codex",
  "codex_timeout": 120,
  "codex_request_timeout": 240,
  "codex_use_app_server": true,
  "codex_app_server_timeout": 240,
  "codex_home": "data/codex_home",
  "codex_ignore_user_config": true,
  "codex_ignore_rules": true,
  "validation_retry_limit": 3,
  "session_memory_limit": 20,
  "storage_backend": "sqlite",
  "sqlite_path": "data/todos.db",
  "auto_migrate_json": true,
  "log_level": "ERROR"
}
```

PowerShell 环境变量示例：

```powershell
$env:AI_AUTH_MODE="codex_cli"
$env:AI_MODEL="gpt-5.3-codex-spark"
$env:AI_CODEX_COMMAND="codex"
$env:AI_CODEX_TIMEOUT="120"
$env:AI_CODEX_REQUEST_TIMEOUT="240"
$env:AI_CODEX_USE_APP_SERVER="true"
$env:AI_CODEX_APP_SERVER_TIMEOUT="240"
$env:AI_CODEX_HOME="data/codex_home"
$env:AI_CODEX_IGNORE_USER_CONFIG="true"
$env:AI_CODEX_IGNORE_RULES="true"
$env:AI_VALIDATION_RETRY_LIMIT="3"
$env:AI_SESSION_MEMORY_LIMIT="20"
$env:TODO_STORAGE_BACKEND="sqlite"
$env:TODO_SQLITE_PATH="data/todos.db"
```

Codex 模式不会读取或保存新的 Codex token，而是复用本机 `codex login` 的登录态。默认优先启动 `codex app-server --listen stdio://`，并把 `auth.json` 复制到项目私有的 `data/codex_home`，只复用 Codex auth，不加载用户个人 `~/.codex` 下的插件、MCP、hooks 和用户配置；如果 app-server 不可用，会回退到 `codex exec`，并给 `codex exec` 增加 `--ignore-user-config --ignore-rules`。

`data/codex_home` 会包含复制后的 Codex 登录文件，已在 `.gitignore` 中排除，不能提交到仓库。

`validation_retry_limit` 表示 AI 工具参数未通过本地校验后的最大重试次数。默认值为 `3`；超过次数后程序会停止执行工具，避免错误参数写入本地待办数据。

`session_memory_limit` 表示当前运行期间短期会话记忆最多保留的消息条数。默认值为 `20`，大约等于最近 10 轮 user/assistant 对话；该记忆不持久化，程序退出后清空。

存储相关配置：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `storage_backend` | `sqlite` | 存储后端，可选 `sqlite` 或 `json` |
| `sqlite_path` | `data/todos.db` | SQLite 数据库文件路径 |
| `todo_data_file` | `todos.json` | 旧版 JSON 数据文件路径 |
| `workflow_data_file` | `data/workflow.json` | JSON 后端下的工作流数据文件路径 |
| `codex_task_report_dir` | `data/codex-task-reports` | Codex 每日任务报告目录 |
| `codex_resume_enabled` | `true` | `/r all` 是否通过本机 Codex CLI 推进会话 |
| `codex_resume_timeout` | `240` | 单次 Codex resume 调用超时时间（秒） |
| `codex_resume_exclusions_file` | `data/codex-resume-exclusions.json` | 不自动推进的 Codex 线程排除列表 |
| `sync_watch_interval_seconds` | `1800` | `/sync watch` 未指定间隔时的本地前台触发间隔 |
| `auto_migrate_json` | `true` | SQLite 空库首次启动时是否从 JSON 自动迁移 |

## 启动应用

智能 CLI：

```powershell
python -m ai_todo_assistant
```

安装 editable 包后也可以运行：

```powershell
ai-todo
```

GUI：

```powershell
python -m ai_todo_assistant.presentation.gui
```

## CLI 使用说明

进入 `python -m ai_todo_assistant` 后，可以直接输入自然语言，也可以使用斜杠命令。

自然语言示例：

- `明天下午三点提醒我开会`
- `帮我记录周五下班前要交周报，描述是包含本周所有项目进展`
- `把周报任务标记为完成`
- `我今天还有哪些任务没做完`
- `帮我总结一下当前待办进度`

日常主命令：

| 命令 | 说明 |
| --- | --- |
| `/list` | 统一任务视图，合并 TodoList 和同步工作项 |
| `/sync [路径]` | 统一同步入口，只读同步 Codex 报告和 Git/OpenSpec/Playbook 项目上下文 |
| `/sync watch [秒] [路径]` | 本地前台定时触发 `/sync`，每轮汇报同步结果和下一步建议 |
| `/sync watch --resume [秒] [路径]` | 本地前台定时同步后，推进可继续的 Codex 暂停会话 |
| `/next` | 推荐下一步工作 |
| `/review` | 生成工作日复盘草稿 |
| `/help` | 查看帮助 |

分类帮助：

| 命令 | 说明 |
| --- | --- |
| `/help todo` | 查看 Todo 管理命令 |
| `/help work` | 查看工作流、证据和兼容命令 |
| `/help codex` | 查看 Codex 自动推进指南 |
| `/help prefs` | 查看长期偏好命令 |
| `/help system` | 查看历史、退出和颜色说明 |

高级斜杠命令仍保持兼容：

| 命令 | 说明 |
| --- | --- |
| `/list today` | 查看今天相关任务 |
| `/list week` | 查看本周任务 |
| `/list month` | 查看本月任务 |
| `/list pending` | 查看未完成任务 |
| `/list completed` | 查看已完成任务 |
| `/list all` | 查看所有任务 |
| `/list overdue` | 查看已过期任务 |
| `/list upcoming` | 查看即将到期任务 |
| `/add [high|medium|low] <标题>` | 新增任务 |
| `/today` | 查看今日个人助理简报 |
| `/plan day` | 按优先级和截止时间生成今日计划 |
| `/search <关键词>` | 搜索任务 |
| `/toggle <ID>` | 切换完成状态 |
| `/update <ID> [title|end_time|priority] <值>` | 更新任务字段 |
| `/delete <ID>` | 删除任务 |
| `/stats` | 查看统计 |
| `/clear` | 清除已完成任务 |
| `/preferences` | 查看长期偏好 |
| `/remember <偏好名> <偏好内容>` | 记住长期偏好 |
| `/forget <偏好名>` | 删除长期偏好 |
| `/work add <标题>` | 创建个人工作项 |
| `/work import redmine <id>` | 通过 Playbook 只读导入 Redmine 工作项 |
| `/work status` | 查看 WorkItem 状态、来源、下一步和同步时效 |
| `/work split <work-id> <source> <source-ref> [title]` | 将误合并的来源拆成独立 WorkItem |
| `/work rollback <work-id> <audit-id>` | 根据合并审计回滚一次误合并并恢复独立 WorkItem |
| `/work show <work-id>` | 查看完整来源链、稳定身份、合并审计、冲突和证据 |
| `/work evidence add <work-id> <摘要>` | 为工作项追加证据 |
| `/work evidence summary <work-id>` | 汇总工作项证据 |
| `/codex tasks` | 读取 Codex 每日 JSON/Markdown 任务报告并同步未完成工作项 |
| `/r` | 用序号表预览可推进/跳过的 Codex 暂停会话 |
| `/r <序号>` | 手动推进指定序号 |
| `/r all` | 批量推进所有可继续会话 |
| `/r skip <序号> [reason]` | 排除某个序号，后续批量/定时自动推进会持续跳过 |
| `/r unskip <序号>` | 解除某个序号的自动推进排除 |
| `/r skips` | 查看当前自动推进排除列表 |
| `/sync watch [秒] [路径]` | 保持 CLI 运行并定时触发同步，每轮输出汇报；按 `Ctrl+C` 停止 |
| `/sync watch --resume [秒] [路径]` | 保持 CLI 运行，定时同步后再推进可继续的 Codex 会话 |
| `/continue` | 兼容命令，等同 `/next` |
| `/start day` | 生成工作日启动计划 |
| `/review day` | 兼容命令，等同 `/review` |
| `/history` | 查看本次 CLI 命令历史 |
| `/exit` 或 `/quit` | 退出 |

退出方式：

- 输入 `/exit` 或 `/quit`
- 按两次 `Ctrl+C`
- 按 `Ctrl+D`

## 数据文件

待办事项默认保存到：

```text
data/todos.db
```

如果项目根目录存在旧版 `todos.json`，并且 SQLite 数据库为空，程序会在启动时自动把 JSON 中的待办迁移到 SQLite。迁移不会删除 `todos.json`。

## 个人工作助手

`ai-node` 可以作为个人工作助手编排层使用。它会在本地维护 `WorkItem` 与 `Evidence`，并通过只读 connector 读取 Git、OpenSpec、Playbook 和 Codex 每日任务报告。

安全边界：

- `/sync`、`/work import redmine <id>` 和 Agent workflow 工具只读取外部事实，不写 Redmine/GitLab/MR，不登记工时，不执行 closeout、merge、cleanup 或发布。
- Codex 任务分析通过文件交接完成：Codex 自动化写入 `data/codex-task-reports/YYYY-MM-DD.json` 和同名 `.md`，`ai-node` 只读取这些稳定文件。
- Evidence 是追加式记录，用于日报、closeout 草稿、MR/Redmine 草稿和个人复盘；默认不会把完整日志塞进摘要。
- WorkItem 去重只基于稳定 identity 自动合并，例如 `redmine:<id>`、`openspec:<change>`、`gitlab-mr:<project>:<id>` 和 `codex-thread:<id>`；仅标题相似或跨项目 MR id 不会自动合并，会在同步摘要中计入 `skipped`。
- `/r` 用短表预览最新 Codex report 中的可推进/跳过线程，不发送消息也不写 Evidence；表里的 `#` 序号可直接用于 `/r <序号>`、`/r skip <序号>` 和 `/r unskip <序号>`。
- `/r all` 只会推进 `unfinished` 中有 `thread_id`、有 `resume_prompt` 或 `next_action`、且显式 `resume_eligible=true` 或状态为 `continueable/paused/ready/needs_action/needs_resume` 的线程；兼容旧报告时，普通 `status=unfinished` 且有明确 `next_action`、没有人工确认/用户输入/权限审批等信号的条目会归一化为可推进。`blocked`、`completed`、缺少 thread id、缺少 prompt、或需要用户输入的线程会跳过。
- 批量 `/r all` 和 `/sync watch --resume` 会自动跳过需要用户输入的线程；例如 5 个 Codex 线程中 3 个可继续、2 个需要输入时，只推进 3 个可继续项。可用 `/r skip <序号> [reason]` 持久排除某个线程的自动推进，直到 `/r unskip <序号>` 解除；显式 `/r <序号>` 属于手动动作，不受自动推进排除限制。
- 真正发送 Codex thread message 默认通过本机非交互命令 `codex exec resume --json <thread-id> -` 完成，prompt 通过 stdin 传入，避免完整上下文出现在进程参数里；可用 `AI_CODEX_RESUME_ENABLED=false` 禁用，或用 `AI_CODEX_RESUME_TIMEOUT` 调整超时。命令失败、超时或 Codex CLI 不存在时会 fail-closed，并把首次失败尝试写入本地 Evidence；后续批量/定时自动推进遇到同一 prompt 会跳过，避免 watch 按间隔重复堆 Evidence，显式 `/r <序号>` 仍可手动重试。
- 自动合并会保留 source refs、source identities、evidence 和 merge audit；误合并可通过 `/work rollback <work-id> <audit-id>` 按审计记录回滚，或通过 `/work split <work-id> <source> <source-ref> [title]` 本地拆分，不会写回外部系统。

Codex 每日任务报告 schema 详见：

```text
docs/CODEX_TASK_REPORTS.md
```

如需临时使用旧版 JSON 后端，可以配置：

```json
{
  "storage_backend": "json",
  "todo_data_file": "todos.json"
}
```

单条任务包含以下主要字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 任务唯一 ID |
| `title` | 标题 |
| `description` | 描述 |
| `start_time` | 开始时间 |
| `end_time` | 截止时间 |
| `due_date` | 旧版截止日期字段，等同 `end_time` |
| `priority` | `high`、`medium`、`low` |
| `completed` | 是否完成 |
| `created_at` | 创建时间 |

时间格式支持：

- `YYYY-MM-DD`
- `YYYY-MM-DD HH:MM`
- `YYYY-MM-DD HH:MM:SS`

## 项目结构

```text
ai-node/
├── src/
│   └── ai_todo_assistant/
│       ├── domain/          # 领域层：Todo 实体与领域规则
│       ├── application/     # 应用层：用例服务、端口、Agent 推理和工具执行
│       ├── infrastructure/  # 基础设施层：配置、SQLite/JSON 持久化、LLM 客户端
│       └── presentation/    # 表现层：CLI、GUI、日历展示
├── tests/               # 单元测试和结构约束测试
├── examples/            # 示例脚本和示例数据
├── config/              # 本地 AI 配置
├── data/                # 本地 SQLite 数据，默认不提交
├── docs/                # 设计、评审和归档文档
├── pyproject.toml       # Python 包元数据和命令入口
├── requirements.txt
├── README.md
└── todos.json           # 旧版本地运行数据，默认不提交
```

核心包结构：

```text
src/ai_todo_assistant/
├── domain/
│   └── models.py
├── application/
│   ├── memory/
│   ├── ports/
│   ├── todo_service.py
│   └── agent/
│       ├── core.py
│       ├── tool_definitions.py
│       ├── tool_executor.py
│       ├── tool_models.py
│       ├── tool_validation.py
│       └── legacy_json_agent.py
├── infrastructure/
│   ├── config/
│   ├── llm/
│   └── persistence/
└── presentation/
    ├── cli.py
    ├── gui.py
    └── calendar_view.py
```

## 运行测试

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

## 更多文档

- [代码质量与结构评审](docs/CODE_QUALITY_REVIEW.md)
- [每日工作助手优化路线](docs/DAILY_WORK_ASSISTANT_ROADMAP.md)

## 许可

MIT License
