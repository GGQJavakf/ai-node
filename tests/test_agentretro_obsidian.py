from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sqlite3
import sys
import threading
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
from agent_retro.domain.projection import projection_input_hash
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

    def save_current_projection_event(
        self, project_id: str, cause: str, cause_entity_id: str
    ) -> str:
        input_hash = projection_input_hash(self.list_project_knowledge(project_id))
        identity = json.dumps(
            [project_id, cause, cause_entity_id, input_hash],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        event_id = "projection-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        return self.save_projection_event(
            event_id, project_id, cause, cause_entity_id, input_hash
        )

    def projection_fence_matches(
        self, event_id: str, expected_input_hash: str
    ) -> bool:
        events = self.list_projection_events("NPKI")
        return (
            bool(events)
            and events[-1].id == event_id
            and projection_input_hash(self.items) == expected_input_hash
        )

    def complete_sync(
        self,
        event_id: str,
        project_id: str,
        file_states,
        expected_input_hash: str,
    ) -> None:
        if not self.projection_fence_matches(event_id, expected_input_hash):
            raise RuntimeError("projection superseded")
        for path, managed_hash, full_hash in file_states:
            self.save_managed_file_state(project_id, path, managed_hash, full_hash)
        self.finish_sync(event_id, ProjectionStatus.SYNCED.value)
        self.finish_projection_event(event_id, ProjectionStatus.SYNCED)


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


def test_unconfigured_vault_never_uses_preexisting_placeholder_directory(
    tmp_path: Path, capsys
) -> None:
    home = tmp_path / "home"
    state = home / ".agentretro"
    placeholder = state / "unconfigured-obsidian"
    placeholder.mkdir(parents=True)
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    _seed_pending_candidate(repository)

    assert main(["--json", "review", "accept", "candidate-rule"], home=home, env={}) == 0
    output = capsys.readouterr().out
    event = repository.list_projection_events("NPKI")[0]

    assert list(placeholder.rglob("*")) == []
    assert event.status is ProjectionStatus.SYNC_PENDING
    assert event.error == "vault_not_configured"
    assert "vault_not_configured" in output
    configured = tmp_path / "configured-vault"
    configured.mkdir()
    assert main(
        ["--json", "sync", "retry", event.id],
        home=home,
        env={"AGENTRETRO_OBSIDIAN_ROOT": str(configured)},
    ) == 0
    capsys.readouterr()
    assert repository.get_projection_event(event.id).status is ProjectionStatus.SYNCED
    assert (configured / "项目" / "NPKI" / "AgentRetro" / "规则.md").exists()


def test_projection_exception_details_never_reach_persistence_audit_or_output(
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-C:/users/name/secret-token"

    class ExplodingProjection(ObsidianProjection):
        def plan(self, *args, **kwargs):
            raise OSError(secret)

    repository, coordinator = _coordinator(
        tmp_path, [_knowledge("rule", KnowledgeType.RULE)]
    )
    coordinator = ProjectionCoordinator(
        repository,
        ExplodingProjection(tmp_path / "vault", tmp_path / "backups"),
        coordinator.sync,
    )

    result = coordinator.after_commit("accept", "rule", "NPKI")
    event = repository.get_projection_event(result.event_id)
    audits = repository.list_audit_entries(entity_id=result.event_id)
    serialized = json.dumps(
        {
            "result": result.__dict__,
            "event": event.__dict__,
            "audits": [entry.__dict__ for entry in audits],
        },
        default=str,
        ensure_ascii=False,
    )

    assert secret not in serialized
    assert event.error == "planning_failed"
    assert result.reason == "planning_failed"


def test_older_paused_projection_cannot_overwrite_newer_committed_knowledge(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = _repository(tmp_path)
    _seed_pending_candidate(repository, "candidate-old")
    old = repository.accept_candidate("candidate-old", "旧知识", "user", 0.98)
    evidence = repository.list_evidence("session-1")[0]
    repository.save_candidates(
        [
            Candidate(
                "candidate-new",
                KnowledgeType.RULE,
                "NPKI",
                "project",
                "新知识",
                (evidence.id,),
                CandidateStatus.PENDING_REVIEW,
                0.99,
            )
        ]
    )
    first_replace_entered = threading.Event()
    release_first_replace = threading.Event()
    replace_count = 0

    def pausing_replace(source: Path, target: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 1:
            first_replace_entered.set()
            assert release_first_replace.wait(5)
        os.replace(source, target)

    projection = ObsidianProjection(vault, tmp_path / "backups")
    coordinator = ProjectionCoordinator(
        repository,
        projection,
        SyncService(
            repository, vault, tmp_path / "backups", replace=pausing_replace
        ),
    )
    results: dict[str, object] = {}
    old_thread = threading.Thread(
        target=lambda: results.setdefault(
            "old", coordinator.after_commit("accept", old.id, "NPKI")
        )
    )
    old_thread.start()
    assert first_replace_entered.wait(5)
    new = repository.accept_candidate("candidate-new", "新知识", "user", 0.99)
    new_thread = threading.Thread(
        target=lambda: results.setdefault(
            "new", coordinator.after_commit("accept", new.id, "NPKI")
        )
    )
    new_thread.start()
    release_first_replace.set()
    old_thread.join(10)
    new_thread.join(10)

    content = (vault / "项目" / "NPKI" / "AgentRetro" / "规则.md").read_text(
        encoding="utf-8"
    )
    assert "新知识" in content and "旧知识" in content
    assert results["old"].status is ProjectionStatus.SYNC_PENDING
    assert results["old"].reason == "projection_superseded"
    assert results["new"].status is ProjectionStatus.SYNCED
    log = (vault / "项目" / "NPKI" / "AgentRetro" / "变更日志.md").read_text(
        encoding="utf-8"
    )
    assert log.count(results["new"].event_id) == 1
    assert results["old"].event_id not in log


def test_project_file_lock_serializes_processes_and_auto_releases_on_exit(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows msvcrt lock contract")
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = _repository(tmp_path)
    _seed_pending_candidate(repository)
    knowledge = repository.accept_candidate(
        "candidate-rule", "跨进程锁知识", "user", 0.98
    )
    key = hashlib.sha256(b"NPKI").hexdigest()
    lock_root = (tmp_path / "backups").parent / ".projection-locks"
    lock_root.mkdir()
    lock_path = lock_root / f"{key}.lock"
    script = (
        "import msvcrt,sys,time\n"
        "p=sys.argv[1]\n"
        "f=open(p,'a+b')\n"
        "f.seek(0,2)\n"
        "f.write(b'0') if f.tell()==0 else None\n"
        "f.flush(); f.seek(0)\n"
        "msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)\n"
        "print('locked',flush=True)\n"
        "time.sleep(0.8)\n"
        "sys.exit(0)\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None and child.stdout.readline().strip() == "locked"
    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        SyncService(repository, vault, tmp_path / "backups"),
    )

    result = coordinator.after_commit("accept", knowledge.id, "NPKI")
    child.wait(timeout=5)

    assert child.returncode == 0
    assert result.status is ProjectionStatus.SYNCED
    assert lock_path.exists()
    assert (vault / "项目" / "NPKI" / "AgentRetro" / "规则.md").exists()


@pytest.mark.parametrize("boundary", ["marker", "symlink"])
def test_boundary_private_details_are_reduced_to_stable_reason(
    tmp_path: Path, boundary: str
) -> None:
    secret = "PRIVATE-USER-PATH"
    repository, coordinator = _coordinator(
        tmp_path, [_knowledge("rule", KnowledgeType.RULE)]
    )
    vault = tmp_path / "vault"
    if boundary == "marker":
        summary = vault / "项目" / "NPKI" / "项目_NPKI.md"
        summary.parent.mkdir(parents=True)
        summary.write_text(
            f"<!-- agentretro:summary:start project={secret} -->\n"
            "old\n<!-- agentretro:summary:end -->\n",
            encoding="utf-8",
        )
    else:
        (vault / "项目").mkdir()
        try:
            os.symlink(
                tmp_path / secret,
                vault / "项目" / "NPKI",
                target_is_directory=True,
            )
        except OSError:
            pytest.skip("symlink creation unavailable")

    result = coordinator.after_commit("accept", "rule", "NPKI")
    event = repository.get_projection_event(result.event_id)
    audits = repository.list_audit_entries(entity_id=result.event_id)
    serialized = json.dumps(
        [result.__dict__, event.__dict__, [entry.__dict__ for entry in audits]],
        default=str,
        ensure_ascii=False,
    )

    assert result.reason == "planning_failed"
    assert event.error == "planning_failed"
    assert secret not in serialized


def test_apply_rejects_plan_bound_to_different_event_before_any_filesystem_write(
    tmp_path: Path,
) -> None:
    repository, coordinator = _coordinator(
        tmp_path, [_knowledge("rule", KnowledgeType.RULE)]
    )
    input_hash = projection_input_hash(repository.items)
    event_a = repository.save_projection_event(
        "event-a", "NPKI", "accept", "a", input_hash
    )
    event_b = repository.save_projection_event(
        "event-b", "NPKI", "accept", "b", input_hash
    )
    plan_b = coordinator.projection.plan(
        "NPKI",
        repository.items,
        event_id=event_b,
        input_hash=input_hash,
    )
    lock_root = (tmp_path / "backups").parent / ".projection-locks"

    result = coordinator.sync.apply(plan_b, event_id=event_a)

    assert result.status is ProjectionStatus.SYNC_PENDING
    assert result.reason == "projection_identity_mismatch"
    assert repository.get_projection_event(event_a).error == (
        "projection_identity_mismatch"
    )
    assert not (tmp_path / "vault" / "项目").exists()
    assert not lock_root.exists()


def test_late_stale_event_does_not_poison_current_event_retry(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = _repository(tmp_path)
    _seed_pending_candidate(repository, "candidate-old")
    repository.accept_candidate("candidate-old", "旧知识", "user", 0.98)
    old_hash = projection_input_hash(repository.list_project_knowledge("NPKI"))
    old_ready = threading.Event()
    release_old = threading.Event()

    def save_late_old() -> None:
        old_ready.set()
        assert release_old.wait(5)
        repository.save_projection_event(
            "late-old", "NPKI", "accept", "old", old_hash
        )

    thread = threading.Thread(target=save_late_old)
    thread.start()
    assert old_ready.wait(5)
    evidence = repository.list_evidence("session-1")[0]
    repository.save_candidates(
        [
            Candidate(
                "candidate-new",
                KnowledgeType.RULE,
                "NPKI",
                "project",
                "新知识",
                (evidence.id,),
                CandidateStatus.PENDING_REVIEW,
                0.99,
            )
        ]
    )
    try:
        repository.accept_candidate("candidate-new", "新知识", "user", 0.99)
        current = repository.save_current_projection_event(
            "NPKI", "accept", "candidate-new"
        )
    finally:
        release_old.set()
        thread.join(5)
    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        SyncService(repository, vault, tmp_path / "backups"),
    )

    result = coordinator.retry(current)

    assert result.status is ProjectionStatus.SYNCED
    assert repository.get_projection_event(current).status is ProjectionStatus.SYNCED
    assert repository.get_projection_event("late-old").status is (
        ProjectionStatus.SYNC_PENDING
    )


def test_begin_sync_sqlite_error_is_sanitized_and_writes_no_vault_file(
    tmp_path: Path,
) -> None:
    secret = "PRIVATE-BEGIN-SQLITE"

    class BeginFailure(SQLiteRetroRepository):
        def begin_sync(self, job) -> None:
            raise sqlite3.OperationalError(secret)

    vault = tmp_path / "vault"
    vault.mkdir()
    repository = BeginFailure(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    _seed_pending_candidate(repository)
    knowledge = repository.accept_candidate(
        "candidate-rule", "开始日志失败", "user", 0.98
    )
    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        SyncService(repository, vault, tmp_path / "backups"),
    )

    result = coordinator.after_commit("accept", knowledge.id, "NPKI")
    event = repository.get_projection_event(result.event_id)
    serialized = json.dumps(
        [result.__dict__, event.__dict__, [a.__dict__ for a in repository.list_audit_entries()]],
        default=str,
    )

    assert result.reason == "journal_start_failed"
    assert event.error == "journal_start_failed"
    assert secret not in serialized
    assert not (vault / "项目").exists()


def test_finish_sync_sqlite_error_after_rollback_is_sanitized(tmp_path: Path) -> None:
    secret = "PRIVATE-FINISH-SQLITE"

    class FinishFailure(SQLiteRetroRepository):
        def finish_sync(self, job_id: str, status: str, error: str = "") -> None:
            raise sqlite3.OperationalError(secret)

    vault = tmp_path / "vault"
    vault.mkdir()
    repository = FinishFailure(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    _seed_pending_candidate(repository)
    knowledge = repository.accept_candidate(
        "candidate-rule", "结束日志失败", "user", 0.98
    )

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("PRIVATE-REPLACE")

    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        SyncService(
            repository, vault, tmp_path / "backups", replace=fail_replace
        ),
    )

    result = coordinator.after_commit("accept", knowledge.id, "NPKI")
    serialized = json.dumps(
        [result.__dict__, repository.get_projection_event(result.event_id).__dict__],
        default=str,
    )

    assert result.reason == "journal_update_failed"
    assert secret not in serialized
    assert "PRIVATE-REPLACE" not in serialized
    assert not (vault / "项目" / "NPKI" / "AgentRetro" / "规则.md").exists()


def test_rollback_required_retry_uses_stable_named_fields(tmp_path: Path) -> None:
    repository, coordinator = _coordinator(
        tmp_path, [_knowledge("rule", KnowledgeType.RULE)]
    )
    event_id = repository.save_projection_event(
        "rollback-event",
        "NPKI",
        "accept",
        "rule",
        projection_input_hash(repository.items),
    )
    repository.finish_projection_event(
        event_id, ProjectionStatus.ROLLBACK_REQUIRED, "rollback_failed"
    )

    result = coordinator.retry(event_id)

    assert result.warning == "RETRO_ROLLBACK_REQUIRED"
    assert result.reason == "rollback_failed"
    assert result.recovery_command == "retro doctor --repair-sync"


def test_unavailable_event_status_store_returns_sanitized_cli_recovery(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    secret = "PRIVATE-STATUS-SQLITE"

    class StatusFailure(SQLiteRetroRepository):
        def begin_sync(self, job) -> None:
            raise sqlite3.OperationalError(secret)

        def finish_projection_event(self, event_id, status, error="") -> None:
            raise sqlite3.OperationalError(secret)

    home = tmp_path / "home"
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = StatusFailure(
        home / ".agentretro" / "retro.db",
        home / ".agentretro" / "backups",
    )
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping("mapping", tmp_path / "repo", "remote", "NPKI"), "user"
    )
    _seed_pending_candidate(repository)
    monkeypatch.setattr(
        "agent_retro.presentation.cli.build_retro_repository",
        lambda settings: repository,
    )

    result = main(
        ["--json", "review", "accept", "candidate-rule"],
        home=home,
        env={"AGENTRETRO_OBSIDIAN_ROOT": str(vault)},
    )
    output = capsys.readouterr().out

    assert result == 2
    assert "RETRO_SYNC_STATE_UNAVAILABLE" in output
    assert "journal_start_failed" in output
    assert "retro doctor --repair-sync" in output
    assert secret not in output
    assert repository.knowledge_for_candidate("candidate-rule").status == "active"
