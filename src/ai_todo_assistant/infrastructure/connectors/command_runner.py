"""Safe command execution helpers for read-only connectors."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    cwd: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.missing

    @property
    def command_text(self) -> str:
        return " ".join(self.args)

    def output_excerpt(self, limit: int = 1200) -> str:
        text = (self.stdout or self.stderr or "").strip()
        return text[:limit]

    def parse_json(self) -> Any:
        return json.loads(self.stdout or "null")


class CommandRunner:
    """Runs commands without a shell and captures concise output."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def run(self, args: list[str], cwd: str = "") -> CommandResult:
        try:
            completed = subprocess.run(
                args,
                cwd=cwd or None,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout,
                shell=False,
                check=False,
            )
            return CommandResult(
                args=args,
                cwd=cwd,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except FileNotFoundError as exc:
            return CommandResult(args=args, cwd=cwd, returncode=127, stderr=str(exc), missing=True)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                args=args,
                cwd=cwd,
                returncode=124,
                stdout=_to_text(exc.stdout),
                stderr=_to_text(exc.stderr),
                timed_out=True,
            )


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
