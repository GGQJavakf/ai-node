"""Playbook workflow connector."""
from __future__ import annotations

import json

from ai_todo_assistant.domain.workflow import SourceSnapshot
from ai_todo_assistant.infrastructure.connectors.command_runner import CommandRunner


class PlaybookConnector:
    def __init__(self, runner: CommandRunner | None = None):
        self.runner = runner or CommandRunner(timeout=60)

    def redmine_issue(self, project_path: str, issue_id: str) -> SourceSnapshot:
        args = ["playbook", "redmine", "pm", "issue", issue_id, "--output", "json", "--full"]
        result = self.runner.run(args, cwd=project_path)
        return self._json_snapshot(project_path, result, " ".join(args), source_ref=issue_id)

    def workspace_status(self, project_path: str) -> SourceSnapshot:
        args = ["playbook", "workspace", "task", "status", "--output", "json", "--full"]
        result = self.runner.run(args, cwd=project_path)
        return self._json_snapshot(project_path, result, " ".join(args))

    def closeout_gaps(self, project_path: str) -> SourceSnapshot:
        args = ["playbook", "workspace", "task", "closeout", "--dry-run", "--output", "json"]
        result = self.runner.run(args, cwd=project_path)
        return self._json_snapshot(project_path, result, " ".join(args))

    def _json_snapshot(self, project_path: str, result, command: str, source_ref: str = "") -> SourceSnapshot:
        if not result.success:
            return _unavailable(project_path, result, command)
        try:
            facts = result.parse_json()
        except json.JSONDecodeError:
            return SourceSnapshot(
                source="playbook",
                project_path=project_path,
                summary="playbook invalid JSON",
                facts={"output_excerpt": result.output_excerpt(), "source_ref": source_ref},
                command=command,
                success=False,
                error="invalid JSON output",
            )
        summary = _summarize_playbook(facts, source_ref)
        return SourceSnapshot(
            source="playbook",
            project_path=project_path,
            summary=summary,
            facts=facts if isinstance(facts, dict) else {"items": facts, "source_ref": source_ref},
            command=command,
        )


def _summarize_playbook(facts, source_ref: str) -> str:
    if source_ref:
        title = ""
        if isinstance(facts, dict):
            title = str(facts.get("subject") or facts.get("title") or "")
        return f"Redmine {source_ref} {title}".strip()
    if isinstance(facts, dict):
        if "tasks" in facts and isinstance(facts["tasks"], list):
            return f"{len(facts['tasks'])} workspace tasks"
        if "gaps" in facts and isinstance(facts["gaps"], list):
            return f"{len(facts['gaps'])} closeout gaps"
    return "Playbook snapshot"


def _unavailable(project_path: str, result, command: str) -> SourceSnapshot:
    error = "missing command" if result.missing else (result.stderr or result.stdout or "command failed")
    return SourceSnapshot(
        source="playbook",
        project_path=project_path,
        summary="playbook unavailable",
        facts={"output_excerpt": result.output_excerpt()},
        command=command,
        success=False,
        error=error.strip(),
    )
