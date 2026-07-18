from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_retro.application.sync import ProjectionCoordinator, SyncService
from agent_retro.domain.models import (
    Knowledge,
    KnowledgeType,
    ProjectMapping,
    ProjectionStatus,
)
from agent_retro.infrastructure.obsidian import (
    BoundaryError,
    ObsidianProjection,
    UnsafeVaultPathError,
    replace_managed_block,
)
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)


def _knowledge(
    identifier: str,
    kind: KnowledgeType,
    *,
    status: str = "active",
    text: str = "保留明确证据。",
) -> Knowledge:
    return Knowledge(
        id=identifier,
        version=2,
        candidate_id=f"candidate-{identifier}",
        knowledge_type=kind,
        project_id="NPKI",
        scope="project",
        text=text,
        status=status,
        confidence=0.98,
        accepted_by="user",
        evidence_ids=("evidence-2", "evidence-1"),
        valid_until=None,
        updated_at=NOW,
        supersedes=(f"{identifier}:v1",),
    )


def _repository(tmp_path: Path) -> SQLiteRetroRepository:
    repository = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping(
            id="mapping-npki",
            git_root=tmp_path / "repo",
            remote_identity="https://example.invalid/npki.git",
            obsidian_project="NPKI",
        ),
        "user",
    )
    return repository


class KnowledgeRepository(SQLiteRetroRepository):
    def __init__(self, db_path: Path, backup_dir: Path, items: list[Knowledge]):
        super().__init__(db_path, backup_dir)
        self.items = items

    def list_project_knowledge(self, project_id: str) -> list[Knowledge]:
        return [item for item in self.items if item.project_id == project_id]


def _coordinator(
    tmp_path: Path,
    items: list[Knowledge],
    *,
    replace=os.replace,
) -> tuple[KnowledgeRepository, ProjectionCoordinator]:
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = KnowledgeRepository(
        tmp_path / "retro.db", tmp_path / "backups", items
    )
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping(
            id="mapping-npki",
            git_root=tmp_path / "repo",
            remote_identity="https://example.invalid/npki.git",
            obsidian_project="NPKI",
        ),
        "user",
    )
    projection = ObsidianProjection(vault, tmp_path / "backups")
    sync = SyncService(repository, vault, tmp_path / "backups", replace=replace)
    return repository, ProjectionCoordinator(repository, projection, sync)


def test_three_types_render_to_deterministic_aggregate_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    items = [
        _knowledge("z-rule", KnowledgeType.RULE),
        _knowledge("a-rule", KnowledgeType.RULE, status="archived"),
        _knowledge("lesson", KnowledgeType.LESSON),
        _knowledge("task", KnowledgeType.TASK_STATE),
    ]
    projection = ObsidianProjection(vault, tmp_path / "backups")

    first = projection.plan("NPKI", items)
    second = projection.plan("NPKI", list(reversed(items)))

    assert [write.target.name for write in first.writes] == [
        "规则.md",
        "经验.md",
        "任务状态.md",
    ]
    assert [write.after_bytes for write in first.writes] == [
        write.after_bytes for write in second.writes
    ]
    rule = first.writes[0].after_bytes.decode("utf-8")
    assert rule.index("z-rule") < rule.index("## 已归档") < rule.index("a-rule")
    for field in ("ID", "范围", "置信度", "证据", "版本", "更新时间"):
        assert field in rule


def test_managed_block_replaces_only_inner_bytes() -> None:
    original = (
        "人工前言\r\n"
        "<!-- agentretro:summary:start project=NPKI -->\r\n"
        "旧摘要\r\n"
        "<!-- agentretro:summary:end -->\r\n"
        "人工结尾\r\n"
    ).encode()

    updated = replace_managed_block(original, "NPKI", "新摘要")

    assert updated.startswith("人工前言\r\n".encode())
    assert updated.endswith("人工结尾\r\n".encode())
    assert "新摘要\r\n".encode() in updated


@pytest.mark.parametrize(
    "content",
    [
        b"no markers",
        b"<!-- agentretro:summary:start project=NPKI -->\n",
        (
            b"<!-- agentretro:summary:start project=NPKI -->\n"
            b"<!-- agentretro:summary:start project=NPKI -->\n"
            b"<!-- agentretro:summary:end -->\n"
        ),
        (
            b"<!-- agentretro:summary:start project=OTHER -->\n"
            b"<!-- agentretro:summary:end -->\n"
        ),
    ],
)
def test_managed_block_rejects_malformed_boundaries(content: bytes) -> None:
    with pytest.raises(BoundaryError):
        replace_managed_block(content, "NPKI", "new")


def test_plan_rejects_project_traversal(tmp_path: Path) -> None:
    with pytest.raises(UnsafeVaultPathError):
        ObsidianProjection(tmp_path / "vault", tmp_path / "backups").plan(
            "../outside", [_knowledge("rule", KnowledgeType.RULE)]
        )


def test_apply_preflights_all_targets_before_first_write(tmp_path: Path) -> None:
    repository, coordinator = _coordinator(
        tmp_path,
        [
            _knowledge("rule", KnowledgeType.RULE),
            _knowledge("lesson", KnowledgeType.LESSON),
        ],
    )
    rule = tmp_path / "vault" / "项目" / "NPKI" / "AgentRetro" / "规则.md"
    lesson = rule.with_name("经验.md")
    rule.parent.mkdir(parents=True)
    rule.write_bytes(b"old-rule")
    lesson.write_bytes(b"old-lesson")
    event = repository.save_projection_event("event", "NPKI", "accept", "k", "h")
    plan = coordinator.projection.plan(
        "NPKI", repository.items, event_id=event
    )
    lesson.write_bytes(b"external-change")

    result = coordinator.sync.apply(plan, event_id=event)

    assert result.status is ProjectionStatus.SYNC_PENDING
    assert rule.read_bytes() == b"old-rule"


def test_symlink_escape_is_rejected_without_write(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unsupported")
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    project_parent = vault / "项目"
    project_parent.mkdir()
    try:
        os.symlink(outside, project_parent / "NPKI", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")

    with pytest.raises(UnsafeVaultPathError):
        ObsidianProjection(vault, tmp_path / "backups").plan(
            "NPKI", [_knowledge("rule", KnowledgeType.RULE)]
        )
    assert list(outside.iterdir()) == []


def test_later_replace_failure_restores_every_target_exactly(tmp_path: Path) -> None:
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replace failure")
        os.replace(source, target)

    repository, coordinator = _coordinator(
        tmp_path,
        [
            _knowledge("rule", KnowledgeType.RULE),
            _knowledge("lesson", KnowledgeType.LESSON),
        ],
        replace=fail_second,
    )
    root = tmp_path / "vault" / "项目" / "NPKI" / "AgentRetro"
    root.mkdir(parents=True)
    before = {"规则.md": b"manual rule", "经验.md": b"manual lesson"}
    for name, data in before.items():
        (root / name).write_bytes(data)

    result = coordinator.after_commit("accept", "rule", "NPKI")

    assert result.status is ProjectionStatus.SYNC_PENDING
    assert {name: (root / name).read_bytes() for name in before} == before
    assert any((tmp_path / "backups").rglob("规则.md"))


def test_restoration_failure_blocks_future_sync(tmp_path: Path) -> None:
    calls = 0

    def fail_write_and_restore(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OSError("injected restore failure")
        os.replace(source, target)

    repository, coordinator = _coordinator(
        tmp_path,
        [
            _knowledge("rule", KnowledgeType.RULE),
            _knowledge("lesson", KnowledgeType.LESSON),
        ],
        replace=fail_write_and_restore,
    )
    aggregate = tmp_path / "vault" / "项目" / "NPKI" / "AgentRetro"
    aggregate.mkdir(parents=True)
    (aggregate / "规则.md").write_bytes(b"old rule")
    (aggregate / "经验.md").write_bytes(b"old lesson")

    failed = coordinator.after_commit("accept", "rule", "NPKI")
    refused = coordinator.after_commit("edit", "rule", "NPKI")

    assert failed.status is ProjectionStatus.ROLLBACK_REQUIRED
    assert refused.status is ProjectionStatus.ROLLBACK_REQUIRED
    assert "doctor" in refused.recovery_command


def test_after_commit_is_idempotent_and_log_has_one_event(tmp_path: Path) -> None:
    repository, coordinator = _coordinator(
        tmp_path, [_knowledge("rule", KnowledgeType.RULE)]
    )

    first = coordinator.after_commit("accept", "rule", "NPKI")
    second = coordinator.after_commit("accept", "rule", "NPKI")

    assert first.status is ProjectionStatus.SYNCED
    assert second.status is ProjectionStatus.SYNCED
    assert repository.projection_event_count("NPKI") == 1
    log = (
        tmp_path / "vault" / "项目" / "NPKI" / "AgentRetro" / "变更日志.md"
    ).read_text(encoding="utf-8")
    assert log.count(first.event_id) == 1


def test_projection_failure_keeps_sqlite_authority_and_retry_succeeds(
    tmp_path: Path,
) -> None:
    repository, coordinator = _coordinator(
        tmp_path, [_knowledge("rule", KnowledgeType.RULE)]
    )
    vault = tmp_path / "vault"
    vault.rmdir()

    failed = coordinator.after_commit("accept", "rule", "NPKI")
    vault.mkdir()
    retried = coordinator.retry(failed.event_id)

    assert failed.status is ProjectionStatus.SYNC_PENDING
    assert repository.items[0].status == "active"
    assert failed.recovery_command == f"retro sync retry {failed.event_id}"
    assert retried.status is ProjectionStatus.SYNCED


def test_backup_enumeration_and_confirmed_removal_are_hash_bound(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    backup = tmp_path / "backups" / "run" / "copy.md"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(b"sensitive-copy")
    expected = hashlib.sha256(b"sensitive-copy").hexdigest()
    service = SyncService(
        repository, tmp_path / "vault", tmp_path / "backups"
    )

    assert service.enumerate_backups_containing(expected) == (backup,)
    with pytest.raises(ValueError):
        service.remove_confirmed_backup_copy(backup, "0" * 64)
    service.remove_confirmed_backup_copy(backup, expected)
    assert not backup.exists()
