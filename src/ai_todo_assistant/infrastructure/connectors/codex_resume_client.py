"""Command-backed Codex thread resume client."""
from __future__ import annotations

import os
import shutil
import subprocess

from ai_todo_assistant.application.ports.codex_resume_client import CodexThreadResumeOutcome


class CodexCliResumeClient:
    """Resume saved Codex sessions through non-interactive `codex exec resume`."""

    def __init__(self, config: dict):
        self.command = str(config.get("codex_command") or "codex")
        self.timeout = int(config.get("codex_resume_timeout") or config.get("codex_request_timeout") or 240)
        self.cwd = str(config.get("project_root") or os.getcwd())
        self.enabled = _as_bool(config.get("codex_resume_enabled", True))

    def resume_thread(self, thread_id: str, prompt: str) -> CodexThreadResumeOutcome:
        if not self.enabled:
            return CodexThreadResumeOutcome(success=False, message="codex resume disabled")
        base_command = _base_command(self.command)
        if not base_command:
            return CodexThreadResumeOutcome(success=False, message=f"codex command not found: {self.command}")
        args = base_command + ["exec", "resume", "--json", thread_id, "-"]
        try:
            proc = subprocess.run(
                args,
                cwd=self.cwd if os.path.isdir(self.cwd) else None,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return CodexThreadResumeOutcome(success=False, message=f"codex resume timeout after {self.timeout}s")
        except OSError as exc:
            return CodexThreadResumeOutcome(success=False, message=f"codex resume failed to start: {exc}")

        output = _compact_output(proc.stdout, proc.stderr)
        if proc.returncode == 0:
            return CodexThreadResumeOutcome(success=True, message=output or "codex resume completed")
        return CodexThreadResumeOutcome(success=False, message=output or f"codex resume exited {proc.returncode}")


def _base_command(command: str) -> list[str]:
    resolved = shutil.which(command) or command
    if not shutil.which(command) and not os.path.exists(resolved):
        return []
    if os.name == "nt" and resolved.lower().endswith(".cmd"):
        base_dir = os.path.dirname(resolved)
        codex_js = os.path.join(base_dir, "node_modules", "@openai", "codex", "bin", "codex.js")
        if os.path.exists(codex_js):
            bundled_node = os.path.join(base_dir, "node.exe")
            node = bundled_node if os.path.exists(bundled_node) else shutil.which("node") or "node"
            return [node, codex_js]
    return [resolved]


def _compact_output(stdout: str, stderr: str, limit: int = 1000) -> str:
    text = "\n".join(part.strip() for part in [stdout, stderr] if part and part.strip())
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
