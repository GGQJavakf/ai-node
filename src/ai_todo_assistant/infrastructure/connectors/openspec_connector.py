"""OpenSpec workflow connector."""
from __future__ import annotations

import json

from ai_todo_assistant.domain.workflow import SourceSnapshot
from ai_todo_assistant.infrastructure.connectors.command_runner import CommandRunner


class OpenSpecConnector:
    def __init__(self, runner: CommandRunner | None = None):
        self.runner = runner or CommandRunner(timeout=45)

    def list_changes(self, project_path: str) -> SourceSnapshot:
        result = self.runner.run(["openspec", "list", "--json"], cwd=project_path)
        return self._json_snapshot("openspec", project_path, result, "openspec list --json")

    def status(self, project_path: str, change: str) -> SourceSnapshot:
        result = self.runner.run(["openspec", "status", "--change", change, "--json"], cwd=project_path)
        return self._json_snapshot("openspec", project_path, result, f"openspec status --change {change} --json")

    def apply_instructions(self, project_path: str, change: str) -> SourceSnapshot:
        result = self.runner.run(["openspec", "instructions", "apply", "--change", change, "--json"], cwd=project_path)
        return self._json_snapshot("openspec", project_path, result, f"openspec instructions apply --change {change} --json")

    def _json_snapshot(self, source: str, project_path: str, result, command: str) -> SourceSnapshot:
        if not result.success:
            return _unavailable(source, project_path, result, command)
        try:
            facts = result.parse_json()
        except json.JSONDecodeError:
            return SourceSnapshot(
                source=source,
                project_path=project_path,
                summary=f"{source} invalid JSON",
                facts={"output_excerpt": result.output_excerpt()},
                command=command,
                success=False,
                error="invalid JSON output",
            )
        summary = _summarize_openspec(facts)
        return SourceSnapshot(
            source=source,
            project_path=project_path,
            summary=summary,
            facts=facts if isinstance(facts, dict) else {"items": facts},
            command=command,
        )


def _summarize_openspec(facts) -> str:
    if isinstance(facts, dict):
        if "changeName" in facts:
            return f"{facts.get('changeName')}: {facts.get('schemaName', 'openspec')}"
        if "changes" in facts and isinstance(facts["changes"], list):
            return f"{len(facts['changes'])} active changes"
    if isinstance(facts, list):
        return f"{len(facts)} OpenSpec entries"
    return "OpenSpec snapshot"


def _unavailable(source: str, project_path: str, result, command: str) -> SourceSnapshot:
    error = "missing command" if result.missing else (result.stderr or result.stdout or "command failed")
    return SourceSnapshot(
        source=source,
        project_path=project_path,
        summary=f"{source} unavailable",
        facts={"output_excerpt": result.output_excerpt()},
        command=command,
        success=False,
        error=error.strip(),
    )
