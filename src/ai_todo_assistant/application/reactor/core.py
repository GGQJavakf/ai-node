"""Pure Reactor state machine for the assistant agent."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from ai_todo_assistant.application.agent.tool_validation import ToolValidationError, validate_tool_calls
from ai_todo_assistant.application.reactor.effects import ExecuteTools, RequestLlm
from ai_todo_assistant.application.reactor.events import (
    LlmResponseReceived,
    ToolExecutionCompleted,
    UserMessageReceived,
)
from ai_todo_assistant.application.reactor.state import ReactorState


class AgentReactor:
    """Decides the next assistant effects from explicit events and immutable state."""

    def __init__(
        self,
        model: str,
        tool_definitions: list[dict],
        validation_retry_limit: int,
        temperature: float = 0.3,
    ):
        self.model = model
        self.tool_definitions = tool_definitions
        self.validation_retry_limit = validation_retry_limit
        self.temperature = temperature

    def step(self, state: ReactorState, event: Any):
        if isinstance(event, UserMessageReceived):
            return self._handle_user_message(state, event)
        if isinstance(event, LlmResponseReceived):
            return self._handle_llm_response(state, event)
        if isinstance(event, ToolExecutionCompleted):
            return self._handle_tool_execution_completed(state, event)
        raise TypeError(f"Unsupported reactor event: {type(event).__name__}")

    def _handle_user_message(self, state: ReactorState, event: UserMessageReceived):
        messages = self._initial_messages(state) + [{"role": "user", "content": event.content}]
        next_state = replace(state, messages=messages)
        return next_state, [self._request_llm_effect(next_state)]

    def _handle_llm_response(self, state: ReactorState, event: LlmResponseReceived):
        assistant_message = event.message
        tool_calls = assistant_message.get("tool_calls")
        if not tool_calls:
            final_text = assistant_message.get("content", "（无回复）")
            return replace(
                state,
                final_response=final_text,
                stop_reason="final",
                validation_failures=0,
            ), []

        try:
            validated_calls = validate_tool_calls(tool_calls, self.tool_definitions)
        except ToolValidationError as exc:
            validation_failures = state.validation_failures + 1
            if validation_failures > self.validation_retry_limit:
                return replace(
                    state,
                    final_response=(
                        f"❌ AI 工具参数连续校验失败 {validation_failures} 次，"
                        f"已停止执行以避免错误操作。\n最后一次错误: {exc}"
                    ),
                    stop_reason="validation_failed",
                    validation_failures=validation_failures,
                ), []
            messages = state.messages + [assistant_message]
            messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "content": f"[参数错误] {exc}",
                }
                for tool_call in tool_calls
            )
            messages.append({
                "role": "user",
                "content": (
                    "你刚才返回的工具调用参数未通过本地校验，工具尚未执行。\n"
                    f"校验错误: {exc}\n"
                    "请重新返回合法的 tool_calls；不要解释，不要输出普通文本。"
                ),
            })
            next_state = replace(state, messages=messages, validation_failures=validation_failures)
            return next_state, [self._request_llm_effect(next_state)]

        next_state = replace(
            state,
            messages=state.messages + [assistant_message],
            validation_failures=0,
            tool_round=state.tool_round + 1,
        )
        return next_state, [ExecuteTools(validated_calls)]

    def _handle_tool_execution_completed(self, state: ReactorState, event: ToolExecutionCompleted):
        tool_messages = [
            {
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "content": result["content"],
            }
            for result in event.results
        ]
        next_state = replace(state, messages=state.messages + tool_messages)
        return next_state, [self._request_llm_effect(next_state)]

    def _initial_messages(self, state: ReactorState) -> list[dict]:
        messages = []
        if state.system_message:
            messages.append(state.system_message)
        messages.extend(state.memory_messages)
        messages.extend(state.messages)
        return messages

    def _request_llm_effect(self, state: ReactorState) -> RequestLlm:
        return RequestLlm(
            payload={
                "model": self.model,
                "messages": state.messages,
                "tools": self.tool_definitions,
                "tool_choice": "auto",
                "temperature": self.temperature,
                "stream": state.stream,
            },
            stream=state.stream,
        )
