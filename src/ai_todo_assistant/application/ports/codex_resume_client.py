"""Application port for resuming Codex threads."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CodexThreadResumeOutcome:
    success: bool
    message: str = ""


class CodexThreadResumeClient(Protocol):
    def resume_thread(self, thread_id: str, prompt: str) -> CodexThreadResumeOutcome: ...
