"""Events consumed by the agent Reactor."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserMessageReceived:
    content: str


@dataclass(frozen=True)
class LlmResponseReceived:
    message: dict


@dataclass(frozen=True)
class ToolExecutionCompleted:
    results: list[dict]
