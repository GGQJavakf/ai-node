# reactor-agent-runtime Specification

## Purpose
TBD - created by archiving change standard-reactor-architecture. Update Purpose after archive.
## Requirements
### Requirement: Reactor step loop

The assistant SHALL expose a Reactor runtime that models the agent loop as deterministic state transitions driven by explicit events.

#### Scenario: User message starts LLM request

- **GIVEN** a configured assistant receives a user message
- **WHEN** the Reactor handles the initial user event
- **THEN** it SHALL append the user message to the LLM message list
- **AND** it SHALL emit an LLM request effect containing the system prompt, prior memory, user message, tool definitions, model, temperature, and stream flag.

#### Scenario: Final assistant message stops the loop

- **GIVEN** the Reactor receives an LLM response with no tool calls
- **WHEN** the response contains assistant text
- **THEN** it SHALL record the text as the final response
- **AND** it SHALL stop without emitting tool execution effects.

### Requirement: Tool validation before side effects

The assistant SHALL validate all tool calls before executing any local tool side effect.

#### Scenario: Valid tool calls execute as effects

- **GIVEN** an LLM response contains valid tool calls
- **WHEN** the Reactor processes the response
- **THEN** it SHALL append the assistant message to the conversation
- **AND** it SHALL emit tool execution effects for the validated calls.

#### Scenario: Invalid tool calls do not execute tools

- **GIVEN** an LLM response contains invalid tool arguments
- **WHEN** local validation fails
- **THEN** no local tool SHALL execute
- **AND** the Reactor SHALL append one `role=tool` validation error message for each original tool call
- **AND** it SHALL append a user retry instruction asking the model to regenerate legal `tool_calls`.

### Requirement: AgentCore compatibility facade

`AgentCore.chat()` SHALL remain the compatibility entry point for presentation code.

#### Scenario: Existing callers keep using AgentCore

- **GIVEN** CLI or tests call `AgentCore.chat(user_input)`
- **WHEN** the Reactor runtime is enabled
- **THEN** the method SHALL return the same user-facing response shape as before
- **AND** existing session memory behavior SHALL remain intact.

### Requirement: Runtime effect boundaries

The Reactor decision step SHALL be testable without real LLM clients, repositories, terminal IO, or network access.

#### Scenario: Step test uses plain in-memory values

- **GIVEN** a unit test constructs Reactor state and events with plain dictionaries and dataclasses
- **WHEN** it calls the Reactor step method
- **THEN** no external IO SHALL be required
- **AND** the returned effects SHALL fully describe required side effects.

