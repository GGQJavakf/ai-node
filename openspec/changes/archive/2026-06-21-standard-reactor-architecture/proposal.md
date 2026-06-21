## Why

当前 `AgentCore` 同时负责上下文构建、LLM 调用、工具校验、工具执行、短期记忆更新和错误处理，已经形成“可运行但难演进”的集中式控制器。要把项目推进成个人 AI 助手，需要把推理循环改造成标准 Reactor 架构，让决策、状态转换和副作用执行有清晰边界。

## What Changes

- 引入标准 Reactor runtime：用事件驱动的 step 循环表达用户输入、LLM 响应、工具调用、工具结果、校验失败和最终回复。
- 将可变会话状态收敛到 `ReactorState`，包括消息、工具轮次、校验失败次数和最终输出。
- 将外部副作用建模为 effect，由 handler 统一执行，包括 LLM 请求、工具执行、流式解析和错误恢复。
- 保留 `AgentCore.chat()` 作为兼容 facade，CLI、GUI 和既有测试不需要立即改入口。
- 建立架构边界测试，防止后续把 LLM、工具执行或持久化副作用重新塞回 Reactor 决策逻辑。
- 不引入新的三方依赖，不改变现有工具 schema、仓储 API 或用户命令行为。

## Capabilities

### New Capabilities

- `reactor-agent-runtime`: 个人助手 Agent 的标准 Reactor 运行时，包括事件、状态、step、effect、handler 和兼容 facade。

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `src/ai_todo_assistant/application/agent/core.py`
  - `src/ai_todo_assistant/application/agent/tool_executor.py`
  - New files under `src/ai_todo_assistant/application/reactor/`
  - Tests under `tests/`
- Affected behavior:
  - Natural-language chat should remain externally compatible.
  - Tool validation retry behavior must remain unchanged.
  - Session memory and long-term preferences must remain available in prompts.
- Dependencies:
  - No new runtime dependency.
  - Use standard library dataclasses/enums/typing only.
