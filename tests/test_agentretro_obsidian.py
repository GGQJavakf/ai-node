from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_retro.application.sync import ProjectionCoordinator, SyncService
from agent_retro.domain.models import (
    Candidate,
    CandidateStatus,
    Evidence,
    Knowledge,
    KnowledgeConflict,
    KnowledgeType,
    NormalizedSession,
    ProjectMapping,
    ProjectionStatus,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
)
from agent_retro.infrastructure.obsidian import (
    BoundaryError,
    ObsidianProjection,
    UnsafeVaultPathError,
    replace_managed_block,
)
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation.cli import main


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


def _seed_pending_candidate(
    repository: SQLiteRetroRepository,
    candidate_id: str = "candidate-rule",
    *,
    kind: KnowledgeType = KnowledgeType.RULE,
) -> None:
    locator = SourceLocator("source-session", "event-1", "session.jsonl", "a" * 64)
    session = NormalizedSession(
        id="session-1",
        source_session_id="source-session",
        source_path=Path("session.jsonl"),
        source_hash="b" * 64,
        project_id="NPKI",
        completed=True,
        completed_at=NOW,
        events=(),
    )
    evidence = Evidence("evidence-1", session.id, "user", locator, "用户明确要求")
    repository.save_capture(session, [evidence])
    repository.save_candidates(
        [
            Candidate(
                id=candidate_id,
                knowledge_type=kind,
                project_id="NPKI",
                scope="project",
                proposed_text="保留明确证据。",
                evidence_ids=(evidence.id,),
                status=CandidateStatus.PENDING_REVIEW,
                extraction_confidence=0.98,
            )
        ]
    )


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
        (
            b"<!-- agentretro:summary:start project=NPKI -->\n"
            b"content\n<!-- agentretro:index:end -->\n"
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


def test_broken_symlink_target_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "项目").mkdir(parents=True)
    try:
        os.symlink(
            tmp_path / "missing-target",
            vault / "项目" / "NPKI",
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(UnsafeVaultPathError):
        ObsidianProjection(vault, tmp_path / "backups").plan(
            "NPKI", [_knowledge("rule", KnowledgeType.RULE)]
        )


def test_backup_symlink_escape_is_rejected_before_target_write(tmp_path: Path) -> None:
    repository, coordinator = _coordinator(
        tmp_path, [_knowledge("rule", KnowledgeType.RULE)]
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    backup_root = tmp_path / "backups"
    try:
        os.symlink(outside, backup_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    result = coordinator.after_commit("accept", "rule", "NPKI")
    assert result.status is ProjectionStatus.SYNC_PENDING
    assert not (tmp_path / "vault" / "项目").exists()
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
    assert failed.warning == "RETRO_SYNC_PENDING"


def test_repository_finalize_failure_restores_files_and_states(tmp_path: Path) -> None:
    class FinalizeFailureRepository(KnowledgeRepository):
        def complete_sync(self, *args, **kwargs) -> None:
            raise OSError("secret finalize detail")

    vault = tmp_path / "vault"
    vault.mkdir()
    repository = FinalizeFailureRepository(
        tmp_path / "retro.db",
        tmp_path / "backups",
        [_knowledge("rule", KnowledgeType.RULE)],
    )
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        SyncService(repository, vault, tmp_path / "backups"),
    )

    result = coordinator.after_commit("accept", "rule", "NPKI")

    assert result.status is ProjectionStatus.SYNC_PENDING
    assert result.warning == "RETRO_SYNC_PENDING"
    assert "secret" not in result.warning
    assert not (vault / "项目" / "NPKI" / "AgentRetro" / "规则.md").exists()
    assert repository.get_managed_file_state(
        vault / "项目" / "NPKI" / "AgentRetro" / "规则.md"
    ) is None


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


def test_cli_accept_commits_then_projects_once_in_same_command(
    tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    vault.mkdir()
    state = home / ".agentretro"
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping(
            "mapping-npki", tmp_path / "repo", "https://invalid/npki", "NPKI"
        ),
        "user",
    )
    _seed_pending_candidate(repository)

    result = main(
        ["--json", "review", "accept", "candidate-rule"],
        home=home,
        env={"AGENTRETRO_OBSIDIAN_ROOT": str(vault)},
    )

    assert result == 0
    accepted = repository.knowledge_for_candidate("candidate-rule")
    assert accepted is not None and accepted.status == "active"
    assert repository.projection_event_count("NPKI") == 1
    assert (vault / "项目" / "NPKI" / "AgentRetro" / "规则.md").exists()
    assert '"projection"' in capsys.readouterr().out


def test_cli_accept_keeps_knowledge_when_vault_unavailable_then_sync_retry(
    tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "missing-vault"
    state = home / ".agentretro"
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping(
            "mapping-npki", tmp_path / "repo", "https://invalid/npki", "NPKI"
        ),
        "user",
    )
    _seed_pending_candidate(repository)
    env = {"AGENTRETRO_OBSIDIAN_ROOT": str(vault)}

    accepted = main(
        ["--json", "review", "accept", "candidate-rule"], home=home, env=env
    )
    output = capsys.readouterr().out
    event = repository.list_projection_events("NPKI")[0]
    vault.mkdir()
    retried = main(["--json", "sync", "retry", event.id], home=home, env=env)

    assert accepted == 0 and retried == 0
    assert repository.knowledge_for_candidate("candidate-rule").status == "active"
    assert "sync_pending" in output and "retro sync retry" in output
    assert repository.get_projection_event(event.id).status is ProjectionStatus.SYNCED


def test_cli_edit_and_archive_each_trigger_one_post_commit_projection(
    tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    vault.mkdir()
    state = home / ".agentretro"
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    _seed_pending_candidate(repository)
    env = {"AGENTRETRO_OBSIDIAN_ROOT": str(vault)}

    assert (
        main(
            [
                "--json",
                "review",
                "edit",
                "candidate-rule",
                "--text",
                "编辑后的规则。",
            ],
            home=home,
            env=env,
        )
        == 0
    )
    capsys.readouterr()
    assert repository.projection_event_count("NPKI") == 1
    knowledge = repository.knowledge_for_candidate("candidate-rule")
    assert main(
        ["--json", "review", "archive", knowledge.id], home=home, env=env
    ) == 0
    capsys.readouterr()
    assert repository.projection_event_count("NPKI") == 2
    aggregate = (vault / "项目" / "NPKI" / "AgentRetro" / "规则.md").read_text(
        encoding="utf-8"
    )
    assert aggregate.index("## 已归档") < aggregate.index(knowledge.id)


def test_cli_conflict_resolution_triggers_one_post_commit_projection(
    tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    vault.mkdir()
    state = home / ".agentretro"
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    _seed_pending_candidate(repository, "candidate-active")
    active = repository.accept_candidate(
        "candidate-active", "旧规则", "user", 0.98
    )
    evidence = repository.list_evidence("session-1")[0]
    repository.save_candidates(
        [
            Candidate(
                "candidate-new",
                KnowledgeType.RULE,
                "NPKI",
                "project",
                "新规则",
                (evidence.id,),
                CandidateStatus.PENDING_REVIEW,
                0.98,
            )
        ]
    )
    repository.create_conflict(
        KnowledgeConflict(
            "conflict-1", active.id, "candidate-new", "冲突", "合并规则", "open"
        )
    )

    result = main(
        [
            "--json",
            "review",
            "merge",
            "conflict-1",
            "--text",
            "最终规则",
        ],
        home=home,
        env={"AGENTRETRO_OBSIDIAN_ROOT": str(vault)},
    )

    assert result == 0
    capsys.readouterr()
    assert repository.projection_event_count("NPKI") == 1


def test_cli_auto_acceptance_triggers_one_post_commit_projection(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    vault.mkdir()
    state = home / ".agentretro"
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    _seed_pending_candidate(repository)

    class AutoAcceptReview:
        def __init__(self, repo):
            self.repo = repo

        def review_session(self, session_id: str):
            self.repo.accept_candidate(
                "candidate-rule",
                "自动接受规则",
                "model-review",
                0.99,
                candidate_status=CandidateStatus.AUTO_ACCEPTED,
            )
            return [
                ReviewResult(
                    ReviewVerdict.ACCEPT,
                    0.99,
                    "evidence-bound",
                    "自动接受规则",
                    None,
                    None,
                )
            ]

    monkeypatch.setattr(
        "agent_retro.presentation.cli._build_review_service",
        lambda settings, repo: AutoAcceptReview(repo),
    )
    result = main(
        ["--json", "review", "run", "--session", "source-session"],
        home=home,
        env={"AGENTRETRO_OBSIDIAN_ROOT": str(vault)},
    )

    assert result == 0
    capsys.readouterr()
    assert repository.projection_event_count("NPKI") == 1
    assert repository.knowledge_for_candidate("candidate-rule").status == "active"


def test_human_accept_reports_sqlite_commit_and_projection_recovery(
    tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    state = home / ".agentretro"
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    _seed_pending_candidate(repository)

    result = main(
        ["review", "accept", "candidate-rule"],
        home=home,
        env={"AGENTRETRO_OBSIDIAN_ROOT": str(tmp_path / "missing-vault")},
    )
    output = capsys.readouterr().out

    assert result == 0
    assert "SQLite 已提交，知识保持有效" in output
    assert "RETRO_SYNC_PENDING" in output
    assert "retro sync retry" in output


def test_same_batch_updates_summary_and_index_only_inside_valid_markers(
    tmp_path: Path,
) -> None:
    repository, coordinator = _coordinator(
        tmp_path, [_knowledge("rule", KnowledgeType.RULE)]
    )
    vault = tmp_path / "vault"
    summary = vault / "项目" / "NPKI" / "项目_NPKI.md"
    index = vault / "项目" / "项目索引.md"
    summary.parent.mkdir(parents=True)
    summary_before = (
        b"human-summary-before\n"
        b"<!-- agentretro:summary:start project=NPKI -->\nold\n"
        b"<!-- agentretro:summary:end -->\nhuman-summary-after\n"
    )
    index_before = (
        b"human-index-before\n"
        b"<!-- agentretro:index:start project=NPKI -->\nold\n"
        b"<!-- agentretro:index:end -->\nhuman-index-after\n"
    )
    summary.write_bytes(summary_before)
    index.write_bytes(index_before)

    result = coordinator.after_commit("accept", "rule", "NPKI")

    assert result.status is ProjectionStatus.SYNCED
    assert summary.read_bytes().startswith(b"human-summary-before\n")
    assert summary.read_bytes().endswith(b"human-summary-after\n")
    assert index.read_bytes().startswith(b"human-index-before\n")
    assert index.read_bytes().endswith(b"human-index-after\n")
    event = repository.get_projection_event(result.event_id)
    backup_dir = tmp_path / "backups"
    assert any(
        path.read_bytes() == summary_before for path in backup_dir.rglob("项目_NPKI.md")
    )
    assert any(path.read_bytes() == index_before for path in backup_dir.rglob("项目索引.md"))
    assert event is not None and event.status is ProjectionStatus.SYNCED
