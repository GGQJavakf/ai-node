from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from _path import SRC  # noqa: F401
from ai_todo_assistant.presentation.cli import TodoCLI


_RETRO_ENTRY = (
    "import sys; "
    "from agent_retro.presentation.cli import main; "
    "raise SystemExit(main(sys.argv[1:]))"
)


class _StrictTextFile:
    def __init__(self, encoding: str = "gbk") -> None:
        self.encoding = encoding
        self.writes: list[str] = []
        self.flush_count = 0

    def write(self, value: str) -> None:
        value.encode(self.encoding, errors="strict")
        self.writes.append(value)

    def flush(self) -> None:
        self.flush_count += 1


class _RenderingConsole:
    def __init__(
        self,
        *,
        rendered_text: str = "",
        render_error: Exception | None = None,
    ) -> None:
        self.file = _StrictTextFile()
        self.rendered_text = rendered_text
        self.render_error = render_error
        self.render_calls = 0
        self.printed: list[object] = []

    def render(self, renderable):
        self.render_calls += 1
        if self.render_error is not None:
            raise self.render_error
        return (SimpleNamespace(text=self.rendered_text),)

    def print(self, value: object) -> None:
        self.printed.append(value)


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
    mapped = _run_retro(
        tmp_path,
        encoding,
        "--json",
        "project",
        "map-workspace",
        "--root",
        str(tmp_path),
        "--vault-project",
        "project-1",
    )
    assert mapped.returncode == 0, (mapped.stdout + mapped.stderr).decode(
        encoding, errors="replace"
    )
    flows = (
        (("--help",), 0, "capture"),
        (("--json", "capture", "--last"), 2, "RETRO_COMMAND_FAILED"),
        (("--json", "review", "list"), 0, "RETRO_REVIEW_LISTED"),
        (("--json", "review", "inbox"), 0, "RETRO_REVIEW_INBOX"),
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


def test_retro_help_does_not_import_todo_or_workitem_application_domain(
    tmp_path: Path,
) -> None:
    probe = (
        "import sys; "
        "from agent_retro.presentation.cli import build_parser; "
        "parser=build_parser(); "
        "\ntry: parser.parse_args(['--help'])\n"
        "except SystemExit as error:\n"
        " assert error.code == 0\n"
        "forbidden=[name for name in sys.modules "
        "if name.startswith('ai_todo_assistant.application')]; "
        "assert not forbidden, forbidden"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=_isolated_environment(tmp_path, "utf-8"),
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode(
        "utf-8", errors="replace"
    )


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


def test_existing_ai_todo_noninteractive_exit_remains_gbk_safe(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ai_todo_assistant.presentation.cli import main; main()",
        ],
        cwd=tmp_path,
        env=_isolated_environment(tmp_path, "gbk"),
        input="/exit\n".encode("gbk"),
        capture_output=True,
        check=False,
        timeout=20,
    )
    combined = completed.stdout + completed.stderr

    assert completed.returncode == 0, combined.decode("gbk", errors="replace")
    assert b"UnicodeEncodeError" not in combined
    combined.decode("gbk", errors="strict")


def test_ai_todo_display_response_uses_one_console_file_encoding_fallback() -> None:
    console = _RenderingConsole(rendered_text="📖 帮助")
    cli = object.__new__(TodoCLI)
    cli.console = console

    assert cli._display_response("📖 帮助") is True

    assert console.render_calls == 1
    assert console.printed == []
    assert console.file.writes == ["? 帮助\n"]
    assert console.file.flush_count == 1


def test_ai_todo_display_response_propagates_non_encoding_render_errors() -> None:
    error = RuntimeError("render failed")
    console = _RenderingConsole(render_error=error)
    cli = object.__new__(TodoCLI)
    cli.console = console

    with pytest.raises(RuntimeError, match="render failed"):
        cli._display_response("plain help")

    assert console.render_calls == 1
    assert console.printed == []
    assert console.file.writes == []
    assert console.file.flush_count == 0
