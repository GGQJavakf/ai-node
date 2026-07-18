from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from _path import SRC  # noqa: F401


_RETRO_ENTRY = (
    "import sys; "
    "from agent_retro.presentation.cli import main; "
    "raise SystemExit(main(sys.argv[1:]))"
)


def _isolated_environment(tmp_path: Path, encoding: str) -> dict[str, str]:
    state = tmp_path / "state"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "AGENTRETRO_HOME": str(state),
            "AGENTRETRO_DB_PATH": str(state / "retro.db"),
            "AGENTRETRO_BACKUP_DIR": str(state / "backups"),
            "AGENTRETRO_OBSIDIAN_ROOT": str(tmp_path / "vault"),
            "CODEX_HOME": str(codex_home),
            "HOME": str(tmp_path / "home"),
            "USERPROFILE": str(tmp_path / "home"),
            "PYTHONIOENCODING": f"{encoding}:strict",
            "PYTHONPATH": str(SRC),
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    return environment


def _run_retro(
    tmp_path: Path, encoding: str, *arguments: str
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-c", _RETRO_ENTRY, *arguments],
        cwd=tmp_path,
        env=_isolated_environment(tmp_path, encoding),
        capture_output=True,
        check=False,
        timeout=20,
    )


@pytest.mark.parametrize("encoding", ["gbk", "utf-8"])
def test_retro_subprocess_smoke_has_defined_exits_and_strict_console_output(
    tmp_path: Path, encoding: str
) -> None:
    flows = (
        (("--help",), 0, "capture"),
        (("--json", "capture", "--last"), 2, "RETRO_COMMAND_FAILED"),
        (("--json", "review", "list"), 0, "RETRO_REVIEW_LISTED"),
        (
            ("--json", "brief", "empty task", "--project", "project-1"),
            0,
            "RETRO_BRIEF_READY",
        ),
    )

    for arguments, expected_exit, expected_marker in flows:
        completed = _run_retro(tmp_path, encoding, *arguments)
        combined = completed.stdout + completed.stderr
        decoded = combined.decode(encoding, errors="strict")

        assert completed.returncode == expected_exit, decoded
        assert b"UnicodeEncodeError" not in combined
        assert expected_marker in decoded


def test_existing_ai_todo_noninteractive_help_remains_gbk_safe(
    tmp_path: Path,
) -> None:
    environment = _isolated_environment(tmp_path, "gbk")
    command = (
        "from rich.console import Console; "
        "from ai_todo_assistant.presentation.cli import TodoCLI; "
        "cli=object.__new__(TodoCLI); cli.console=Console(); "
        "response=cli._handle_slash_command('/help'); "
        "raise SystemExit(0 if cli._display_response(response) else 3)"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        timeout=20,
    )
    combined = completed.stdout + completed.stderr

    assert completed.returncode == 0, combined.decode("gbk", errors="replace")
    assert b"UnicodeEncodeError" not in combined
    combined.decode("gbk", errors="strict")
    assert "日常主命令".encode("gbk") in combined
