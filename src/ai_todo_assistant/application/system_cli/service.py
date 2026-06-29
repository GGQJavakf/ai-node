"""Safe system CLI command service."""
from __future__ import annotations

import os
import re
from pathlib import Path

from ai_todo_assistant.application.system_cli.catalog import get_command_spec, list_command_specs
from ai_todo_assistant.application.system_cli.models import (
    POLICY_ALLOWED,
    POLICY_DENIED,
    READ_ONLY,
    CommandExecutionRecord,
    CommandSpec,
)
from ai_todo_assistant.infrastructure.connectors import CommandResult, CommandRunner


class SystemCliService:
    """Runs only cataloged read-only commands and returns compact summaries."""

    def __init__(self, config: dict | None = None, runner=None):
        self.config = config or {}
        self.runner = runner
        self.stdout_limit = int(self.config.get("system_cli_stdout_limit") or 4000)
        self.stderr_limit = int(self.config.get("system_cli_stderr_limit") or 2000)

    def list_commands(self) -> dict[str, CommandSpec]:
        return list_command_specs()

    def allowed_roots(self) -> list[str]:
        configured = self.config.get("system_cli_allowed_roots")
        if isinstance(configured, str) and configured.strip():
            raw_roots = [item.strip() for item in configured.split(os.pathsep) if item.strip()]
        elif isinstance(configured, list):
            raw_roots = [str(item).strip() for item in configured if str(item).strip()]
        else:
            raw_roots = [str(self.config.get("project_root") or os.getcwd())]
        return [os.path.abspath(root) for root in raw_roots]

    def run(self, command_key: str, cwd: str | None = None) -> CommandExecutionRecord:
        spec = get_command_spec(command_key)
        resolved_cwd = self._resolve_cwd(cwd)
        if spec is None:
            return self._denied(command_key, [], resolved_cwd, f"unknown command: {command_key}")
        if spec.risk_level != READ_ONLY:
            return self._denied(command_key, spec.argv, resolved_cwd, f"unsupported risk level: {spec.risk_level}")
        allowed, reason = self._is_cwd_allowed(resolved_cwd)
        if not allowed:
            return self._denied(command_key, spec.argv, resolved_cwd, reason)

        runner = self.runner or CommandRunner(timeout=spec.timeout_seconds)
        result = runner.run(list(spec.argv), cwd=resolved_cwd)
        return self._record_from_result(spec, resolved_cwd, result)

    def format_for_tool(self, record: CommandExecutionRecord) -> str:
        lines = [
            f"[system_cli] {record.command_key} {record.status_text}",
            f"policy: {record.policy_decision}",
            f"cwd: {record.cwd or '-'}",
            f"exit_code: {record.returncode}",
        ]
        if record.policy_reason:
            lines.append(f"reason: {record.policy_reason}")
        if record.timed_out:
            lines.append("timed_out: true")
        if record.missing:
            lines.append("missing: true")
        if record.output_truncated:
            lines.append("output_truncated: true")
        excerpt = record.stdout_excerpt or record.stderr_excerpt
        if excerpt:
            stream_name = "stdout_excerpt" if record.stdout_excerpt else "stderr_excerpt"
            lines.extend([f"{stream_name}:", excerpt])
        return "\n".join(lines)

    def format_command_list(self) -> str:
        lines = ["System CLI commands", "-" * 80]
        for key, spec in sorted(self.list_commands().items()):
            lines.append(f"  {key:<14} {spec.description}")
        return "\n".join(lines)

    def format_policy(self) -> str:
        lines = [
            "System CLI policy",
            "-" * 80,
            "  risk: read_only only",
            "  shell: disabled",
            "  allowed roots:",
        ]
        lines.extend(f"    - {root}" for root in self.allowed_roots())
        return "\n".join(lines)

    def _resolve_cwd(self, cwd: str | None) -> str:
        raw_cwd = cwd or self.config.get("project_root") or os.getcwd()
        return os.path.abspath(str(raw_cwd))

    def _is_cwd_allowed(self, cwd: str) -> tuple[bool, str]:
        if not os.path.isdir(cwd):
            return False, f"cwd does not exist: {cwd}"
        try:
            resolved = Path(cwd).resolve()
        except OSError as exc:
            return False, f"cwd cannot be resolved: {exc}"
        for root in self.allowed_roots():
            try:
                root_path = Path(root).resolve()
            except OSError:
                continue
            if resolved == root_path or root_path in resolved.parents:
                return True, ""
        return False, f"cwd outside allowed roots: {cwd}"

    def _denied(self, command_key: str, argv: list[str], cwd: str, reason: str) -> CommandExecutionRecord:
        return CommandExecutionRecord(
            command_key=command_key,
            argv=argv,
            cwd=cwd,
            returncode=126,
            success=False,
            policy_decision=POLICY_DENIED,
            policy_reason=reason,
        )

    def _record_from_result(self, spec: CommandSpec, cwd: str, result: CommandResult) -> CommandExecutionRecord:
        stdout_excerpt, stdout_truncated = _safe_excerpt(result.stdout, self.stdout_limit or spec.stdout_limit)
        stderr_excerpt, stderr_truncated = _safe_excerpt(result.stderr, self.stderr_limit or spec.stderr_limit)
        return CommandExecutionRecord(
            command_key=spec.key,
            argv=list(spec.argv),
            cwd=cwd,
            returncode=result.returncode,
            success=result.success,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
            timed_out=result.timed_out,
            missing=result.missing,
            output_truncated=stdout_truncated or stderr_truncated,
            risk_level=spec.risk_level,
            policy_decision=POLICY_ALLOWED,
        )


def _safe_excerpt(text: str, limit: int) -> tuple[str, bool]:
    redacted = _redact(text or "")
    if len(redacted) <= limit:
        return redacted.strip("\r\n"), False
    omitted = len(redacted) - limit
    return f"{redacted[:limit].rstrip()}\n...[truncated {omitted} chars]", True


def _redact(text: str) -> str:
    if not text:
        return ""
    rules = [
        (r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]"),
        (r"(?i)\b(password|passwd|pwd|token|secret|api_key)=([^\s&]+)", r"\1=[REDACTED]"),
        (r'(?i)("(?:password|passwd|pwd|token|secret|api_key)"\s*:\s*")[^"]+', r"\1[REDACTED]"),
        (r"(?i)('(?:password|passwd|pwd|token|secret|api_key)'\s*:\s*')[^']+", r"\1[REDACTED]"),
        (r"(?i)(set-cookie:\s*)[^\n]+", r"\1[REDACTED]"),
        (r"(?i)(cookie:\s*)[^\n]+", r"\1[REDACTED]"),
        (
            r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----",
            "[REDACTED_PRIVATE_KEY]",
        ),
    ]
    redacted = text
    for pattern, replacement in rules:
        redacted = re.sub(pattern, replacement, redacted, flags=re.DOTALL)
    return redacted
