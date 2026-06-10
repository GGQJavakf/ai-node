# AI 日常待办管家

一个本地 Python 待办事项管理工具，支持智能命令行、图形界面和本地 JSON 持久化。命令行模式集成 LLM，可以用自然语言创建、查询、更新和总结待办事项。

## 功能特性

- 自然语言管理待办：例如“明天下午三点提醒我开会”“我今天还有哪些没做完”。
- 斜杠命令：在 CLI 中快速执行 `/list`、`/add`、`/stats`、`/delete` 等操作。
- 双入口：`ai_todo_assistant.presentation.cli` 提供智能命令行，`ai_todo_assistant.presentation.gui` 提供 tkinter 图形界面。
- 本地持久化：任务保存在 `todos.json`。
- 状态与统计：支持完成状态、截止时间、优先级、过期任务、即将到期任务和完成率统计。
- LLM 后端可选：支持 OpenAI 兼容接口，也支持复用本机 Codex CLI 登录态。
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

AI 配置文件位于：

```text
config/settings.json
```

也可以使用环境变量覆盖配置文件。建议不要把真实 API Key 写入要提交或分发的配置文件。

### 方式一：OpenAI 兼容 API

`config/settings.json` 示例：

```json
{
  "auth_mode": "openai_api",
  "api_key": "REPLACE_WITH_YOUR_API_KEY",
  "api_base": "https://api.openai.com/v1/chat/completions",
  "model": "gpt-4o-mini",
  "validation_retry_limit": 3,
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
```

### 方式二：Codex CLI 登录态

先完成 Codex 登录：

```powershell
codex login
```

`config/settings.json` 示例：

```json
{
  "auth_mode": "codex_cli",
  "model": "gpt-5.5",
  "codex_command": "codex",
  "codex_timeout": 120,
  "validation_retry_limit": 3,
  "log_level": "ERROR"
}
```

PowerShell 环境变量示例：

```powershell
$env:AI_AUTH_MODE="codex_cli"
$env:AI_MODEL="gpt-5.5"
$env:AI_CODEX_COMMAND="codex"
$env:AI_CODEX_TIMEOUT="120"
$env:AI_VALIDATION_RETRY_LIMIT="3"
```

Codex CLI 模式不会读取或保存 Codex OAuth token，而是通过本机 `codex exec` 调用已登录的 Codex CLI。

`validation_retry_limit` 表示 AI 工具参数未通过本地校验后的最大重试次数。默认值为 `3`；超过次数后程序会停止执行工具，避免错误参数写入本地待办数据。

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

常用斜杠命令：

| 命令 | 说明 |
| --- | --- |
| `/list` | 查看所有待办 |
| `/list today` | 查看今天相关任务 |
| `/list week` | 查看本周任务 |
| `/list month` | 查看本月任务 |
| `/list pending` | 查看未完成任务 |
| `/list completed` | 查看已完成任务 |
| `/list overdue` | 查看已过期任务 |
| `/list upcoming` | 查看即将到期任务 |
| `/add [high|medium|low] <标题>` | 新增任务 |
| `/search <关键词>` | 搜索任务 |
| `/toggle <ID>` | 切换完成状态 |
| `/update <ID> [title|end_time|priority|desc] <值>` | 更新任务字段 |
| `/delete <ID>` | 删除任务 |
| `/stats` | 查看统计 |
| `/clear` | 清除已完成任务 |
| `/history` | 查看本次 CLI 命令历史 |
| `/help` | 查看帮助 |
| `/exit` 或 `/quit` | 退出 |

退出方式：

- 输入 `/exit` 或 `/quit`
- 按两次 `Ctrl+C`
- 按 `Ctrl+D`

## 数据文件

待办事项默认保存到：

```text
todos.json
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
│       ├── application/     # 应用层：用例服务、Agent 推理和工具执行
│       ├── infrastructure/  # 基础设施层：配置、JSON 持久化、LLM 客户端
│       └── presentation/    # 表现层：CLI、GUI、日历展示
├── tests/               # 单元测试和结构约束测试
├── examples/            # 示例脚本和示例数据
├── config/              # 本地 AI 配置
├── docs/                # 设计、评审和归档文档
├── pyproject.toml       # Python 包元数据和命令入口
├── requirements.txt
├── README.md
└── todos.json           # 本地运行数据
```

核心包结构：

```text
src/ai_todo_assistant/
├── domain/
│   └── models.py
├── application/
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

## 许可

MIT License
