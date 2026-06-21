"""State container for the agent Reactor."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReactorState:
    system_message: dict | None = None
    memory_messages: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    stream: bool = False
    validation_failures: int = 0
    tool_round: int = 0
    final_response: str | None = None
    stop_reason: str | None = None
