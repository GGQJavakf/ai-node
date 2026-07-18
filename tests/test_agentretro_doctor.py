from __future__ import annotations

import json
from pathlib import Path

from _path import ROOT  # noqa: F401
from agent_retro.application.doctor import CHECK_ORDER, DoctorService
from agent_retro.domain.models import ProjectMapping, SyncJob
from agent_retro.infrastructure.settings import load_retro_settings
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


class _Repository:
    def __init__(
        self,
        *,
        schema_version: int = 2,
        mappings: tuple[ProjectMapping, ...] = (),
        rollback_jobs: tuple[SyncJob, ...] = (),
        purge_incomplete: bool = False,
    ) -> None:
        self._schema_version = schema_version
        self._mappings = mappings
        self._rollback_jobs = rollback_jobs
        self._purge_incomplete = purge_incomplete

    def schema_version(self) -> int:
        return self._schema_version

    def list_project_mappings(self, active_only: bool = True):
        return list(self._mappings)

    def rollback_required_sync_jobs(self):
        return list(self._rollback_jobs)

    def has_rollback_required_sync(self) -> bool:
        return bool(self._rollback_jobs)

    def has_purge_incomplete(self) -> bool:
        return self._purge_incomplete


def _settings(tmp_path: Path, vault: Path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "retro.db").write_bytes(b"test-db-present")
    (state / "backups").mkdir()
    return load_retro_settings(
        home=tmp_path,
        env={
            "AGENTRETRO_HOME": str(state),
            "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
        },
    )


def test_doctor_returns_exact_order_redacted_model_state_and_one_recovery_per_check(
    tmp_path,
):
    codex_home = tmp_path / "codex-private-location"
    (codex_home / "sessions").mkdir(parents=True)
    vault = tmp_path / "vault-private-location"
    vault.mkdir()
    settings = _settings(tmp_path, vault)
    mapping = ProjectMapping(
        id="mapping-1",
        git_root=tmp_path / "private-project-root",
        remote_identity="example.invalid/team/repo",
        obsidian_project="project-1",
    )

    report = DoctorService(
        settings,
        _Repository(mappings=(mapping,)),
        codex_home=codex_home,
        model_config_loader=lambda: {
            "model": "test-model",
            "api_key": "doctor-secret-must-not-leak",
        },
        console_encoding=lambda: "utf-8",
    ).run()

    assert tuple(check.name for check in report.checks) == CHECK_ORDER
    assert len(report.checks) == 13
    assert all(
        check.status in {"healthy", "warning", "error"} for check in report.checks
    )
    assert all(check.recovery for check in report.checks)
    model = report.by_name("model")
    assert model.status == "healthy"
    assert model.summary == "configured"
    serialized = json.dumps(report.as_dict(), ensure_ascii=False)
    assert "doctor-secret-must-not-leak" not in serialized
    assert str(tmp_path) not in serialized
    assert "test-model" not in serialized


def test_doctor_surfaces_rollback_purge_override_and_missing_model_without_paths(
    tmp_path,
):
    codex_home = tmp_path / "codex-private-location"
    (codex_home / "sessions").mkdir(parents=True)
    (codex_home / "AGENTS.override.md").write_text("shadow", encoding="utf-8")
    vault = tmp_path / "vault-private-location"
    vault.mkdir()
    settings = _settings(tmp_path, vault)
    rollback = SyncJob(
        id="sync-run-safe-id",
        project_id="project-1",
        status="rollback_required",
        plan_json="{}",
        backup_path=tmp_path / "secret-backup-path",
        error="do-not-leak-error-detail",
    )

    report = DoctorService(
        settings,
        _Repository(rollback_jobs=(rollback,), purge_incomplete=True),
        codex_home=codex_home,
        model_config_loader=lambda: {"model": "", "api_key": "hidden"},
        console_encoding=lambda: "cp936",
    ).run()

    assert report.by_name("model").summary == "missing"
    assert report.by_name("sync_recovery").status == "error"
    assert "rollback_required" in report.by_name("sync_recovery").summary
    assert "sync-run-safe-id" in report.by_name("sync_recovery").recovery
    assert report.by_name("purge_recovery").status == "error"
    assert report.by_name("purge_recovery").summary == "purge_incomplete"
    assert report.by_name("codex_override").status == "error"
    assert report.exit_code == 2
    serialized = json.dumps(report.as_dict(), ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "secret-backup-path" not in serialized
    assert "do-not-leak-error-detail" not in serialized


def test_repository_lists_only_rollback_required_jobs_for_doctor(tmp_path):
    repository = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
    for job_id, status in (
        ("sync-running", "running"),
        ("sync-rollback", "rollback_required"),
    ):
        repository.begin_sync(
            SyncJob(
                id=job_id,
                project_id="project-1",
                status="running",
                plan_json="{}",
                backup_path=tmp_path / "backups" / job_id,
            )
        )
        repository.finish_sync(job_id, status)

    assert [job.id for job in repository.rollback_required_sync_jobs()] == [
        "sync-rollback"
    ]


def test_doctor_keeps_legacy_boolean_rollback_signal_blocking_and_warns_on_ascii(
    tmp_path,
):
    codex_home = tmp_path / "codex"
    (codex_home / "sessions").mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    settings = _settings(tmp_path, vault)
    repository = _Repository(
        rollback_jobs=(
            SyncJob(
                id="safe-run",
                project_id="project-1",
                status="rollback_required",
                plan_json="{}",
                backup_path=tmp_path / "private-backup",
            ),
        )
    )
    repository.rollback_required_sync_jobs = None

    report = DoctorService(
        settings,
        repository,
        codex_home=codex_home,
        model_config_loader=lambda: {},
        console_encoding=lambda: "ascii",
    ).run()

    assert report.by_name("sync_recovery").status == "error"
    assert report.by_name("sync_recovery").summary == "rollback_required"
    assert report.by_name("console_encoding").status == "warning"
