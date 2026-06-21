## 1. Reactor Model

- [x] 1.1 Add failing tests for initial user event -> LLM request effect.
- [x] 1.2 Add failing tests for final assistant response -> stopped final state.
- [x] 1.3 Create `application/reactor/events.py` with event dataclasses.
- [x] 1.4 Create `application/reactor/effects.py` with effect dataclasses.
- [x] 1.5 Create `application/reactor/state.py` with `ReactorState`.
- [x] 1.6 Create `application/reactor/core.py` with pure `AgentReactor.step()`.

## 2. Tool Validation Flow

- [x] 2.1 Add failing tests proving invalid tool calls do not execute local tools.
- [x] 2.2 Add failing tests proving valid tool calls become execution effects.
- [x] 2.3 Preserve validation retry feedback message shape from current `AgentCore`.
- [x] 2.4 Preserve validation retry limit behavior.

## 3. Runtime Integration

- [x] 3.1 Add `application/reactor/runtime.py` to execute effects using injected LLM client and tool executor.
- [x] 3.2 Refactor `AgentCore.chat()` to delegate loop orchestration to Reactor runtime.
- [x] 3.3 Keep `AgentCore.clear_history()` and `is_configured()` behavior unchanged.
- [x] 3.4 Preserve current conservative streaming behavior.

## 4. Compatibility and Verification

- [x] 4.1 Update architecture boundary tests for Reactor module importability.
- [x] 4.2 Run focused Reactor and AgentCore tests.
- [x] 4.3 Run full unittest suite.
- [x] 4.4 Run OpenSpec status/list validation.
- [x] 4.5 Perform final code review for accidental IO in pure Reactor step.
