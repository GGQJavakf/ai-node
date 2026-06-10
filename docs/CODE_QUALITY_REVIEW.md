# 代码质量与结构评审

## 总体结论

项目已经形成清晰的学习型 Agent 分层：实体层、数据管理层、工具层、推理循环、LLM 适配层和 UI 层基本分离。对本地教学和原型验证来说，当前结构可理解、可运行，也便于继续迭代。

主要短板集中在工程化边界：配置密钥安全、旧版和新版 Agent 并存导致入口认知成本较高、CLI/Agent 工具链测试覆盖仍需继续补强，以及 JSON 文件持久化缺少并发和损坏恢复策略。

当前代码已按开源项目常见 `src/` 布局重排，主包为 `src/ai_todo_assistant`。源码按 DDD 思路拆分为 `domain`、`application`、`infrastructure`、`presentation` 四类边界；原顶层业务模块已经移除，不再在根目录保留兼容门面。

## 主要优点

- 分层基本清晰：`TodoManager` 不直接依赖 UI 或 LLM，`ToolExecutor` 作为 Agent 工具边界，`llm_client.py` 单独封装后端。
- 工具调用教学价值高：`agent_tools.py` 明确列出 JSON Schema 和工具执行流程，适合理解 Function Calling。
- 本地可测试性较好：数据层和 LLM 适配层已有 `unittest` 覆盖，且测试不依赖真实网络。
- 兼容性意识明确：`Todo.due_date` 保留旧字段别名，`llm_client.py` 自动补 `/chat/completions` 后缀。
- 用户入口完整：CLI 和 GUI 都能使用同一个 `TodoManager` 数据文件。

## 主要风险与问题

| 等级 | 问题 | 证据 | 影响 |
| --- | --- | --- | --- |
| 高 | 本地配置文件可能保存真实 API Key | `config/settings.json` 使用 `api_key` 字段，CLI 会读取该文件 | 容易误提交或泄露凭据 |
| 已处理 | 新旧 Agent 配置优先级不一致 | 已新增统一配置加载器 `ai_todo_assistant.infrastructure.config.load_settings` | CLI 和旧版 Agent 使用同一优先级：默认值 < 配置文件 < 环境变量 |
| 已处理 | 时间解析逻辑重复且格式处理不完全一致 | 领域模型和 JSON 仓储已迁移到 `ai_todo_assistant` 并集中解析秒级/分钟级/日期格式 | 降低统计、过期判断和查询逻辑分叉风险 |
| 中 | 流式模式下工具调用被弱化 | `AgentCore.chat(... stream=True)` 解析流式文本后直接返回，注释说明通常不处理工具调用 | 自然语言新增/修改任务依赖模型是否在流式响应中返回工具调用，行为可能不稳定 |
| 中 | CLI 业务逻辑较重 | `TodoCLI` 同时做配置、命令解析、表格渲染、Agent 调用、异常处理 | 单元测试难度较高，后续命令扩展容易膨胀 |
| 中 | JSON 持久化不是原子写 | `TodoManager.save()` 直接写入 `todos.json` | 进程中断或并发运行 CLI/GUI 时可能造成数据损坏或覆盖 |
| 低 | 旧版 `ai_agent.py` 与新版 `agent_core.py` 目标重叠 | 两套 Agent 机制并存：JSON action 模式与 Tool Calling 模式 | 维护者容易不清楚哪个入口是主路径 |
| 低 | 测试覆盖偏向底层 | 现有测试覆盖 `TodoManager`、`Todo`、`llm_client`，缺少 `AgentCore`、`ToolExecutor`、CLI 命令测试 | 回归时难以及时发现自然语言工具链或命令解析问题 |

## 建议改进顺序

1. 先处理凭据安全：将真实 `config/settings.json` 从分发范围中移除，增加 `config/settings.example.json`，文档推荐环境变量。
2. 给 `ToolExecutor` 和 `AgentCore` 增加更多无网络单元测试：通过 fake LLM client 构造 tool_calls，验证多轮工具调用和历史追加。
3. 明确弃用或保留 `ai_agent.py`：如果保留，文档标注“旧版演示”；如果不保留，逐步删除重复逻辑。
4. 下版本将 JSON 持久化替换为 SQLite，届时在 `ai_todo_assistant.infrastructure.persistence` 下新增 SQLite 仓储实现。

## 维护约定建议

- 新增业务能力优先从 `TodoManager` 增加可测试方法，再通过 `ToolExecutor` 暴露给 Agent。
- 新增自然语言能力时同步更新 `TOOL_DEFINITIONS`、`ToolExecutor` 和至少一个 `AgentCore` fake-client 测试。
- CLI 展示逻辑不要反向写入数据规则；数据规则应沉到 `Todo` 或 `TodoManager`。
- 配置文档只写字段名和示例占位符，不写真实密钥。
- 修改时间语义时必须同时跑数据层测试、工具层测试和 CLI 命令 smoke 测试。

## 本次评审验证

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

结果：

```text
Ran 26 tests
OK
```
