"""Effects emitted by the pure agent Reactor."""
from __future__ import annotations

from dataclasses import dataclass

from ai_todo_assistant.application.agent.tool_validation import ValidatedToolCall


@dataclass(frozen=True)
class RequestLlm:
    payload: dict
    stream: bool


@dataclass(frozen=True)
class ExecuteTools:
    calls: list[ValidatedToolCall]
