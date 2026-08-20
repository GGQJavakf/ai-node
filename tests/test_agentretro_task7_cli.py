from __future__ import annotations

import json
from pathlib import Path

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.brief import BriefTimeoutError
from agent_retro.domain.models import BriefHealthCounts, ProjectMapping
from agent_retro.presentation import cli as retro_cli


class _EmptyBriefRepository:
    def list_project_mappings(self):
        return [
            ProjectMapping(
                "mapping-project-1",
                Path.cwd(),
                "",
                "project-1",
                mapping_kind="workspace",
            )
        ]

    def expire_task_states(self, at):
        return []

    def list_brief_knowledge(self, project_id, at):
        return []

    def brief_health_counts(self, project_id, at):
        return BriefHealthCounts(0, 0, 0, 0, 0)

    def list_open_conflicts(self, project_id):
        return []

    def list_projection_events(self, project_id):
        return []

    def has_rollback_required_sync(self):
        return False

    def has_purge_incomplete(self):
        return False


def _json(capsys):
    return json.loads(capsys.readouterr().out)


def _env(tmp_path):
    codex_home = tmp_path / "codex"
    codex_home.mkdir(exist_ok=True)
    return {
        "AGENTRETRO_HOME": str(tmp_path / "state"),
        "CODEX_HOME": str(codex_home),
    }


def test_task7_parser_exposes_brief_doctor_and_mutually_exclusive_integration():
    parser = retro_cli.build_parser()

    brief = parser.parse_args(["brief", "fix parser", "--project", "project-1"])
    assert (brief.command, brief.task, brief.project_id) == (
        "brief",
        "fix parser",
        "project-1",
    )
    assert parser.parse_args(["doctor"]).command == "doctor"
    preview = parser.parse_args(["integrate", "codex"])
    assert not preview.integrate_apply and not preview.integrate_remove
    assert parser.parse_args(["integrate", "codex", "--apply"]).integrate_apply
    assert parser.parse_args(["integrate", "codex", "--remove"]).integrate_remove
    with pytest.raises(SystemExit):
        parser.parse_args(["integrate", "codex", "--apply", "--remove"])


def test_cli_brief_uses_sqlite_service_and_emits_stable_path_free_json(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(
        retro_cli, "build_retro_repository", lambda settings: _EmptyBriefRepository()
    )
    monkeypatch.setattr(
        retro_cli,
        "load_legacy_model_config",
        lambda: pytest.fail("brief must not load model configuration"),
    )

    assert (
        retro_cli.main(
            ["--json", "brief", "fix parser", "--project", "project-1"],
            home=tmp_path,
            env=_env(tmp_path),
        )
        == 0
    )
    payload = _json(capsys)
    assert payload["code"] == "RETRO_BRIEF_READY"
    assert payload["data"]["task"] == "fix parser"
    assert payload["data"]["items"] == []
    serialized = json.dumps(payload)
    assert str(tmp_path) not in serialized
    assert "\x1b" not in serialized


def test_cli_brief_unknown_and_ambiguous_references_fail_before_knowledge_read(
    tmp_path, capsys, monkeypatch
):
    root = (tmp_path / "workspace").resolve()
    root.mkdir()

    class MappingOnlyRepository:
        def __init__(self, mappings):
            self.mappings = mappings

        def list_project_mappings(self):
            return self.mappings

    monkeypatch.setattr(
        retro_cli,
        "BriefService",
        lambda *args, **kwargs: pytest.fail("unresolved project must not read knowledge"),
    )
    repository = MappingOnlyRepository([])
    monkeypatch.setattr(retro_cli, "build_retro_repository", lambda settings: repository)

    assert (
        retro_cli.main(
            ["--json", "brief", "safe", "--project", "missing"],
            home=tmp_path,
            env=_env(tmp_path),
        )
        == 2
    )
    unknown = _json(capsys)
    assert unknown["code"] == "RETRO_UNKNOWN_PROJECT_REFERENCE"
    assert unknown["data"] == {
        "mapping_ids": [],
        "reason": "unknown_project_reference",
        "recovery_command": "retro project list",
    }

    repository.mappings = [
        ProjectMapping("mapping-a", root, "", "A", mapping_kind="workspace"),
        ProjectMapping("mapping-b", root, "", "B", mapping_kind="workspace"),
    ]
    assert (
        retro_cli.main(
            ["brief", "safe", "--project", str(root)],
            home=tmp_path,
            env=_env(tmp_path),
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    ambiguous = json.loads(captured.err)
    assert ambiguous == {
        "mapping_ids": ["mapping-a", "mapping-b"],
        "reason": "multiple_mapping_matches",
        "recovery_command": "retro project list",
    }
    assert str(root) not in captured.err


def test_cli_doctor_json_keeps_fixed_order_and_redacts_absolute_paths(
    tmp_path, capsys, monkeypatch
):
    payload_env = _env(tmp_path)
    monkeypatch.setattr(retro_cli, "load_legacy_model_config", lambda: {})

    assert retro_cli.main(["--json", "doctor"], home=tmp_path, env=payload_env) == 2
    payload = _json(capsys)
    assert payload["code"] == "RETRO_DOCTOR_ISSUES"
    assert [item["name"] for item in payload["data"]["checks"]] == [
        "codex_source",
        "safety_limits",
        "database",
        "migration",
        "model",
        "obsidian_root",
        "project_mapping",
        "backup_path",
        "sync_recovery",
        "purge_recovery",
        "codex_integration",
        "codex_override",
        "console_encoding",
    ]
    assert str(tmp_path) not in json.dumps(payload)


def test_cli_integration_defaults_to_zero_write_preview_then_applies_and_removes_tmp_target(
    tmp_path, capsys
):
    env = _env(tmp_path)
    target = tmp_path / "codex" / "AGENTS.md"
    state = tmp_path / "state"

    assert retro_cli.main(["--json", "integrate", "codex"], home=tmp_path, env=env) == 0
    preview = _json(capsys)
    assert preview["code"] == "RETRO_CODEX_INTEGRATION_PREVIEW"
    assert preview["data"]["target"] == "${CODEX_HOME}/AGENTS.md"
    assert preview["data"]["backup_location"].startswith("${AGENTRETRO_BACKUP_DIR}/")
    assert preview["data"]["target_missing"] is True
    assert not target.exists()
    assert not state.exists()
    assert str(tmp_path) not in json.dumps(preview)

    assert (
        retro_cli.main(
            ["--json", "integrate", "codex", "--apply"],
            home=tmp_path,
            env=env,
        )
        == 0
    )
    applied = _json(capsys)
    assert applied["code"] == "RETRO_CODEX_INTEGRATION_APPLIED"
    assert applied["data"]["discoverable"] is True
    assert target.is_file()

    assert (
        retro_cli.main(
            ["--json", "integrate", "codex", "--remove"],
            home=tmp_path,
            env=env,
        )
        == 0
    )
    removed = _json(capsys)
    assert removed["code"] == "RETRO_CODEX_INTEGRATION_REMOVED"
    assert not target.exists()


def test_cli_discoverability_exception_restores_absence_and_returns_typed_error(
    tmp_path, capsys, monkeypatch
):
    env = _env(tmp_path)
    target = tmp_path / "codex" / "AGENTS.md"
    guidance_type = retro_cli.CodexGuidance

    def guidance_with_failed_discovery(codex_home, backup_root):
        return guidance_type(
            codex_home,
            backup_root,
            discoverer=lambda home: (_ for _ in ()).throw(
                RuntimeError("secret discovery failure")
            ),
        )

    monkeypatch.setattr(retro_cli, "CodexGuidance", guidance_with_failed_discovery)

    assert (
        retro_cli.main(
            ["--json", "integrate", "codex", "--apply"],
            home=tmp_path,
            env=env,
        )
        == 2
    )
    payload = _json(capsys)
    assert payload["code"] == "RETRO_CODEX_INTEGRATION_FAILED"
    assert payload["data"] == {"reason": "discoverability_failed"}
    assert "secret discovery failure" not in json.dumps(payload)
    assert not target.exists()


def test_cli_brief_deadline_and_codex_override_have_typed_errors(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(
        retro_cli,
        "_run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(BriefTimeoutError()),
    )
    assert retro_cli.main(["--json", "doctor"], home=tmp_path, env=_env(tmp_path)) == 2
    assert _json(capsys)["code"] == "RETRO_BRIEF_DEADLINE_EXCEEDED"
    monkeypatch.undo()

    env = _env(tmp_path)
    (tmp_path / "codex" / "AGENTS.override.md").write_text("shadow", encoding="utf-8")
    assert (
        retro_cli.main(
            ["--json", "integrate", "codex", "--apply"],
            home=tmp_path,
            env=env,
        )
        == 2
    )
    error = _json(capsys)
    assert error["code"] == "RETRO_CODEX_INTEGRATION_FAILED"
    assert error["data"]["reason"] == "codex_override_present"
    assert str(tmp_path) not in json.dumps(error)

    preview = retro_cli.main(["--json", "integrate", "codex"], home=tmp_path, env=env)
    assert preview == 0
    assert _json(capsys)["data"]["override_conflict"] is True
