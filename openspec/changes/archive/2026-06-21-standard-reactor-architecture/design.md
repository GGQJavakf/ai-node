## Context

The current assistant already has useful layers: domain models, repository ports, persistence adapters, LLM clients, tool validation, and tool execution. The main architectural weakness is the orchestration center: `AgentCore.chat()` owns the full interaction loop and mixes pure decisions with IO-heavy effects.

For a personal AI assistant, this loop will keep growing: reminders, planning, memory, external apps, and review workflows all add more event types and side effects. A Reactor runtime gives the project a stable extension point without forcing a full rewrite of CLI, storage, or LLM adapters.

## Goals

- Make the assistant loop explicit as `event -> state -> effects`.
- Keep Reactor decision logic deterministic and unit-testable.
- Keep LLM calls, tool execution, repository writes, and stream parsing outside pure step logic.
- Preserve the public `AgentCore` API during migration.
- Support current tool-call validation retry behavior exactly, including adding `role=tool` messages for failed tool calls.
- Make future capabilities such as reminders, external app effects, and richer memory easier to add.

## Non-Goals

- Do not replace the current LLM clients.
- Do not change tool definitions or tool parameter schemas.
- Do not redesign CLI commands.
- Do not change repository persistence formats.
- Do not implement a fully asynchronous event bus in this change.

## Decisions

### 1. Reactor runtime is application-layer code

The runtime belongs under `src/ai_todo_assistant/application/reactor/` because it orchestrates application use cases but must not depend on presentation details. Infrastructure clients are accessed through injected callables/ports from handlers.

### 2. Step is pure; handlers perform effects

`Reactor.step(state, event)` returns a new state and a list of effects. It must not call the LLM, execute tools, mutate repositories, or write terminal output. Runtime/handlers execute returned effects and feed their results back as events.

### 3. Compatibility facade remains in AgentCore

`AgentCore.chat()` remains the public API used by CLI and tests. It should construct the initial reactor state, execute the runtime loop, update session memory, and return the final user-facing text.

### 4. Tool validation remains before execution

The Reactor must preserve the current safety rule: validate all tool calls before executing any tool in that assistant message. On validation failure, no local tool executes; a tool-role error message is appended for each original tool call and the model is asked to regenerate legal `tool_calls`.

### 5. Maximum tool rounds remains explicit

The existing `MAX_TOOL_ROUNDS` limit stays as a runtime guard. The Reactor state records the current round so tests can verify loop termination without relying on logs.

### 6. Streaming behavior remains conservative

Current streaming only works when no tools are enabled. This change keeps that behavior and models stream parsing as an effect handler concern, not Reactor step logic.

## Reactor Model

- Events:
  - `UserMessageReceived`
  - `LlmResponseReceived`
  - `LlmRequestFailed`
  - `ToolValidationFailed`
  - `ToolExecutionCompleted`
  - `StreamCompleted`
- State:
  - messages sent to the LLM
  - user input
  - tool round count
  - validation failure count
  - final response text
  - stopped reason
- Effects:
  - `RequestLlm`
  - `ExecuteTools`
  - `AppendValidationFailureFeedback`
  - `ParseStream`
  - `ReturnFinal`

## Risks

- A mechanical extraction could preserve behavior but leave hidden IO in step logic. Boundary tests must assert the pure step does not need real clients or repositories.
- Over-generalizing the runtime too early could make the small assistant harder to read. The first implementation should model only current events and effects.
- Existing dirty worktree contains unrelated changes; implementation must avoid broad formatting or cleanup.

## Migration Plan

1. Add failing tests for Reactor state/effect behavior.
2. Implement minimal Reactor model and step transitions.
3. Add an effect runner that reuses current LLM client, tool validation, and `ToolExecutor`.
4. Refactor `AgentCore.chat()` to delegate the orchestration loop to the runtime while preserving public behavior.
5. Run focused agent tests, then the full unittest suite.
