"""Git workflow connector."""
from __future__ import annotations

from ai_todo_assistant.domain.workflow import SourceSnapshot
from ai_todo_assistant.infrastructure.connectors.command_runner import CommandRunner


class GitConnector:
    def __init__(self, runner: CommandRunner | None = None):
        self.runner = runner or CommandRunner(timeout=20)

    def snapshot(self, project_path: str) -> SourceSnapshot:
        branch = self.runner.run(["git", "branch", "--show-current"], cwd=project_path)
        if not branch.success:
            return _unavailable("git", project_path, branch)
        status = self.runner.run(["git", "status", "--short"], cwd=project_path)
        if not status.success:
            return _unavailable("git", project_path, status)
        diff = self.runner.run(["git", "diff", "--stat"], cwd=project_path)
        facts = {
            "branch": branch.stdout.strip(),
            "dirty": bool(status.stdout.strip()),
            "status_short": status.stdout.splitlines(),
            "diff_stat": diff.stdout.strip() if diff.success else "",
        }
        summary = f"branch={facts['branch'] or '-'}, dirty={facts['dirty']}"
        return SourceSnapshot(
            source="git",
            project_path=project_path,
            summary=summary,
            facts=facts,
            command="git branch --show-current && git status --short && git diff --stat",
        )


def _unavailable(source: str, project_path: str, result) -> SourceSnapshot:
    command = result.command_text
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
