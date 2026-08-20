from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.obsidian_init import (
    BoundaryInitError,
    BoundaryInitStalePlan,
    ManagedBoundaryInitializer,
)
from agent_retro.domain.models import ProjectMapping, ProjectionStatus
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation import cli as retro_cli


def _snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _repository(
    tmp_path: Path, obsidian_project: str = "NPKI"
) -> SQLiteRetroRepository:
    state = tmp_path / "state"
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping(
            id=f"mapping-{obsidian_project.replace('/', '-')}",
            git_root=tmp_path / "repo",
            remote_identity="example.invalid/npki",
            obsidian_project=obsidian_project,
        ),
        actor="user",
    )
    return repository


def _targets(
    tmp_path: Path, project_id: str = "NPKI"
) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    project_path = Path(project_id)
    summary = vault / "项目" / project_path / f"项目_{project_path.name}.md"
    index = vault / "项目" / "项目索引.md"
    summary.parent.mkdir(parents=True)
    index.parent.mkdir(parents=True, exist_ok=True)
    return vault, summary, index


def _initializer(
    tmp_path: Path,
    *,
    repository: SQLiteRetroRepository | None = None,
    replace=os.replace,
) -> ManagedBoundaryInitializer:
    return ManagedBoundaryInitializer(
        repository or _repository(tmp_path),
        tmp_path / "vault",
        tmp_path / "state" / "backups",
        replace=replace,
    )


def test_os_25_preview_is_deterministic_complete_and_zero_write(tmp_path: Path) -> None:
    vault, summary, index = _targets(tmp_path)
    summary.write_bytes("# 项目\r\n\r\n人工摘要\r\n".encode())
    index.write_bytes("# 项目索引\n\n- [[项目/OTHER]]\n".encode())
    repository = _repository(tmp_path)
    before_vault = _snapshot(vault)
    before_backups = _snapshot(tmp_path / "state" / "backups")

    first = _initializer(tmp_path, repository=repository).preview("NPKI")
    second = _initializer(tmp_path, repository=repository).preview("NPKI")

    assert first == second
    assert first.id.startswith("obsidian-init-")
    assert [target.relative_path.as_posix() for target in first.targets] == [
        "项目/NPKI/项目_NPKI.md",
        "项目/项目索引.md",
    ]
    assert all(len(target.before_hash) == 64 for target in first.targets)
    assert all(len(target.after_hash) == 64 for target in first.targets)
    assert all(target.changed for target in first.targets)
    assert all(target.diff.startswith("--- ") for target in first.targets)
    assert all(str(first.id) in str(target.backup_path) for target in first.targets)
    assert _snapshot(vault) == before_vault
    assert _snapshot(tmp_path / "state" / "backups") == before_backups
    assert repository.get_sync_job(first.id) is None


def test_os_26_matching_apply_preserves_prose_and_missing_page_stays_missing(
    tmp_path: Path,
) -> None:
    vault, summary, index = _targets(tmp_path)
    original_summary = "# 项目\r\n\r\n人工摘要\r\n".encode()
    original_index = "# 项目索引\n\n- [[项目/OTHER]]\n".encode()
    summary.write_bytes(original_summary)
    index.write_bytes(original_index)
    repository = _repository(tmp_path)
    initializer = _initializer(tmp_path, repository=repository)
    plan = initializer.preview("NPKI")

    result = initializer.apply("NPKI", plan.id)

    assert result.status is ProjectionStatus.SYNCED
    assert result.changed is True
    assert summary.read_bytes().startswith(original_summary)
    assert index.read_bytes().startswith(original_index)
    assert b"agentretro:summary:start project=NPKI" in summary.read_bytes()
    assert b"agentretro:index:start project=NPKI" in index.read_bytes()
    assert (plan.backup_dir / "项目" / "NPKI" / "项目_NPKI.md").read_bytes() == (
        original_summary
    )
    assert (plan.backup_dir / "项目" / "项目索引.md").read_bytes() == original_index
    assert repository.get_sync_job(plan.id).status == ProjectionStatus.SYNCED.value

    summary.unlink()
    missing_plan = initializer.preview("NPKI")
    initializer.apply("NPKI", missing_plan.id)
    assert not summary.exists()


def test_nested_project_preview_and_apply_use_leaf_summary_name(tmp_path: Path) -> None:
    project_id = "Team/Example"
    vault, summary, index = _targets(tmp_path, project_id)
    original_summary = "# Example\n\n人工摘要\n".encode()
    original_index = "# 项目索引\n\n- [[项目/OTHER]]\n".encode()
    summary.write_bytes(original_summary)
    index.write_bytes(original_index)
    repository = _repository(tmp_path, project_id)
    initializer = _initializer(tmp_path, repository=repository)

    plan = initializer.preview(project_id)

    assert [target.relative_path.as_posix() for target in plan.targets] == [
        "项目/Team/Example/项目_Example.md",
        "项目/项目索引.md",
    ]
    assert _snapshot(vault)["项目/Team/Example/项目_Example.md"] == original_summary

    result = initializer.apply(project_id, plan.id)

    assert result.status is ProjectionStatus.SYNCED
    assert result.changed is True
    assert b"agentretro:summary:start project=Team/Example" in summary.read_bytes()
    assert b"agentretro:index:start project=Team/Example" in index.read_bytes()
    assert (
        plan.backup_dir / "项目" / "Team" / "Example" / "项目_Example.md"
    ).read_bytes() == original_summary


def test_os_27_changed_target_rejects_stale_plan_before_backup_or_write(
    tmp_path: Path,
) -> None:
    _, summary, index = _targets(tmp_path)
    summary.write_text("original\n", encoding="utf-8")
    index.write_bytes(b"index\n")
    initializer = _initializer(tmp_path)
    plan = initializer.preview("NPKI")
    summary.write_text("external edit\n", encoding="utf-8")
    before = _snapshot(tmp_path / "vault")

    with pytest.raises(BoundaryInitStalePlan):
        initializer.apply("NPKI", plan.id)

    assert _snapshot(tmp_path / "vault") == before
    assert not plan.backup_dir.exists()


@pytest.mark.parametrize(
    "content",
    [
        b"<!-- agentretro:summary:start project=NPKI -->\n",
        (
            b"<!-- agentretro:summary:start project=NPKI -->\n"
            b"<!-- agentretro:summary:start project=NPKI -->\n"
            b"<!-- agentretro:summary:end -->\n"
        ),
        (
            b"<!-- agentretro:index:start project=NPKI -->\n"
            b"<!-- agentretro:index:end -->\n"
        ),
        (
            b"<!-- agentretro:summary:start project=OTHER -->\n"
            b"<!-- agentretro:summary:end -->\n"
        ),
        b"invalid-utf8-\xff",
    ],
)
def test_os_28_unsafe_marker_or_encoding_rejects_complete_plan(
    tmp_path: Path, content: bytes
) -> None:
    vault, summary, index = _targets(tmp_path)
    summary.write_bytes(content)
    index.write_text("safe index\n", encoding="utf-8")
    before = _snapshot(vault)

    with pytest.raises(BoundaryInitError):
        _initializer(tmp_path).preview("NPKI")

    assert _snapshot(vault) == before


def test_os_28_directory_or_symlink_target_is_rejected_without_write(
    tmp_path: Path,
) -> None:
    vault, summary, index = _targets(tmp_path)
    summary.mkdir()
    index.write_bytes(b"index\n")
    with pytest.raises(BoundaryInitError):
        _initializer(tmp_path).preview("NPKI")

    summary.rmdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        summary.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(BoundaryInitError):
        _initializer(tmp_path).preview("NPKI")
    assert outside.read_text(encoding="utf-8") == "outside"
    assert summary.is_symlink()
    assert index.read_bytes() == b"index\n"


@pytest.mark.parametrize(
    "project_id",
    [
        "../NPKI",
        "Team/../../NPKI",
        "/absolute/NPKI",
        "C:/absolute/NPKI",
        "//server/share/NPKI",
        "Team/./NPKI",
        "Team//NPKI",
        "Team\\NPKI",
        "Team/NPKI?",
        "NPKI\nOTHER",
        "NPKI -->",
    ],
)
def test_os_28_project_identity_cannot_escape_path_or_marker(
    tmp_path: Path, project_id: str
) -> None:
    vault, _, _ = _targets(tmp_path)
    before = _snapshot(vault)

    with pytest.raises(BoundaryInitError, match="invalid_project_id"):
        _initializer(tmp_path).preview(project_id)

    assert _snapshot(vault) == before
    assert not (tmp_path / "state" / "backups").exists()


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_os_29_multi_target_failure_restores_or_records_rollback_required(
    tmp_path: Path, rollback_fails: bool
) -> None:
    vault, summary, index = _targets(tmp_path)
    summary.write_text("summary\n", encoding="utf-8")
    index.write_text("index\n", encoding="utf-8")
    before = _snapshot(vault)
    calls = 0

    def injected_replace(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2 or (rollback_fails and calls == 3):
            raise OSError("injected replace failure")
        os.replace(source, target)

    repository = _repository(tmp_path)
    initializer = _initializer(
        tmp_path, repository=repository, replace=injected_replace
    )
    plan = initializer.preview("NPKI")

    result = initializer.apply("NPKI", plan.id)

    if rollback_fails:
        assert result.status is ProjectionStatus.ROLLBACK_REQUIRED
        assert repository.has_rollback_required_sync() is True
    else:
        assert result.status is ProjectionStatus.SYNC_PENDING
        assert _snapshot(vault) == before
    assert plan.backup_dir.exists()


def test_os_29_retry_after_verified_rollback_reuses_retained_backup(
    tmp_path: Path,
) -> None:
    _, summary, index = _targets(tmp_path)
    summary.write_bytes(b"summary\n")
    index.write_bytes(b"index\n")
    calls = 0

    def fail_second_replace(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replace failure")
        os.replace(source, target)

    repository = _repository(tmp_path)
    failed_initializer = _initializer(
        tmp_path, repository=repository, replace=fail_second_replace
    )
    plan = failed_initializer.preview("NPKI")
    failed = failed_initializer.apply("NPKI", plan.id)
    retained = _snapshot(plan.backup_dir)

    assert failed.status is ProjectionStatus.SYNC_PENDING
    retry_initializer = _initializer(tmp_path, repository=repository)
    retry_plan = retry_initializer.preview("NPKI")
    retried = retry_initializer.apply("NPKI", retry_plan.id)

    assert retry_plan.id == plan.id
    assert retried.status is ProjectionStatus.SYNCED
    assert _snapshot(plan.backup_dir) == retained
    assert b"agentretro:summary:start" in summary.read_bytes()
    assert b"agentretro:index:start" in index.read_bytes()


def test_sync_init_cli_previews_then_applies_exact_plan(tmp_path: Path, capsys) -> None:
    _, summary, index = _targets(tmp_path)
    summary.write_text("summary\n", encoding="utf-8")
    index.write_text("index\n", encoding="utf-8")
    _repository(tmp_path)
    env = {
        "AGENTRETRO_HOME": str(tmp_path / "state"),
        "AGENTRETRO_OBSIDIAN_ROOT": str(tmp_path / "vault"),
    }

    assert (
        retro_cli.main(
            ["--json", "sync", "init", "--project", "NPKI"],
            home=tmp_path,
            env=env,
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    assert preview["code"] == "RETRO_SYNC_INIT_PREVIEW"
    assert preview["data"]["changed"] is True
    plan_id = preview["data"]["plan_id"]
    assert summary.read_text(encoding="utf-8") == "summary\n"

    assert (
        retro_cli.main(
            [
                "--json",
                "sync",
                "init",
                "--project",
                "NPKI",
                "--apply",
                plan_id,
            ],
            home=tmp_path,
            env=env,
        )
        == 0
    )
    applied = json.loads(capsys.readouterr().out)
    assert applied["code"] == "RETRO_SYNC_INIT_APPLIED"
    assert applied["data"]["status"] == ProjectionStatus.SYNCED.value
    assert b"agentretro:summary:start" in summary.read_bytes()
