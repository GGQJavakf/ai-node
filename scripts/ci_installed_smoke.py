"""Build-artifact smoke tests that never import from the source checkout."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


_SENSITIVE_PREFIXES = (
    "AGENTRETRO_",
    "AI_",
    "ANTHROPIC_",
    "CODEX_",
    "OPENAI_",
    "TODO_",
)
_REMOVED_ENVIRONMENT = {
    "PYTHONHOME",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "WORKFLOW_DATA_FILE",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install one wheel into a clean venv and smoke its console scripts."
    )
    parser.add_argument("artifact", type=Path)
    return parser.parse_args()


def _resolve_wheel(artifact: Path) -> Path:
    candidate = artifact.resolve(strict=True)
    if candidate.is_dir():
        wheels = sorted(candidate.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("expected exactly one wheel in the artifact directory")
        candidate = wheels[0]
    if candidate.suffix != ".whl" or not candidate.is_file():
        raise ValueError("expected one existing .whl file or artifact directory")
    return candidate


def _venv_executable(venv_root: Path, name: str) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / f"{name}.exe"
    return venv_root / "bin" / name


def _isolated_environment(root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _REMOVED_ENVIRONMENT
        and not key.upper().startswith(_SENSITIVE_PREFIXES)
    }
    home = root / "home"
    state = root / "state"
    codex_home = root / "codex-home"
    home.mkdir()
    state.mkdir()
    (codex_home / "sessions").mkdir(parents=True)
    environment.update(
        {
            "AGENTRETRO_BACKUP_DIR": str(state / "backups"),
            "AGENTRETRO_DB_PATH": str(state / "retro.db"),
            "AGENTRETRO_HOME": str(state),
            "AGENTRETRO_OBSIDIAN_ROOT": str(root / "vault"),
            "AI_CODEX_HOME": str(codex_home),
            "AI_CODEX_RESUME_ENABLED": "false",
            "AI_CODEX_RESUME_EXCLUSIONS_FILE": str(
                state / "codex-resume-exclusions.json"
            ),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "CODEX_HOME": str(codex_home),
            "HOME": str(home),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "NO_COLOR": "1",
            "PROMPT_TOOLKIT_NO_CPR": "1",
            "PYTHONIOENCODING": "utf-8:strict",
            "PYTHONUTF8": "1",
            "TERM": "dumb",
            "TODO_AUTO_MIGRATE_JSON": "false",
            "TODO_SQLITE_PATH": str(state / "todos.db"),
            "TODO_STORAGE_BACKEND": "sqlite",
            "USERPROFILE": str(home),
            "WORKFLOW_DATA_FILE": str(state / "workflow.json"),
            "XDG_CONFIG_HOME": str(home / ".config"),
        }
    )
    return environment


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    input_text: str | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with exit {completed.returncode}: {command[0]}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if "UnicodeEncodeError" in completed.stdout + completed.stderr:
        raise RuntimeError(f"console encoding failed: {command[0]}")
    return completed


def main() -> int:
    wheel = _resolve_wheel(_parse_args().artifact)

    with tempfile.TemporaryDirectory(prefix="ai-node-installed-smoke-") as temporary:
        root = Path(temporary)
        venv_root = root / "venv"
        work = root / "unrelated-cwd"
        work.mkdir()
        environment = _isolated_environment(root)

        venv.EnvBuilder(with_pip=True, clear=True).create(venv_root)
        python = _venv_executable(venv_root, "python")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel),
            ],
            cwd=work,
            env=environment,
            timeout=180,
        )

        template = (
            venv_root
            / "share"
            / "ai-todo-assistant"
            / "settings.example.json"
        )
        template_payload = json.loads(template.read_text(encoding="utf-8"))
        if template_payload.get("api_key") != "REPLACE_WITH_YOUR_API_KEY":
            raise RuntimeError("installed settings template is missing or not sanitized")

        retro = _venv_executable(venv_root, "retro")
        retro_help = _run([str(retro), "--help"], cwd=work, env=environment)
        if "capture" not in retro_help.stdout or "doctor" not in retro_help.stdout:
            raise RuntimeError("installed retro help is incomplete")

        project_list = _run(
            [str(retro), "--json", "project", "list"],
            cwd=work,
            env=environment,
        )
        project_payload = json.loads(project_list.stdout)
        if project_payload.get("code") != "RETRO_PROJECT_UPDATED":
            raise RuntimeError("installed retro JSON command returned an unexpected result")

        ai_todo = _venv_executable(venv_root, "ai-todo")
        todo_exit = _run(
            [str(ai_todo)],
            cwd=work,
            env=environment,
            input_text="/exit\n",
        )
        if "Goodbye" not in todo_exit.stdout:
            raise RuntimeError("installed ai-todo did not complete its exit flow")

    print("installed wheel smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
