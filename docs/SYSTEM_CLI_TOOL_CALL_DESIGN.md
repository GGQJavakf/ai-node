# 系统 CLI 工具调用设计

本文档设计 `ai-node` 如何支持通过本地系统 CLI 执行受控命令，并把执行结果纳入现有工具调用、WorkItem 和 Evidence 工作流。目标是让助手能读取和编排本机工作事实，同时保持可审计、可测试、可逐步扩展的安全边界。

## 背景

当前 `ai-node` 已经具备以下基础能力：

- CLI 命令面已收敛到 `/sync`、`/list`、`/next`、`/review` 和 `/help`。
- Agent 工具调用已有本地校验链路：模型返回 tool call 后，先通过 Pydantic 参数模型和白名单校验，再进入执行器。
- Reactor 主循环已把 LLM 响应、工具执行结果和重试都纳入状态机。
- `CommandRunner` 已支持 `shell=False`、timeout、stdout/stderr 捕获、命令不存在和超时降级。
- 工作流事实已沉淀到 `WorkItem` 和追加式 `Evidence`，可用于日报、closeout 草稿和下一步建议。
- Git、OpenSpec、Playbook、Codex resume 等场景已经以 connector 或 client 形式存在。

因此，本设计不新建一套执行框架，而是在现有 agent/tool/workflow 架构上补齐一层“系统 CLI 工具能力”。

## 目标

1. 允许助手通过工具调用执行受控的本地 CLI 命令。
2. 允许用户通过 slash command 手动触发同一套系统 CLI 能力。
3. 对模型暴露能力目录，而不是暴露任意 shell。
4. 所有命令执行前经过参数校验、命令白名单、cwd 边界和风险策略门禁。
5. 所有执行结果都有结构化记录，可选择追加到 WorkItem Evidence。
6. 命令失败、超时、缺失、被策略拒绝时也必须返回 tool 结果，保持 tool-call 协议完整。
7. 分阶段实现，先只读，再本地写，再按独立 OpenSpec 审批外部写。

## 非目标

- 不提供通用 `run_shell(command: string)` 能力。
- 不允许模型直接拼接 PowerShell、cmd、bash 或 shell 管道。
- 不在第一阶段支持外部系统写操作，例如 Redmine 写回、GitLab MR merge、push、发布、登记工时。
- 不绕过 Playbook、OpenSpec、Git 等现有工具的边界重新实现业务逻辑。
- 不把完整 stdout/stderr 长日志塞入 LLM 上下文或 Evidence 摘要。
- 不新增另一个日常同步入口，仍以 `/sync` 为主入口。

## 核心原则

### 能力目录优先

系统 CLI 能力必须通过 command catalog 暴露。例如：

- `git.status`
- `git.diff_stat`
- `openspec.list`
- `openspec.validate`
- `playbook.workspace_status`
- `codex.resume_preview`

模型只能选择 catalog 中的命令项，并提供结构化参数。应用代码负责把命令项转换为 `argv: list[str]`。

### 默认只读

首阶段只允许读取事实、dry-run 和验证命令。会修改文件、数据库、远端系统或 Git 历史的命令不进入默认 catalog。

### 执行和解释分离

本地系统负责校验、执行、截断、记录和停止。LLM 负责理解意图、选择候选工具、读取工具结果并组织自然语言回复。

### slash command 和 tool call 共用服务

用户手动输入 `/sync`、`/work evidence ...`、未来的 `/system ...`，以及 LLM tool call，应调用同一层 application service。CLI 只做解析和展示，不复制执行逻辑。

### 证据优先

和交付型工作相关的命令结果应能追加为 Evidence。Evidence 记录事实摘要、命令、cwd、退出码、截断输出、风险等级和时间，而不是保存不可控长日志。

## 总体架构

```text
用户输入
  -> TodoCLI slash command
      -> SystemCliService
      -> CommandPolicyGate
      -> CommandCatalog
      -> CommandRunner
      -> CommandExecutionRecord
      -> EvidenceService 可选记录

用户自然语言
  -> LLM
  -> AgentReactor
  -> validate_tool_calls
  -> ToolRegistry
  -> ToolPolicyGate
  -> SystemCliService
  -> CommandPolicyGate
  -> CommandRunner
  -> role=tool 结果
  -> LLM 总结
```

建议新增或调整的模块：

```text
src/ai_todo_assistant/application/agent/tool_registry.py
src/ai_todo_assistant/application/system_cli/catalog.py
src/ai_todo_assistant/application/system_cli/policy.py
src/ai_todo_assistant/application/system_cli/service.py
src/ai_todo_assistant/application/system_cli/models.py
src/ai_todo_assistant/infrastructure/connectors/command_runner.py
```

`command_runner.py` 可复用现有实现，必要时只做小幅增强，例如输出截断、duration、环境变量白名单和 cwd 规范化。

## 领域模型

### ToolRegistry

当前工具配置分散在参数模型、描述和执行器分发中。建议引入注册中心统一描述：

```python
@dataclass(frozen=True)
class ToolDefinitionSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler_name: str
    risk_level: str
    side_effect: str
    allowed_contexts: set[str]
```

字段含义：

| 字段 | 说明 |
| --- | --- |
| `name` | 工具名，对外暴露给 LLM |
| `description` | tool definition 描述 |
| `args_model` | Pydantic 参数模型 |
| `handler_name` | 执行器中的 handler 标识 |
| `risk_level` | `read_only`、`local_write`、`external_write`、`destructive` |
| `side_effect` | `none`、`local_fs`、`local_db`、`git_local`、`external_system` |
| `allowed_contexts` | `llm_tool`、`slash_command`、`watch`、`manual_only` |

### CommandCatalog

命令目录负责把稳定 command key 转换为具体 argv。

```python
@dataclass(frozen=True)
class CommandSpec:
    key: str
    title: str
    description: str
    argv_template: list[str]
    default_timeout_seconds: int
    risk_level: str
    side_effect: str
    cwd_policy: str
    output_limit: int
    record_evidence_by_default: bool
    allowed_args_schema: type[BaseModel]
```

示例 catalog：

| key | argv | 风险 | 说明 |
| --- | --- | --- | --- |
| `git.status` | `git status --short` | `read_only` | 读取当前仓库脏状态 |
| `git.branch` | `git branch --show-current` | `read_only` | 读取当前分支 |
| `git.diff_stat` | `git diff --stat` | `read_only` | 读取未提交 diff 概览 |
| `openspec.list` | `openspec list --json` | `read_only` | 读取 OpenSpec change 列表 |
| `openspec.validate` | `openspec validate --strict` | `read_only` | 校验 OpenSpec 变更或 specs |
| `playbook.workspace_status` | `playbook workspace status --output json` | `read_only` | 读取 workspace 状态 |
| `codex.resume_preview` | 内部 service dry-run | `read_only` | 预览可推进 Codex 线程 |

后续 local write catalog 可以另行启用：

| key | argv | 风险 | 说明 |
| --- | --- | --- | --- |
| `openspec.archive` | `openspec archive <change> -y` | `local_write` | 本地归档 OpenSpec 变更 |
| `git.add_explicit` | `git add -- <paths>` | `local_write` | 显式 stage 指定文件 |
| `ruff.check_fix` | `ruff check --fix <paths>` | `local_write` | 本地格式或 lint 修复 |

外部写命令不进入默认 catalog。若未来需要支持，必须通过独立 OpenSpec 明确审批。

### SystemCliRequest

给 LLM 暴露的工具参数应稳定、收敛：

```python
class SystemCliRequest(ToolArgsModel):
    command_key: str
    cwd: str | None = None
    args: dict[str, str | int | bool | list[str]] = {}
    work_item_id: str | None = None
    record_evidence: bool = False
    reason: str = ""
```

约束：

- `command_key` 必须存在于 catalog。
- `args` 必须再按对应 `allowed_args_schema` 校验。
- `cwd` 为空时使用项目根或当前 WorkItem 绑定路径。
- `cwd` 必须在允许根目录内。
- `record_evidence=true` 只允许对 `read_only` 或已批准的 `local_write` 命令生效。

### CommandExecutionRecord

执行结果内部结构：

```python
@dataclass(frozen=True)
class CommandExecutionRecord:
    command_key: str
    argv: list[str]
    cwd: str
    returncode: int
    success: bool
    stdout_excerpt: str
    stderr_excerpt: str
    timed_out: bool
    missing: bool
    duration_ms: int
    risk_level: str
    side_effect: str
    policy_decision: str
    policy_reason: str
    started_at: str
```

返回给 LLM 的文本应是这个结构的短摘要，而不是原始长输出：

```text
[system_cli] git.status succeeded
cwd: D:\IdeaProjects\npki\ai\ai-node
exit_code: 0
stdout:
 M docs/SYSTEM_CLI_TOOL_CALL_DESIGN.md
```

## 策略门禁

### 风险分级

| 风险 | 自动 tool call | slash command | watch 自动触发 | 说明 |
| --- | --- | --- | --- | --- |
| `read_only` | 允许 | 允许 | 可允许 | 读取状态、验证、dry-run |
| `local_write` | 默认禁用 | 可手动启用 | 禁用 | 修改本地文件、数据库、Git index |
| `external_write` | 禁用 | 需要独立审批 | 禁用 | 写 Redmine、GitLab、MR、远端服务 |
| `destructive` | 禁用 | 禁用或强人工确认 | 禁用 | 删除、reset、清库、强制覆盖 |

### cwd 边界

每次执行前必须规范化 cwd：

1. 解析为绝对路径。
2. 校验路径存在。
3. 校验路径在允许根内，例如项目根、配置的 workspace 根、WorkItem 绑定项目路径。
4. 禁止使用 `..` 逃逸、UNC 不可信路径、空路径回退到未知目录。
5. 记录最终 cwd。

### argv 边界

命令必须是 `list[str]`，不得经过 shell：

- 禁止 `shell=True`。
- 禁止拼接单个 command string。
- 禁止模型传入 `|`、`;`、`&&`、重定向等 shell 控制符作为命令结构。
- 可允许这些字符作为普通参数值，但必须由具体 command spec 明确声明。

### 输出边界

默认输出截断：

- stdout excerpt 默认 4000 字符。
- stderr excerpt 默认 2000 字符。
- Evidence 摘要默认 1200 字符。
- 完整输出默认不保存。若未来需要保存，应写入本地 artifact，并在 Evidence 中记录 artifact 路径和 hash。

### 环境变量边界

默认继承最小环境即可。若未来需要配置：

- 使用 env allowlist。
- 不把 token、cookie、password 写入 Evidence。
- stderr/stdout 进入 Evidence 前做敏感信息脱敏。

## 和现有 CLI 的关系

新增能力不应扩散日常命令面。

推荐命令：

| 命令 | 用途 |
| --- | --- |
| `/sync` | 继续作为统一同步入口，可内部调用 read-only system CLI catalog |
| `/next` | 可以推荐要执行的系统命令，默认不执行高风险命令 |
| `/review` | 可汇总系统命令 Evidence |
| `/work evidence add` | 手动追加命令事实 |
| `/system list` | 高级命令，查看可用 command catalog |
| `/system run <key> [args]` | 高级命令，手动执行只读 catalog 命令 |
| `/system policy` | 查看策略配置和当前允许根 |

`/system` 是高级入口，不应出现在日常首屏主命令中。

## 和工具调用的关系

新增工具名建议为 `run_system_cli`，但首阶段只允许只读 command catalog。

工具描述要明确：

- 只能执行系统预置的 command key。
- 不能执行任意 shell。
- 写操作默认不可用。
- 需要工作项证据时传 `work_item_id` 和 `record_evidence=true`。

校验链路：

```text
LLM tool call
  -> validate_tool_calls
  -> SystemCliRequest Pydantic 校验
  -> command_key 存在性校验
  -> command args schema 校验
  -> ToolPolicyGate
  -> CommandPolicyGate
  -> CommandRunner
  -> CommandExecutionRecord
  -> tool result text
```

失败也必须返回 tool result：

| 失败类型 | tool result |
| --- | --- |
| 未知工具 | `[参数错误] 未知工具` |
| 未知 command key | `[策略拒绝] unknown command_key` |
| cwd 越界 | `[策略拒绝] cwd outside allowed roots` |
| 命令缺失 | `[执行失败] command missing` |
| 超时 | `[执行失败] timed out after Ns` |
| 非零退出码 | `[执行完成] failed exit_code=N` |

## Evidence 记录设计

当 `record_evidence=true` 或 command spec 要求默认记录时，系统追加 Evidence。

建议 Evidence 字段映射：

| Evidence 字段 | 值 |
| --- | --- |
| `source` | `system-cli` 或具体来源如 `git`、`openspec`、`playbook` |
| `evidence_type` | `command` |
| `command` | 规范化命令文本，例如 `git status --short` |
| `summary` | 成功/失败摘要和关键输出 |
| `metadata` | command key、cwd、exit code、duration、risk、hash |
| `success` | `CommandExecutionRecord.success` |

去重策略：

- 对 read-only 同步命令，可以按 `work_item_id + command_key + cwd + stdout_hash + date` 去重。
- 对失败命令，可以保留首次失败和状态变化后的失败，避免 watch 每轮刷屏。
- 对显式手动执行，可以允许重复记录，但摘要中标明 manual run。

## 分阶段实现计划

### 阶段 0：设计与测试骨架

目标：锁定行为边界，不改变现有运行行为。

任务：

- 新增 OpenSpec change，描述 system CLI tool call 能力。
- 增加 `system_cli` application 包骨架。
- 增加单测用 fake runner 和 fake catalog。
- 明确 read-only、local-write、external-write 的风险枚举。
- 设计 `/system` help 文案，但不接入主 help 首屏。

验收：

- 测试能覆盖 policy、catalog、record 模型。
- 现有 `python -m unittest discover -s tests` 通过。
- `/help` 主命令仍保持 `/sync`、`/list`、`/next`、`/review`、`/help` 优先。

### 阶段 1：只读 command catalog

目标：支持可审计的只读系统命令执行。

首批 command key：

- `git.branch`
- `git.status`
- `git.diff_stat`
- `openspec.list`
- `openspec.validate`
- `playbook.workspace_status`

任务：

- 实现 `CommandCatalog`。
- 实现 `SystemCliService.run(request)`。
- 复用或增强 `CommandRunner`，补 duration 和输出截断。
- 实现 cwd allowlist。
- 增加 `/system list` 和 `/system run <key>` 高级入口。
- 输出结构化摘要，不写 Evidence 默认可配置。

验收：

- 未知 command key 被拒绝。
- cwd 越界被拒绝。
- 命令缺失返回 missing record，不抛异常。
- 超时返回 timed_out record。
- read-only 命令可从 slash command 执行。

### 阶段 2：接入 LLM tool call

目标：让模型能通过 `run_system_cli` 调用只读 catalog。

任务：

- 新增 `RunSystemCliArgs` Pydantic 模型。
- 将 `run_system_cli` 注册到 ToolRegistry 或现有 `TOOL_ARG_MODELS`。
- 在 `ToolExecutor` 中接入 `SystemCliService`。
- tool result 必须始终返回短摘要。
- 参数错误继续走现有 validation retry 协议。
- 补齐 tool-call 测试：成功、策略拒绝、命令失败、每个 call_id 都有 tool message。

验收：

- LLM 不能调用 catalog 外命令。
- LLM 不能传未知字段绕过校验。
- LLM 不能通过 `args` 注入 shell 结构。
- tool-call 失败不会破坏后续对话协议。

### 阶段 3：Evidence 集成

目标：命令执行事实能进入 WorkItem。

任务：

- `SystemCliRequest` 支持 `work_item_id` 和 `record_evidence`。
- `SystemCliService` 调用 Evidence service 追加命令证据。
- `/system run` 支持 `--evidence <work-id>`。
- `/sync` 内部可将关键只读快照作为 Evidence。
- 实现 Evidence 去重策略，避免 watch 重复写同一失败。

验收：

- 指定 WorkItem 时成功写入 Evidence。
- 未指定 WorkItem 时不乱建工作项，除非 command spec 明确声明。
- Evidence 中不保存超长日志。
- watch 场景不会每轮追加重复失败 Evidence。

### 阶段 4：统一 workflow connector

目标：让现有 Git/OpenSpec/Playbook connectors 复用 system CLI 基础能力。

任务：

- 将现有 connector 的底层执行收敛到 `SystemCliService` 或共享 `CommandRunner` 增强能力。
- `WorkflowSyncService.sync_project()` 读取同样的 `CommandExecutionRecord`。
- 保持现有 `SourceSnapshot` 对外格式兼容。
- 将 invalid JSON、PostHog 噪声、命令缺失等已知降级行为保留。

验收：

- 现有 workflow sync 测试通过。
- `/sync --dry-run` 仍不写 Evidence。
- `/sync status` 仍只读。
- 旧 connector 行为不因为新服务变成外部写。

### 阶段 5：受控 local write

目标：支持明确、低风险、可回滚的本地写操作。

候选命令：

- `ruff.check_fix`
- `openspec.archive`
- `git.add_explicit`
- 本地报告 import 或本地 cache 清理

任务：

- 新增 `local_write` policy。
- Slash command 可手动执行，LLM tool call 默认仍禁用。
- 每个 local write command 必须有显式参数 schema。
- 必须记录 Evidence 或操作日志。
- 必须提供 dry-run 或 preview，如果底层工具支持。

验收：

- local write 不进入 watch 自动触发。
- LLM 默认不能自动执行 local write。
- 执行前后能看到明确 diff、输出或 Evidence。
- 失败不会留下不明状态。

### 阶段 6：外部写能力评审

目标：为未来可能的 Redmine/GitLab/MR 写操作建立审批入口，而不是默认实现。

前置条件：

- 独立 OpenSpec 提案。
- 明确外部系统、权限、幂等策略、失败回滚、审计记录。
- 明确哪些命令只能 manual-only。
- 明确不能由 watch 自动触发。

候选能力：

- Redmine 字段回写。
- GitLab MR 评论回复。
- Git push 或 draft PR 创建。
- Playbook closeout apply。

验收：

- 未通过独立设计评审前，系统 CLI catalog 不出现 external write。
- 即使未来支持，也必须默认人工显式触发，不允许模型静默执行。

## 测试策略

### 单元测试

- `CommandCatalog`：已知 key、未知 key、参数 schema。
- `CommandPolicyGate`：风险、cwd、上下文、record_evidence 权限。
- `SystemCliService`：成功、失败、missing、timeout、输出截断。
- `ToolValidation`：未知字段、错误类型、非法 command key。
- `ToolExecutor`：`run_system_cli` 分发和错误返回。

### CLI 测试

- `/system list` 显示 catalog。
- `/system run git.status` 成功。
- `/system run unknown` 返回策略拒绝。
- `/system run ... --cwd <越界路径>` 被拒绝。
- `/help` 主命令不被 `/system` 稀释。

### Reactor / tool-call 测试

- LLM 返回合法 `run_system_cli` 时执行只读命令。
- LLM 返回未知 command key 时不执行，并返回 tool message。
- 参数校验失败时走已有 retry。
- 多 tool_calls 中每个 call_id 都有结果。

### Workflow 测试

- record evidence 成功写入 WorkItem。
- dry-run 不写 Evidence。
- 重复命令结果按策略去重。
- `/sync` 兼容现有 SourceSnapshot。

## 配置建议

环境变量或配置项：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `system_cli_enabled` | `true` | 是否启用系统 CLI 服务 |
| `system_cli_llm_enabled` | `false` 到阶段 2 后改为 `true` | 是否允许 LLM tool call |
| `system_cli_allowed_roots` | `project_root` | 允许执行 cwd 根目录 |
| `system_cli_default_timeout` | `30` | 默认超时秒数 |
| `system_cli_stdout_limit` | `4000` | stdout 摘要上限 |
| `system_cli_stderr_limit` | `2000` | stderr 摘要上限 |
| `system_cli_local_write_enabled` | `false` | 是否启用本地写 catalog |
| `system_cli_external_write_enabled` | `false` | 是否启用外部写 catalog，默认长期关闭 |

## 安全与失败模式

| 风险 | 防护 |
| --- | --- |
| 命令注入 | 只接受 catalog key，生成 argv list，`shell=False` |
| cwd 逃逸 | 绝对路径规范化和 allowed roots 校验 |
| 模型越权 | ToolRegistry 风险标记和 policy gate |
| 输出污染上下文 | 截断、摘要、敏感信息脱敏 |
| watch 重复写 Evidence | prompt/hash 或 command/hash 去重 |
| 外部系统误写 | external write 默认禁用，独立 OpenSpec 审批 |
| 协议断裂 | 所有失败路径都返回对应 tool result |
| 本地写不可回滚 | local write 默认 manual-only，优先 dry-run 和显式路径 |

## 兼容边界

- 保留现有 `CommandRunner` 的无 shell 执行模型。
- 保留现有 `ToolValidationError` 和 retry 行为。
- 保留 `/sync` 作为同步入口。
- 保留 WorkItem/Evidence 作为工作事实沉淀层。
- 保留 Git/OpenSpec/Playbook connector 当前对外快照格式。
- 不改变已有 Todo 工具行为。

## 推荐首个 OpenSpec 变更拆分

建议不要一次实现所有阶段。首个变更只覆盖阶段 0 到阶段 2：

```text
change id: add-system-cli-tool-catalog

scope:
- 新增只读 System CLI catalog。
- 新增 /system list 和 /system run 高级命令。
- 新增 run_system_cli tool call，但仅允许 read_only command。
- 不写外部系统。
- Evidence 记录只做接口预留，不默认写。
```

第二个变更再做 Evidence 集成：

```text
change id: record-system-cli-evidence

scope:
- 支持 record_evidence。
- 接入 WorkItem Evidence。
- 增加去重。
- 让 /sync 可使用只读命令结果沉淀快照证据。
```

第三个变更再讨论 local write：

```text
change id: enable-manual-local-cli-actions

scope:
- 仅 manual-only。
- 仅本地写。
- 每个 command 单独 schema 和测试。
- 仍不支持 external write。
```

## 最小可交付切片

最小闭环可以只做：

1. `CommandSpec`、`CommandCatalog`、`SystemCliService`。
2. `git.status` 和 `git.branch` 两个只读命令。
3. `/system list` 和 `/system run git.status`。
4. `run_system_cli` tool call。
5. policy 测试、CLI 测试、tool-call 测试。

这个切片能证明完整链路：

```text
LLM 选择工具
  -> 参数校验
  -> 策略门禁
  -> 无 shell 执行
  -> tool result 回灌
  -> 助手总结
```

后续再扩展 OpenSpec、Playbook、Evidence 和 local write，不需要重做主架构。
