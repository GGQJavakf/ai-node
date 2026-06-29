"""Read-only system CLI command catalog."""
from __future__ import annotations

from types import MappingProxyType

from ai_todo_assistant.application.system_cli.models import CommandSpec


SYSTEM_CLI_COMMANDS = MappingProxyType({
    "git.branch": CommandSpec(
        key="git.branch",
        title="Git branch",
        description="Show the current Git branch.",
        argv=("git", "branch", "--show-current"),
        timeout_seconds=20,
    ),
    "git.status": CommandSpec(
        key="git.status",
        title="Git status",
        description="Show short Git worktree status.",
        argv=("git", "status", "--short"),
        timeout_seconds=20,
    ),
    "git.diff_stat": CommandSpec(
        key="git.diff_stat",
        title="Git diff stat",
        description="Show a compact diff stat for unstaged changes.",
        argv=("git", "diff", "--stat"),
        timeout_seconds=20,
    ),
})


def list_command_specs() -> dict[str, CommandSpec]:
    return dict(SYSTEM_CLI_COMMANDS)


def get_command_spec(command_key: str) -> CommandSpec | None:
    return SYSTEM_CLI_COMMANDS.get(command_key)
