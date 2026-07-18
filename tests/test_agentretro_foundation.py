import json
from dataclasses import FrozenInstanceError, replace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

import _path  # noqa: F401
from agent_retro.domain.models import KnowledgeType
from agent_retro.infrastructure.legacy_model import (
    MODEL_CONFIG_KEYS,
    build_retro_llm_client,
    load_legacy_model_config,
)
from agent_retro.infrastructure.settings import (
    effective_model_timeout,
    load_retro_settings,
)
from agent_retro.presentation.cli import build_parser, main
from agent_retro.presentation.output import safe_text, write_json


def test_settings_use_the_supplied_home(tmp_path):
    settings = load_retro_settings(home=tmp_path, env={})

    assert settings.state_dir == tmp_path / ".agentretro"
    assert settings.db_path == tmp_path / ".agentretro" / "retro.db"
    assert settings.backup_dir == tmp_path / ".agentretro" / "backups"
    assert settings.obsidian_root is None
    assert settings.brief_max_tokens == 6000
    assert settings.discovery_max_files == 1000
    assert settings.discovery_timeout_seconds == 10.0
    assert settings.session_max_bytes == 128 * 1024 * 1024
    assert settings.model_timeout_seconds is None
    assert settings.brief_timeout_seconds == 5.0
    assert settings.thresholds == {
        KnowledgeType.RULE: 0.97,
        KnowledgeType.LESSON: 0.93,
        KnowledgeType.TASK_STATE: 0.90,
    }


def test_settings_are_immutable(tmp_path):
    settings = load_retro_settings(home=tmp_path, env={})

    with pytest.raises(FrozenInstanceError):
        settings.brief_max_tokens = 1


@pytest.mark.parametrize("child_key", ["AGENTRETRO_DB_PATH", "AGENTRETRO_BACKUP_DIR"])
def test_settings_reject_state_children_outside_root(tmp_path, child_key):
    with pytest.raises(ValueError, match=child_key):
        load_retro_settings(
            home=tmp_path,
            env={child_key: str(tmp_path.parent / "outside")},
        )


@pytest.mark.parametrize(
    "limit_key",
    [
        "AGENTRETRO_BRIEF_MAX_TOKENS",
        "AGENTRETRO_DISCOVERY_MAX_FILES",
        "AGENTRETRO_DISCOVERY_TIMEOUT_SECONDS",
        "AGENTRETRO_SESSION_MAX_BYTES",
        "AGENTRETRO_MODEL_TIMEOUT_SECONDS",
        "AGENTRETRO_BRIEF_TIMEOUT_SECONDS",
    ],
)
def test_invalid_limit_is_rejected(tmp_path, limit_key):
    with pytest.raises(ValueError, match=limit_key):
        load_retro_settings(home=tmp_path, env={limit_key: "0"})


def test_settings_honor_environment_overrides(tmp_path):
    state_dir = tmp_path / "state"
    settings = load_retro_settings(
        home=tmp_path,
        env={
            "AGENTRETRO_HOME": str(state_dir),
            "AGENTRETRO_DB_PATH": str(state_dir / "custom.db"),
            "AGENTRETRO_BACKUP_DIR": str(state_dir / "saved"),
            "AGENTRETRO_OBSIDIAN_ROOT": str(tmp_path / "vault"),
            "AGENTRETRO_BRIEF_MAX_TOKENS": "7000",
            "AGENTRETRO_DISCOVERY_MAX_FILES": "12",
            "AGENTRETRO_DISCOVERY_TIMEOUT_SECONDS": "1.5",
            "AGENTRETRO_SESSION_MAX_BYTES": "4096",
            "AGENTRETRO_MODEL_TIMEOUT_SECONDS": "30",
            "AGENTRETRO_BRIEF_TIMEOUT_SECONDS": "2.5",
        },
    )

    assert settings.state_dir == state_dir
    assert settings.db_path == state_dir / "custom.db"
    assert settings.backup_dir == state_dir / "saved"
    assert settings.obsidian_root == tmp_path / "vault"
    assert settings.brief_max_tokens == 7000
    assert settings.discovery_max_files == 12
    assert settings.discovery_timeout_seconds == 1.5
    assert settings.session_max_bytes == 4096
    assert settings.model_timeout_seconds == 30
    assert settings.brief_timeout_seconds == 2.5


@pytest.mark.parametrize(
    ("override", "legacy", "expected"),
    [
        (45, {"request_timeout": 60, "codex_request_timeout": 90}, 45),
        (None, {"request_timeout": 60, "codex_request_timeout": 90}, 60),
        (None, {"request_timeout": None, "codex_request_timeout": 90}, 90),
        (None, {}, 120),
    ],
)
def test_effective_model_timeout_uses_documented_precedence(
    tmp_path, override, legacy, expected
):
    env = (
        {"AGENTRETRO_MODEL_TIMEOUT_SECONDS": str(override)}
        if override is not None
        else {}
    )
    settings = load_retro_settings(home=tmp_path, env=env)

    assert effective_model_timeout(settings, legacy) == expected


@pytest.mark.parametrize(
    "invalid_value",
    [True, "not-a-number", float("nan"), float("inf"), 12.5, 0, -1, ""],
)
def test_effective_model_timeout_rejects_invalid_high_priority_legacy_value(
    tmp_path, invalid_value
):
    settings = load_retro_settings(home=tmp_path, env={})

    with pytest.raises(ValueError, match="request_timeout"):
        effective_model_timeout(
            settings,
            {
                "request_timeout": invalid_value,
                "codex_request_timeout": 90,
            },
        )


@pytest.mark.parametrize(
    "invalid_value",
    [False, "not-a-number", float("nan"), float("-inf"), 7.5, 0, -30, ""],
)
def test_effective_model_timeout_rejects_invalid_codex_legacy_value(
    tmp_path, invalid_value
):
    settings = load_retro_settings(home=tmp_path, env={})

    with pytest.raises(ValueError, match="codex_request_timeout"):
        effective_model_timeout(
            settings,
            {
                "request_timeout": None,
                "codex_request_timeout": invalid_value,
            },
        )


@pytest.mark.parametrize("invalid_value", [True, float("nan"), 3.5, 0, -1])
def test_effective_model_timeout_rejects_invalid_agentretro_override(
    tmp_path, invalid_value
):
    settings = replace(
        load_retro_settings(home=tmp_path, env={}),
        model_timeout_seconds=invalid_value,
    )

    with pytest.raises(ValueError, match="AGENTRETRO_MODEL_TIMEOUT_SECONDS"):
        effective_model_timeout(
            settings,
            {"request_timeout": 60, "codex_request_timeout": 90},
        )


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ({"request_timeout": "60", "codex_request_timeout": 90}, 60),
        ({"request_timeout": 60.0, "codex_request_timeout": 90}, 60),
        ({"request_timeout": None, "codex_request_timeout": "90"}, 90),
        ({"request_timeout": None, "codex_request_timeout": 90.0}, 90),
    ],
)
def test_effective_model_timeout_accepts_positive_integer_values(
    tmp_path, legacy, expected
):
    settings = load_retro_settings(home=tmp_path, env={})

    assert effective_model_timeout(settings, legacy) == expected


@patch("agent_retro.infrastructure.legacy_model.load_settings")
def test_legacy_model_adapter_filters_unrelated_settings(load_settings):
    load_settings.return_value = {
        "auth_mode": "openai_api",
        "api_key": "secret-for-test",
        "api_base": "https://example.invalid/v1",
        "model": "test-model",
        "sqlite_path": "data/todos.db",
    }

    filtered = load_legacy_model_config()

    assert "sqlite_path" not in filtered
    assert set(filtered) == set(MODEL_CONFIG_KEYS)
    assert set(filtered) == {
        "auth_mode",
        "api_key",
        "api_base",
        "model",
        "request_timeout",
        "api_retry_limit",
        "api_retry_backoff",
        "codex_command",
        "codex_timeout",
        "codex_request_timeout",
        "codex_use_app_server",
        "codex_app_server_timeout",
        "codex_app_server_start_timeout",
        "codex_app_server_fallback_to_exec",
        "codex_retry_limit",
        "codex_ignore_user_config",
        "codex_ignore_rules",
    }


@patch("agent_retro.infrastructure.legacy_model.build_llm_client")
@patch("agent_retro.infrastructure.legacy_model.load_settings")
def test_legacy_model_client_receives_only_a_fresh_allowlisted_dictionary(
    load_settings, build_llm_client
):
    source = {key: f"value-{key}" for key in MODEL_CONFIG_KEYS}
    source["sqlite_path"] = "data/todos.db"
    load_settings.return_value = source
    sentinel = object()
    build_llm_client.return_value = sentinel

    result = build_retro_llm_client("project-root")

    passed_config = build_llm_client.call_args.args[0]
    assert result is sentinel
    assert passed_config is not source
    assert set(passed_config) == set(MODEL_CONFIG_KEYS)
    assert "sqlite_path" not in passed_config
    load_settings.assert_called_once_with("project-root")


def test_parser_has_independent_program_name():
    parser = build_parser()

    assert parser.prog == "retro"
    assert parser.description == "Codex 会话复盘与知识沉淀"


def test_main_emits_stable_chinese_human_output(capsys):
    assert main([]) == 0

    assert capsys.readouterr().out == "AgentRetro 已就绪。\n"


def test_main_json_emits_stable_english_envelope_without_ansi(capsys):
    assert main(["--json"]) == 0

    raw_output = capsys.readouterr().out
    assert "\x1b[" not in raw_output
    assert json.loads(raw_output) == {
        "code": "RETRO_READY",
        "data": {},
        "message": "AgentRetro is ready.",
        "status": "ok",
    }


def test_legacy_and_retro_entry_points_are_independently_callable():
    from ai_todo_assistant.presentation.cli import main as legacy_main
    from agent_retro.presentation.cli import main as retro_main

    assert callable(legacy_main)
    assert callable(retro_main)
    assert legacy_main is not retro_main
    assert legacy_main.__module__ == "ai_todo_assistant.presentation.cli"
    assert retro_main.__module__ == "agent_retro.presentation.cli"

    with patch("ai_todo_assistant.presentation.cli.TodoCLI") as todo_cli:
        legacy_main()

    todo_cli.assert_called_once_with()
    todo_cli.return_value.run.assert_called_once_with()


def test_output_is_unicode_safe_and_json_remains_machine_readable():
    assert safe_text("Codex 会话复盘", "utf-8") == "Codex 会话复盘"
    assert "?" in safe_text("会话", "ascii")
    stream = StringIO()

    write_json({"status": "ok", "message": "会话完成"}, stream=stream)

    assert "会话完成" in stream.getvalue()
    assert json.loads(stream.getvalue()) == {"status": "ok", "message": "会话完成"}


def test_project_scripts_preserve_ai_todo_and_add_retro():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert 'ai-todo = "ai_todo_assistant.presentation.cli:main"' in pyproject
    assert 'retro = "agent_retro.presentation.cli:main"' in pyproject
