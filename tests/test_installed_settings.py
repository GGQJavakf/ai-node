import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wheel_install_reads_explicit_settings_without_cwd_fallback(tmp_path):
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            str(ROOT),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheelhouse.glob("ai_todo_assistant-*.whl"))
    install_root = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_root),
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    packaged_template = (
        install_root / "share" / "ai-todo-assistant" / "settings.example.json"
    )
    assert packaged_template.is_file()
    assert json.loads(packaged_template.read_text(encoding="utf-8"))["api_key"] == (
        "REPLACE_WITH_YOUR_API_KEY"
    )

    runtime_config = tmp_path / "runtime" / "settings.json"
    runtime_config.parent.mkdir()
    runtime_config.write_text(
        json.dumps({"model": "installed-model", "api_key": "test-only-key"}),
        encoding="utf-8",
    )
    unrelated_cwd = tmp_path / "unrelated"
    poison_config = unrelated_cwd / "config" / "settings.local.json"
    poison_config.parent.mkdir(parents=True)
    poison_config.write_text(
        json.dumps({"model": "cwd-poison"}),
        encoding="utf-8",
    )

    code = (
        "import json,sys; "
        f"sys.path.insert(0, {str(install_root)!r}); "
        "from agent_retro.infrastructure.legacy_model import load_legacy_model_config; "
        "print(json.dumps(load_legacy_model_config(), sort_keys=True))"
    )
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AI_") and not key.startswith("TODO_")
    }
    explicit_env = {**clean_env, "AI_SETTINGS_FILE": str(runtime_config)}
    explicit = subprocess.run(
        [sys.executable, "-c", code],
        cwd=unrelated_cwd,
        env=explicit_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(explicit.stdout)["model"] == "installed-model"

    defaults = subprocess.run(
        [sys.executable, "-c", code],
        cwd=unrelated_cwd,
        env=clean_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(defaults.stdout)["model"] == "gpt-3.5-turbo"

    runtime_config.write_text('{"model":', encoding="utf-8")
    doctor_home = tmp_path / "doctor-home"
    doctor_codex = tmp_path / "doctor-codex"
    (doctor_codex / "sessions").mkdir(parents=True)
    doctor_code = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(install_root)!r}); "
        "from agent_retro.presentation.cli import main; "
        f"raise SystemExit(main(['--json', 'doctor'], home=Path({str(tmp_path)!r}), "
        f"env={{'AGENTRETRO_HOME': {str(doctor_home)!r}, "
        f"'CODEX_HOME': {str(doctor_codex)!r}}}))"
    )
    doctor = subprocess.run(
        [sys.executable, "-c", doctor_code],
        cwd=unrelated_cwd,
        env=explicit_env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert doctor.returncode == 2
    assert doctor.stderr == ""
    assert len(doctor.stdout.splitlines()) == 1
    payload = json.loads(doctor.stdout)
    assert payload["code"] == "RETRO_DOCTOR_ISSUES"
    model_check = next(
        check for check in payload["data"]["checks"] if check["name"] == "model"
    )
    assert model_check == {
        "name": "model",
        "recovery": "repair the selected ai-todo settings file",
        "status": "error",
        "summary": "configuration_error",
    }
