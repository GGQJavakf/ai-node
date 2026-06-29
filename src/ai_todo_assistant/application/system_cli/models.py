"""Models for safe system CLI command execution."""
from __future__ import annotations

from dataclasses import dataclass


READ_ONLY = "read_only"
POLICY_ALLOWED = "allowed"
POLICY_DENIED = "denied"


@dataclass(frozen=True)
class CommandSpec:
    key: str
    title: str
    description: str
    argv: tuple[str, ...]
    timeout_seconds: int = 30
    risk_level: str = READ_ONLY
    stdout_limit: int = 4000
    stderr_limit: int = 2000


@dataclass(frozen=True)
class CommandExecutionRecord:
    command_key: str
    argv: list[str]
    cwd: str
    returncode: int
    success: bool
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    timed_out: bool = False
    missing: bool = False
    output_truncated: bool = False
    risk_level: str = READ_ONLY
    policy_decision: str = POLICY_ALLOWED
    policy_reason: str = ""

    @property
    def status_text(self) -> str:
        return "succeeded" if self.success else "failed"
