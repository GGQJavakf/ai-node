from __future__ import annotations

import json
import os
import sqlite3
import threading
import base64
from datetime import datetime, timezone
from pathlib import Path

import pytest

import _path  # noqa: F401

from agent_retro.application.merge import (
    ConfirmationRequiredError,
    MergeIntegrityError,
    MergeService,
    StalePlanError,
)
from agent_retro.application.knowledge import KnowledgeService
from agent_retro.application.sync import ProjectionCoordinator, SyncService
from agent_retro.application.sync import ProjectionPersistenceError
from agent_retro.domain.models import (
    Candidate,
    CandidateStatus,
    Evidence,
    Knowledge,
    KnowledgeType,
    NormalizedSession,
    ProjectMapping,
    SourceLocator,
)
from agent_retro.infrastructure.obsidian import ObsidianProjection, sha256_bytes
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation.cli import main


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)


def _knowledge(identifier: str = "rule-1", text: str = "数据库规则") -> Knowledge:
    return Knowledge(
        id=identifier,
        version=1,
        candidate_id=f"candidate-{identifier}",
        knowledge_type=KnowledgeType.RULE,
        project_id="NPKI",
        scope="project",
        text=text,
        status="active",
        confidence=0.98,
        accepted_by="user",
        evidence_ids=("evidence-1",),
        valid_until=None,
        updated_at=NOW,
    )


def _repo(tmp_path: Path) -> SQLiteRetroRepository:
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


def _service(
    tmp_path: Path, *, replace=os.replace
) -> tuple[SQLiteRetroRepository, MergeService, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = _repo(tmp_path)
    sync = SyncService(
        repository,
        vault,
        tmp_path / "backups",
        replace=replace,
    )
    return (
        repository,
        MergeService(repository, vault, tmp_path / "backups", sync=sync),
        vault,
    )


def _synchronize_rule(
    tmp_path: Path,
) -> tuple[SQLiteRetroRepository, MergeService, Path, Path]:
    repository, service, vault = _service(tmp_path)
    locator = SourceLocator("session-source", "event-1", "session.jsonl", "a" * 64)
    session = NormalizedSession(
        id="session-1",
        source_session_id="session-source",
        source_path=Path("session.jsonl"),
        source_hash="b" * 64,
        project_id="NPKI",
        completed=True,
        completed_at=NOW,
        events=(),
    )
    evidence = Evidence("evidence-1", session.id, "user", locator, "用户证据")
    repository.save_capture(session, (evidence,))
    repository.save_candidates(
        (
            Candidate(
                id="candidate-rule-1",
                knowledge_type=KnowledgeType.RULE,
                project_id="NPKI",
                scope="project",
                proposed_text="数据库规则",
                evidence_ids=(evidence.id,),
                status=CandidateStatus.PENDING_REVIEW,
                extraction_confidence=0.98,
            ),
        )
    )
    item = repository.accept_candidate("candidate-rule-1", "数据库规则", "user", 0.98)

    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        service.sync,
    )
    assert coordinator.after_commit("seed-rule", item.id, "NPKI").status.value == (
        "synced"
    )
    target = vault / "项目" / "NPKI" / "AgentRetro" / "规则.md"
    return repository, service, vault, target


def _synchronize_all_targets(
    tmp_path: Path,
) -> tuple[SQLiteRetroRepository, MergeService, Path]:
    repository, service, vault, _ = _synchronize_rule(tmp_path)
    summary = vault / "项目" / "NPKI" / "项目_NPKI.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        "summary outside\n"
        "<!-- agentretro:summary:start project=NPKI -->\nold\n"
        "<!-- agentretro:summary:end -->\nsummary footer\n",
        encoding="utf-8",
    )
    index = vault / "项目" / "项目索引.md"
    index.write_text(
        "index outside\n"
        "<!-- agentretro:index:start project=NPKI -->\nold\n"
        "<!-- agentretro:index:end -->\nindex footer\n",
        encoding="utf-8",
    )
    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        service.sync,
    )
    knowledge = repository.list_project_knowledge("NPKI")[0]
    assert coordinator.after_commit("seed-all", knowledge.id, "NPKI").status.value == (
        "synced"
    )
    return repository, service, vault


def test_external_edit_blocks_automatic_sync_and_preserves_both_versions(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    database_text = "数据库规则"
    target.write_text(
        target.read_text(encoding="utf-8").replace(database_text, "手工规则"),
        encoding="utf-8",
    )

    conflicts = service.find_external_edits("NPKI")

    assert len(conflicts) == 1
    assert conflicts[0].status == "external_edit_conflict"
    assert conflicts[0].path == Path("项目/NPKI/AgentRetro/规则.md")
    assert database_text in repository.list_project_knowledge("NPKI")[0].text
    assert "手工规则" in target.read_text(encoding="utf-8")
    assert repository.get_managed_file_state(target).full_hash != sha256_bytes(
        target.read_bytes()
    )


def test_automatic_projection_reports_external_edit_conflict_not_generic_failure(
    tmp_path: Path,
) -> None:
    repository, service, vault, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    event_id = repository.save_current_projection_event(
        "NPKI", "external-edit-check", "rule-1"
    )

    result = service.sync.synchronize(
        event_id, ObsidianProjection(vault, tmp_path / "backups")
    )

    assert result.status.value == "sync_pending"
    assert result.reason == "external_edit_conflict"
    assert repository.get_projection_event(event_id).error == "external_edit_conflict"
    assert "手工规则" in target.read_text(encoding="utf-8")


def test_adopt_vault_creates_pending_edit_candidate_with_provenance(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    conflict = service.find_external_edits("NPKI")[0]

    result = service.reconcile(conflict.id, "adopt_vault", actor="user")

    candidate = repository.get_candidate(result.candidate_id)
    assert result.status == "pending_review"
    assert candidate is not None
    assert candidate.status is CandidateStatus.PENDING_REVIEW
    assert candidate.proposed_text == "手工规则"
    evidence = repository.evidence_for_candidate(candidate.id)
    assert [item.kind for item in evidence] == ["obsidian-manual-edit"]
    assert repository.knowledge_for_candidate(candidate.id) is None

    adoption = repository.get_vault_adoption(candidate.id)
    assert adoption.knowledge_id == repository.list_project_knowledge("NPKI")[0].id
    assert adoption.original_version == 1
    assert adoption.original_text_hash == sha256_bytes("数据库规则".encode())
    assert adoption.status == "pending_review"
    # Adoption is not the authority boundary: baseline remains the last sync.
    assert repository.get_managed_file_state(target).managed_hash != sha256_bytes(
        target.read_bytes()
    )


def test_vault_adoption_accept_supersedes_same_identity_and_updates_baseline(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    candidate_id = service.reconcile(
        service.find_external_edits("NPKI")[0].id,
        "adopt_vault",
        actor="user",
    ).candidate_id
    original_id = repository.list_project_knowledge("NPKI")[0].id

    with pytest.raises(ValueError, match="vault_adoption_requires_guarded_accept"):
        repository.accept_candidate(candidate_id, "手工规则", "user", 0.0)

    accepted = KnowledgeService(repository, adoption_service=service).accept(
        candidate_id, actor="user"
    )

    assert accepted.id == original_id
    assert accepted.version == 2
    assert accepted.text == "手工规则"
    versions = repository.knowledge_versions(original_id)
    assert [item.status for item in versions] == ["superseded", "active"]
    assert repository.get_vault_adoption(candidate_id).status == "accepted"
    baseline = repository.get_managed_file_state(target)
    assert baseline.managed_hash == sha256_bytes(target.read_bytes())
    assert baseline.full_hash == sha256_bytes(target.read_bytes())


@pytest.mark.parametrize("drift", ["vault", "authority"])
def test_vault_adoption_accept_fails_closed_on_drift(
    tmp_path: Path, drift: str
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    original_baseline = repository.get_managed_file_state(target)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    candidate_id = service.reconcile(
        service.find_external_edits("NPKI")[0].id,
        "adopt_vault",
        actor="user",
    ).candidate_id
    original_id = repository.list_project_knowledge("NPKI")[0].id
    if drift == "vault":
        target.write_text("later vault edit", encoding="utf-8")
    else:
        repository.archive_knowledge(original_id, "user")

    with pytest.raises(StalePlanError):
        KnowledgeService(repository, adoption_service=service).accept(
            candidate_id, actor="user"
        )

    assert (
        repository.get_candidate(candidate_id).status is CandidateStatus.PENDING_REVIEW
    )
    assert repository.get_vault_adoption(candidate_id).status == "pending_review"
    assert repository.get_managed_file_state(target) == original_baseline
    if drift == "vault":
        assert repository.knowledge_versions(original_id)[-1].version == 1


def test_vault_adoption_reject_keeps_authority_and_baseline(tmp_path: Path) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    original_baseline = repository.get_managed_file_state(target)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    candidate_id = service.reconcile(
        service.find_external_edits("NPKI")[0].id,
        "adopt_vault",
        actor="user",
    ).candidate_id
    original_id = repository.list_project_knowledge("NPKI")[0].id

    rejected = KnowledgeService(repository, adoption_service=service).reject(
        candidate_id, actor="user"
    )

    assert rejected.status is CandidateStatus.REJECTED
    assert repository.get_vault_adoption(candidate_id).status == "rejected"
    assert repository.knowledge_versions(original_id)[-1].version == 1
    assert repository.get_managed_file_state(target) == original_baseline


def test_cli_accept_vault_adoption_projects_canonical_version_in_same_command(
    tmp_path: Path, capsys
) -> None:
    repository, service, vault, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    candidate_id = service.reconcile(
        service.find_external_edits("NPKI")[0].id,
        "adopt_vault",
        actor="user",
    ).candidate_id
    original_id = repository.list_project_knowledge("NPKI")[0].id
    env = {
        "AGENTRETRO_HOME": str(tmp_path),
        "AGENTRETRO_DB_PATH": str(repository.db_path),
        "AGENTRETRO_BACKUP_DIR": str(tmp_path / "backups"),
        "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
    }

    exit_code = main(
        ["--json", "review", "accept", candidate_id], home=tmp_path, env=env
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["data"]["id"] == original_id
    assert output["data"]["version"] == 2
    assert output["data"]["projection"]["status"] == "synced"
    assert "手工规则" in target.read_text(encoding="utf-8")
    assert [item.id for item in repository.list_project_knowledge("NPKI")] == [
        original_id
    ]


def test_vault_adoption_edit_uses_reviewed_text_on_same_identity(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    candidate_id = service.reconcile(
        service.find_external_edits("NPKI")[0].id,
        "adopt_vault",
        actor="user",
    ).candidate_id
    original_id = repository.list_project_knowledge("NPKI")[0].id

    edited = KnowledgeService(repository, adoption_service=service).edit(
        candidate_id, text="审核整理规则", actor="user"
    )

    assert edited.id == original_id
    assert edited.version == 2
    assert edited.text == "审核整理规则"
    assert repository.get_candidate(candidate_id).status is CandidateStatus.EDITED
    assert repository.get_vault_adoption(candidate_id).status == "accepted"


def test_vault_adoption_transaction_failure_rolls_back_every_state(
    tmp_path: Path, monkeypatch
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    baseline = repository.get_managed_file_state(target)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    candidate_id = service.reconcile(
        service.find_external_edits("NPKI")[0].id,
        "adopt_vault",
        actor="user",
    ).candidate_id
    original_id = repository.list_project_knowledge("NPKI")[0].id
    original_transition = repository._transition_knowledge

    def transition_then_fail(*args, **kwargs):
        original_transition(*args, **kwargs)
        raise sqlite3.OperationalError("injected")

    monkeypatch.setattr(repository, "_transition_knowledge", transition_then_fail)

    with pytest.raises(sqlite3.OperationalError, match="injected"):
        KnowledgeService(repository, adoption_service=service).accept(
            candidate_id, actor="user"
        )

    assert repository.knowledge_versions(original_id)[-1].version == 1
    assert (
        repository.get_candidate(candidate_id).status is CandidateStatus.PENDING_REVIEW
    )
    assert repository.get_vault_adoption(candidate_id).status == "pending_review"
    assert repository.get_managed_file_state(target) == baseline


def test_vault_drift_after_accept_is_projection_conflict_not_baseline_adoption(
    tmp_path: Path,
) -> None:
    repository, service, vault, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    candidate_id = service.reconcile(
        service.find_external_edits("NPKI")[0].id,
        "adopt_vault",
        actor="user",
    ).candidate_id
    accepted = KnowledgeService(repository, adoption_service=service).accept(
        candidate_id, actor="user"
    )
    accepted_baseline = repository.get_managed_file_state(target)
    target.write_text("later external edit", encoding="utf-8")
    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        service.sync,
    )

    result = coordinator.after_commit("manual_accept", accepted.id, accepted.project_id)

    assert result.status.value == "sync_pending"
    assert result.reason == "external_edit_conflict"
    assert repository.get_managed_file_state(target) == accepted_baseline
    assert accepted_baseline.full_hash != sha256_bytes(target.read_bytes())


def test_keep_database_only_creates_replacement_preview_until_apply(
    tmp_path: Path,
) -> None:
    _, service, _, target = _synchronize_rule(tmp_path)
    original = target.read_bytes()
    edited = original.replace("数据库规则".encode(), "手工规则".encode())
    target.write_bytes(edited)
    conflict = service.find_external_edits("NPKI")[0]

    result = service.reconcile(conflict.id, "keep_database", actor="user")
    preview = service.preview(result.plan_id)

    assert result.status == "preview_required"
    assert target.read_bytes() == edited
    assert preview.targets[0].path == Path("项目/NPKI/AgentRetro/规则.md")
    assert "-手工规则" in preview.targets[0].unified_diff
    assert "+数据库规则" in preview.targets[0].unified_diff

    applied = service.apply(result.plan_id, confirmed=True)
    assert applied.status == "synced"
    assert target.read_bytes() == original


def test_keep_database_plan_is_stale_when_authoritative_knowledge_changes(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    original = target.read_bytes()
    target.write_bytes(original.replace("数据库规则".encode(), "手工规则".encode()))
    conflict = service.find_external_edits("NPKI")[0]
    plan_id = service.reconcile(conflict.id, "keep_database", actor="user").plan_id
    active = repository.list_project_knowledge("NPKI")[0]
    repository.archive_knowledge(active.id, "user")

    with pytest.raises(StalePlanError):
        service.apply(plan_id, confirmed=True)

    assert "手工规则" in target.read_text(encoding="utf-8")


def test_reconciliation_is_stale_when_database_changes_before_choice(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    conflict = service.find_external_edits("NPKI")[0]
    active = repository.list_project_knowledge("NPKI")[0]
    repository.archive_knowledge(active.id, "user")

    with pytest.raises(StalePlanError):
        service.reconcile(conflict.id, "keep_database", actor="user")

    assert "手工规则" in target.read_text(encoding="utf-8")


def test_manual_edit_leaves_both_sides_unchanged_and_records_awaiting_input(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    before = target.read_bytes()
    conflict = service.find_external_edits("NPKI")[0]

    result = service.reconcile(conflict.id, "manual_edit", actor="user")

    assert result.status == "awaiting_user_input"
    assert target.read_bytes() == before
    assert repository.get_sync_job(conflict.id).status == "awaiting_user_input"


def test_successful_sync_persists_verifiable_snapshots_for_every_managed_target(
    tmp_path: Path,
) -> None:
    repository, _, vault = _synchronize_all_targets(tmp_path)
    states = repository.list_managed_file_states("NPKI")
    snapshots = [repository.get_managed_file_snapshot(item.path) for item in states]

    assert all(item is not None for item in snapshots)
    by_name = {item.path.name: item for item in snapshots}
    assert by_name["规则.md"].snapshot_kind == "full"
    assert by_name["变更日志.md"].snapshot_kind == "full"
    assert len(by_name["变更日志.md"].owned_bytes) > 0
    assert by_name["项目_NPKI.md"].snapshot_kind == "managed_block"
    assert by_name["项目索引.md"].snapshot_kind == "managed_block"
    assert b"summary outside" not in by_name["项目_NPKI.md"].owned_bytes
    assert b"index outside" not in by_name["项目索引.md"].owned_bytes
    assert all(str(item.path).startswith(str(vault)) for item in snapshots)


def test_log_snapshot_is_stable_across_synced_event_retry(tmp_path: Path) -> None:
    repository, service, vault = _synchronize_all_targets(tmp_path)
    log = vault / "项目" / "NPKI" / "AgentRetro" / "变更日志.md"
    before = repository.get_managed_file_snapshot(log)
    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        service.sync,
    )

    result = coordinator.retry(before.event_id)

    assert result.status.value == "synced"
    assert repository.get_managed_file_snapshot(log) == before


def test_snapshot_finalize_failure_rolls_back_snapshot_and_synced_status(
    tmp_path: Path, monkeypatch
) -> None:
    repository, service, vault, _ = _synchronize_rule(tmp_path)
    summary = vault / "项目" / "NPKI" / "项目_NPKI.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        "outside\n<!-- agentretro:summary:start project=NPKI -->\nold\n"
        "<!-- agentretro:summary:end -->\n",
        encoding="utf-8",
    )
    original_append = repository._append_audit_record

    def fail_completed(connection, entry) -> None:
        if entry.action == "sync_completed":
            raise sqlite3.OperationalError("injected snapshot finalize failure")
        original_append(connection, entry)

    monkeypatch.setattr(repository, "_append_audit_record", fail_completed)
    coordinator = ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, tmp_path / "backups"),
        service.sync,
    )
    knowledge = repository.list_project_knowledge("NPKI")[0]

    result = coordinator.after_commit("snapshot-failure", knowledge.id, "NPKI")

    assert result.status.value == "sync_pending"
    assert result.reason == "journal_update_failed"
    assert repository.get_managed_file_snapshot(summary) is None
    assert repository.get_projection_event(result.event_id).status.value != "synced"


def test_log_keep_database_uses_nonempty_snapshot(tmp_path: Path) -> None:
    repository, service, vault = _synchronize_all_targets(tmp_path)
    log = vault / "项目" / "NPKI" / "AgentRetro" / "变更日志.md"
    snapshot = repository.get_managed_file_snapshot(log)
    assert snapshot.owned_bytes
    log.write_bytes(b"external log edit\n")
    conflict = next(
        item
        for item in service.find_external_edits("NPKI")
        if item.path.name == log.name
    )

    result = service.reconcile(conflict.id, "keep_database", actor="user")
    preview = service.preview(result.plan_id)

    assert preview.targets[0].output_bytes == snapshot.owned_bytes
    assert preview.targets[0].output_bytes != b""
    assert service.apply(result.plan_id, confirmed=True).status == "synced"
    assert log.read_bytes() == snapshot.owned_bytes


def test_summary_keep_database_preserves_current_outside_prose_and_payload_omits_it(
    tmp_path: Path,
) -> None:
    repository, service, vault = _synchronize_all_targets(tmp_path)
    summary = vault / "项目" / "NPKI" / "项目_NPKI.md"
    content = summary.read_bytes()
    content = content.replace(b"summary outside", b"new outside prose")
    content = content.replace(
        b"- \xe8\xa7\x84\xe5\x88\x99: 1", b"- \xe8\xa7\x84\xe5\x88\x99: 999"
    )
    summary.write_bytes(content)
    conflict = next(
        item
        for item in service.find_external_edits("NPKI")
        if item.path.name == summary.name
    )
    job = repository.get_sync_job(conflict.id)

    assert "new outside prose" not in job.plan_json
    payload = json.loads(job.plan_json)
    assert b"new outside prose" not in base64.b64decode(payload["vault_base64"])
    result = service.reconcile(conflict.id, "keep_database", actor="user")
    preview = service.preview(result.plan_id)

    assert b"new outside prose" in preview.targets[0].output_bytes
    assert b"summary footer" in preview.targets[0].output_bytes
    assert b"999" not in preview.targets[0].output_bytes
    assert service.apply(result.plan_id, confirmed=True).status == "synced"
    assert b"new outside prose" in summary.read_bytes()


@pytest.mark.parametrize("name", ["项目_NPKI.md", "项目索引.md", "变更日志.md"])
def test_adopt_vault_is_typed_unsupported_for_nonaggregate_targets(
    tmp_path: Path, name: str
) -> None:
    repository, service, vault = _synchronize_all_targets(tmp_path)
    target = next(path for path in vault.rglob(name))
    if name == "项目索引.md":
        target.write_bytes(
            target.read_bytes().replace(
                "[[项目/NPKI]]".encode(), "[[项目/OTHER]]".encode()
            )
        )
    elif name == "项目_NPKI.md":
        target.write_bytes(
            target.read_bytes().replace("- 规则: 1".encode(), "- 规则: 999".encode())
        )
    else:
        target.write_bytes(target.read_bytes() + b"external\n")
    conflict = next(
        item for item in service.find_external_edits("NPKI") if item.path.name == name
    )
    before_candidates = len(repository.list_candidates(CandidateStatus.PENDING_REVIEW))

    with pytest.raises(ValueError, match="vault_adoption_unsupported_target"):
        service.reconcile(conflict.id, "adopt_vault", actor="user")

    assert (
        len(repository.list_candidates(CandidateStatus.PENDING_REVIEW))
        == before_candidates
    )
    assert target.exists()


def test_legacy_managed_state_without_snapshot_is_diagnostic_and_zero_write(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    with repository.transaction() as connection:
        connection.execute(
            "DELETE FROM managed_file_snapshots WHERE path = ?", (str(target),)
        )
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )

    diagnostics = service.find_external_edits("NPKI")

    assert len(diagnostics) == 1
    assert diagnostics[0].status == "managed_snapshot_unavailable"
    assert repository.get_sync_job(diagnostics[0].id) is None
    for action in ("keep_database", "adopt_vault"):
        with pytest.raises(ValueError, match="managed_snapshot_unavailable"):
            service.reconcile(diagnostics[0].id, action, actor="user")


def test_reconciliation_payload_tampering_fails_before_plan_or_vault_write(
    tmp_path: Path,
) -> None:
    repository, service, _, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    before = target.read_bytes()
    conflict = service.find_external_edits("NPKI")[0]
    stored = repository.get_sync_job(conflict.id)
    payload = json.loads(stored.plan_json)
    payload["database_base64"] = "Zm9yZ2Vk"
    with repository.transaction() as connection:
        connection.execute(
            "UPDATE sync_jobs SET plan_json = ? WHERE id = ?",
            (
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                conflict.id,
            ),
        )

    with pytest.raises(MergeIntegrityError):
        service.reconcile(conflict.id, "keep_database", actor="user")

    assert target.read_bytes() == before
    with repository.transaction() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sync_jobs WHERE id LIKE 'merge-%'"
            ).fetchone()[0]
            == 0
        )


def test_create_plan_is_immutable_persistent_complete_and_does_not_write_vault(
    tmp_path: Path,
) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "notes" / "guide.md"
    target.parent.mkdir()
    target.write_text("before\n", encoding="utf-8")
    delete = vault / "notes" / "old.md"
    delete.write_text("old\n", encoding="utf-8")
    source = vault / "notes" / "move.md"
    source.write_text("move\n", encoding="utf-8")
    before_target = target.read_bytes()

    plan = service.create_plan(
        "NPKI",
        replacements={Path("notes/guide.md"): b"after\n"},
        deletes=(Path("notes/old.md"),),
        renames=((Path("notes/move.md"), Path("notes/moved.md")),),
        conflicts=("needs human choice",),
    )

    assert target.read_bytes() == before_target
    assert delete.exists() and source.exists()
    assert plan == service.preview(plan.id)
    assert plan.targets[0].input_hash == sha256_bytes(before_target)
    assert plan.targets[0].output_bytes == b"after\n"
    assert "-before" in plan.targets[0].unified_diff
    assert "+after" in plan.targets[0].unified_diff
    assert all(
        item.operation_id.startswith("merge-op-")
        for item in (*plan.deletes, *plan.renames, *plan.conflicts)
    )
    stored = repository.get_sync_job(plan.id)
    assert stored is not None and stored.status == "planned"
    persisted = json.loads(stored.plan_json)
    assert persisted["id"] == plan.id
    assert persisted["targets"][0]["output_base64"]
    assert not any(str(vault) in value for value in _walk_strings(persisted))


def test_general_apply_does_not_authorize_destructive_operations(
    tmp_path: Path,
) -> None:
    _, service, vault = _service(tmp_path)
    delete = vault / "old.md"
    delete.write_text("old", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={}, deletes=(Path("old.md"),))

    with pytest.raises(ConfirmationRequiredError) as error:
        service.apply(plan.id, confirmed=True)

    assert error.value.missing_operation_ids == (plan.deletes[0].operation_id,)
    assert delete.read_text(encoding="utf-8") == "old"


def test_direct_merge_executor_requires_exact_persisted_confirmations(
    tmp_path: Path,
) -> None:
    _, service, vault = _service(tmp_path)
    delete = vault / "old.md"
    delete.write_text("old", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={}, deletes=(Path("old.md"),))
    operation_id = plan.deletes[0].operation_id

    with pytest.raises(ValueError, match="merge_operation_confirmation_required"):
        service.sync.apply_confirmed_merge(plan.id, confirmed_operations=())
    with pytest.raises(ValueError, match="unknown_merge_operation_confirmation"):
        service.sync.apply_confirmed_merge(
            plan.id,
            confirmed_operations=(operation_id, "merge-op-forged"),
        )

    assert delete.read_text(encoding="utf-8") == "old"
    result = service.sync.apply_confirmed_merge(
        plan.id, confirmed_operations=(operation_id,)
    )
    assert result.status.value == "synced"
    assert not delete.exists()


def test_exact_confirmations_apply_delete_rename_and_acknowledged_conflict(
    tmp_path: Path,
) -> None:
    _, service, vault = _service(tmp_path)
    delete = vault / "old.md"
    delete.write_text("old", encoding="utf-8")
    source = vault / "source.md"
    source.write_text("move", encoding="utf-8")
    plan = service.create_plan(
        "NPKI",
        replacements={},
        deletes=(Path("old.md"),),
        renames=((Path("source.md"), Path("target.md")),),
        conflicts=("reviewed manually",),
    )
    confirmations = tuple(
        item.operation_id for item in (*plan.deletes, *plan.renames, *plan.conflicts)
    )

    result = service.apply(
        plan.id,
        confirmed=True,
        confirmed_operations=confirmations,
    )

    assert result.status == "synced"
    assert not delete.exists() and not source.exists()
    assert (vault / "target.md").read_text(encoding="utf-8") == "move"


def test_stale_merge_plan_cannot_apply_and_writes_nothing(tmp_path: Path) -> None:
    _, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"planned"})
    target.write_text("newer user edit", encoding="utf-8")

    with pytest.raises(StalePlanError):
        service.apply(plan.id, confirmed=True)

    assert target.read_text(encoding="utf-8") == "newer user edit"


def test_missing_target_and_rename_destination_drift_are_stale(
    tmp_path: Path,
) -> None:
    _, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    missing_plan = service.create_plan(
        "NPKI", replacements={Path("guide.md"): b"after"}
    )
    target.unlink()

    with pytest.raises(StalePlanError):
        service.apply(missing_plan.id, confirmed=True)

    source = vault / "source.md"
    destination = vault / "destination.md"
    source.write_text("source", encoding="utf-8")
    rename_plan = service.create_plan(
        "NPKI",
        replacements={},
        renames=((Path("source.md"), Path("destination.md")),),
    )
    destination.write_text("new user file", encoding="utf-8")

    with pytest.raises(StalePlanError):
        service.apply(
            rename_plan.id,
            confirmed=True,
            confirmed_operations=(rename_plan.renames[0].operation_id,),
        )

    assert source.exists()
    assert destination.read_text(encoding="utf-8") == "new user file"


def test_missing_target_becoming_empty_file_is_stale(tmp_path: Path) -> None:
    _, service, vault = _service(tmp_path)
    target = vault / "new.md"
    plan = service.create_plan("NPKI", replacements={Path("new.md"): b"planned"})
    target.write_bytes(b"")

    with pytest.raises(StalePlanError):
        service.apply(plan.id, confirmed=True)

    assert target.read_bytes() == b""


def test_file_type_change_is_stale(tmp_path: Path) -> None:
    _, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})
    target.unlink()
    target.mkdir()

    with pytest.raises(StalePlanError):
        service.apply(plan.id, confirmed=True)

    assert target.is_dir()


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (Path("foo"), Path("foo.")),
        (Path("A.md"), Path("a.md")),
        (
            Path("caf\N{LATIN SMALL LETTER E WITH ACUTE}.md"),
            Path("cafe\N{COMBINING ACUTE ACCENT}.md"),
        ),
    ],
)
def test_windows_compatible_path_aliases_are_rejected(
    tmp_path: Path, first: Path, second: Path
) -> None:
    _, service, vault = _service(tmp_path)
    (vault / first).write_bytes(b"one")

    with pytest.raises((MergeIntegrityError, ValueError)):
        service.create_plan("NPKI", replacements={second: b"two"}, deletes=(first,))

    assert (vault / first).read_bytes() == b"one"


@pytest.mark.parametrize(
    "path",
    [Path("CON.md"), Path("note.md:stream"), Path("trailing "), Path("LPT1")],
)
def test_windows_invalid_merge_paths_are_rejected(tmp_path: Path, path: Path) -> None:
    _, service, vault = _service(tmp_path)

    with pytest.raises(ValueError, match="merge_target_windows_incompatible"):
        service.create_plan("NPKI", replacements={path: b"bad"})

    assert not (vault / path).exists()


def test_drift_after_backup_is_stale_before_journal_or_vault_write(
    tmp_path: Path, monkeypatch
) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})
    original_backup = service.sync._backup_snapshots

    def backup_then_edit(backup_dir, snapshots) -> None:
        original_backup(backup_dir, snapshots)
        target.write_text("external", encoding="utf-8")

    monkeypatch.setattr(service.sync, "_backup_snapshots", backup_then_edit)

    with pytest.raises(StalePlanError):
        service.apply(plan.id, confirmed=True)

    assert target.read_text(encoding="utf-8") == "external"
    assert repository.get_sync_job(plan.id).status == "planned"


def test_later_target_drift_rolls_back_only_batch_changed_paths(tmp_path: Path) -> None:
    calls = 0
    second: Path

    def edit_second_after_first(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        os.replace(source, target)
        if calls == 1:
            second.write_text("external-second", encoding="utf-8")

    _, service, vault = _service(tmp_path, replace=edit_second_after_first)
    first = vault / "one.md"
    second = vault / "two.md"
    first.write_text("one-before", encoding="utf-8")
    second.write_text("two-before", encoding="utf-8")
    plan = service.create_plan(
        "NPKI",
        replacements={Path("one.md"): b"one-after", Path("two.md"): b"two-after"},
    )

    result = service.apply(plan.id, confirmed=True)

    assert result.status == "sync_pending"
    assert result.reason == "merge_plan_stale"
    assert first.read_text(encoding="utf-8") == "one-before"
    assert second.read_text(encoding="utf-8") == "external-second"


def test_plan_tampering_fails_closed_before_vault_write(tmp_path: Path) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})
    stored = repository.get_sync_job(plan.id)
    encoded = json.loads(stored.plan_json)["targets"][0]["output_base64"]
    with repository.transaction() as connection:
        connection.execute(
            "UPDATE sync_jobs SET plan_json = replace(plan_json, ?, ?) WHERE id = ?",
            (encoded, "ZXZpbA==", plan.id),
        )

    with pytest.raises(MergeIntegrityError):
        service.apply(plan.id, confirmed=True)

    assert target.read_text(encoding="utf-8") == "before"


def test_extra_persisted_target_and_unknown_confirmation_fail_closed(
    tmp_path: Path,
) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})
    with pytest.raises(MergeIntegrityError):
        service.apply(
            plan.id,
            confirmed=True,
            confirmed_operations=("merge-op-forged",),
        )
    assert target.read_text(encoding="utf-8") == "before"

    stored = repository.get_sync_job(plan.id)
    data = json.loads(stored.plan_json)
    data["targets"].append(
        {
            "path": "extra-prose.md",
            "input_hash": sha256_bytes(b""),
            "output_base64": "Zm9yZ2Vk",
            "unified_diff": "forged",
        }
    )
    with repository.transaction() as connection:
        connection.execute(
            "UPDATE sync_jobs SET plan_json = ? WHERE id = ?",
            (
                json.dumps(
                    data,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                plan.id,
            ),
        )

    with pytest.raises(MergeIntegrityError):
        service.apply(plan.id, confirmed=True)

    assert not (vault / "extra-prose.md").exists()
    assert target.read_text(encoding="utf-8") == "before"


@pytest.mark.parametrize(
    "target",
    [Path("../escape.md"), Path("项目/OTHER/prose.md")],
)
def test_cross_boundary_or_cross_project_target_is_rejected(
    tmp_path: Path, target: Path
) -> None:
    _, service, vault = _service(tmp_path)

    with pytest.raises(ValueError):
        service.create_plan("NPKI", replacements={target: b"bad"})

    assert not (tmp_path / "escape.md").exists()
    assert not (vault / "项目" / "OTHER" / "prose.md").exists()


def test_symlink_introduced_after_preview_is_typed_stale_and_zero_write(
    tmp_path: Path,
) -> None:
    _, service, vault = _service(tmp_path)
    plan = service.create_plan("NPKI", replacements={Path("linked/guide.md"): b"after"})
    external = tmp_path / "external"
    external.mkdir()
    link = vault / "linked"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")

    with pytest.raises(StalePlanError):
        service.apply(plan.id, confirmed=True)

    assert not (external / "guide.md").exists()


def test_repeated_apply_is_idempotent(tmp_path: Path) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})

    first = service.apply(plan.id, confirmed=True)
    second = service.apply(plan.id, confirmed=True)

    assert first.status == "synced"
    assert second.status == "already_applied"
    assert target.read_bytes() == b"after"
    assert repository.get_sync_job(plan.id).status == "synced"


def test_partial_merge_write_failure_rolls_back_every_target(tmp_path: Path) -> None:
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sensitive absolute failure detail")
        os.replace(source, target)

    repository, service, vault = _service(tmp_path, replace=fail_second)
    one = vault / "one.md"
    two = vault / "two.md"
    one.write_text("one-before", encoding="utf-8")
    two.write_text("two-before", encoding="utf-8")
    plan = service.create_plan(
        "NPKI",
        replacements={Path("one.md"): b"one-after", Path("two.md"): b"two-after"},
    )

    result = service.apply(plan.id, confirmed=True)

    assert result.status == "sync_pending"
    assert result.reason == "write_failed"
    assert one.read_text(encoding="utf-8") == "one-before"
    assert two.read_text(encoding="utf-8") == "two-before"
    assert "sensitive" not in repository.get_sync_job(plan.id).error

    retried = service.apply(plan.id, confirmed=True)
    assert retried.status == "synced"
    assert one.read_bytes() == b"one-after"
    assert two.read_bytes() == b"two-after"


def test_concurrent_apply_executes_plan_once(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    replace_count = 0
    count_lock = threading.Lock()

    def controlled_replace(source: Path, target: Path) -> None:
        nonlocal replace_count
        with count_lock:
            replace_count += 1
            current = replace_count
        if current == 1:
            entered.set()
            assert release.wait(5)
        os.replace(source, target)

    _, service, vault = _service(tmp_path, replace=controlled_replace)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})
    results = []

    def apply() -> None:
        results.append(service.apply(plan.id, confirmed=True))

    first = threading.Thread(target=apply)
    second = threading.Thread(target=apply)
    first.start()
    assert entered.wait(5)
    second.start()
    release.set()
    first.join(5)
    second.join(5)

    assert sorted(result.status for result in results) == ["already_applied", "synced"]
    assert replace_count == 1
    assert target.read_bytes() == b"after"


def test_merge_journal_start_failure_is_typed_and_writes_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})

    def fail_begin(job) -> None:
        raise sqlite3.OperationalError("secret C:/private/retro.db")

    monkeypatch.setattr(repository, "begin_sync", fail_begin)

    with pytest.raises(ProjectionPersistenceError) as error:
        service.apply(plan.id, confirmed=True)

    assert error.value.reason == "journal_start_failed"
    assert target.read_text(encoding="utf-8") == "before"
    assert "private" not in str(error.value)


def test_merge_plan_read_failure_is_typed_and_writes_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})

    def fail_read(job_id):
        raise sqlite3.OperationalError("secret C:/private/retro.db")

    monkeypatch.setattr(repository, "get_sync_job", fail_read)

    with pytest.raises(ProjectionPersistenceError) as error:
        service.apply(plan.id, confirmed=True)

    assert error.value.reason == "merge_state_unavailable"
    assert target.read_text(encoding="utf-8") == "before"
    assert "private" not in str(error.value)


def test_merge_journal_finish_failure_restores_and_is_sanitized(
    tmp_path: Path, monkeypatch
) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})

    def fail_finish(*args, **kwargs) -> None:
        raise sqlite3.OperationalError("secret C:/private/retro.db")

    monkeypatch.setattr(repository, "finish_sync", fail_finish)

    with pytest.raises(ProjectionPersistenceError) as error:
        service.apply(plan.id, confirmed=True)

    assert error.value.reason == "journal_update_failed"
    assert target.read_text(encoding="utf-8") == "before"
    assert "private" not in str(error.value)


def test_merge_readback_failure_rolls_back(tmp_path: Path) -> None:
    calls = 0

    def corrupt_first(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        os.replace(source, target)
        if calls == 1:
            target.write_bytes(b"corrupt")

    _, service, vault = _service(tmp_path, replace=corrupt_first)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})

    result = service.apply(plan.id, confirmed=True)

    assert result.status == "sync_pending"
    assert result.reason == "write_failed"
    assert target.read_text(encoding="utf-8") == "before"


def test_merge_rollback_failure_blocks_later_apply(tmp_path: Path) -> None:
    def always_fail(source: Path, target: Path) -> None:
        raise OSError("replace failed")

    repository, service, vault = _service(tmp_path, replace=always_fail)
    target = vault / "guide.md"
    target.write_text("before", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={Path("guide.md"): b"after"})

    first = service.apply(plan.id, confirmed=True)
    second = service.apply(plan.id, confirmed=True)

    assert first.status == "rollback_required"
    assert first.reason == "rollback_failed"
    assert second.status == "rollback_required"
    assert second.reason == "rollback_blocked"
    assert repository.get_sync_job(plan.id).status == "rollback_required"
    assert target.read_text(encoding="utf-8") == "before"


def test_cli_merge_preview_and_exact_apply_use_relative_safe_output(
    tmp_path: Path, capsys
) -> None:
    repository, service, vault = _service(tmp_path)
    target = vault / "old.md"
    target.write_text("old", encoding="utf-8")
    plan = service.create_plan("NPKI", replacements={}, deletes=(Path("old.md"),))
    env = {
        "AGENTRETRO_HOME": str(tmp_path),
        "AGENTRETRO_DB_PATH": str(repository.db_path),
        "AGENTRETRO_BACKUP_DIR": str(tmp_path / "backups"),
        "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
    }

    assert main(["--json", "merge", "preview", plan.id], home=tmp_path, env=env) == 0
    preview_text = capsys.readouterr().out
    preview = json.loads(preview_text)
    assert preview["code"] == "RETRO_MERGE_PREVIEW"
    assert preview["data"]["deletes"][0]["path"] == "old.md"
    assert str(tmp_path) not in preview_text

    assert (
        main(["--json", "merge", "apply", plan.id, "--apply"], home=tmp_path, env=env)
        == 2
    )
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["code"] == "RETRO_MERGE_CONFIRMATION_REQUIRED"
    assert blocked["data"]["missing_operation_ids"] == [plan.deletes[0].operation_id]
    assert target.exists()

    assert (
        main(
            [
                "--json",
                "merge",
                "apply",
                plan.id,
                "--apply",
                "--confirm-operation",
                plan.deletes[0].operation_id,
            ],
            home=tmp_path,
            env=env,
        )
        == 0
    )
    applied = json.loads(capsys.readouterr().out)
    assert applied["code"] == "RETRO_MERGE_APPLIED"
    assert not target.exists()


def test_cli_reconciliation_action_records_awaiting_input(
    tmp_path: Path, capsys
) -> None:
    repository, service, vault, target = _synchronize_rule(tmp_path)
    target.write_text(
        target.read_text(encoding="utf-8").replace("数据库规则", "手工规则"),
        encoding="utf-8",
    )
    conflict = service.find_external_edits("NPKI")[0]
    env = {
        "AGENTRETRO_HOME": str(tmp_path),
        "AGENTRETRO_DB_PATH": str(repository.db_path),
        "AGENTRETRO_BACKUP_DIR": str(tmp_path / "backups"),
        "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
    }

    result = main(
        [
            "--json",
            "sync",
            "reconcile",
            conflict.id,
            "--action",
            "manual_edit",
        ],
        home=tmp_path,
        env=env,
    )
    output = json.loads(capsys.readouterr().out)

    assert result == 0
    assert output["code"] == "RETRO_SYNC_RECONCILED"
    assert output["data"]["status"] == "awaiting_user_input"
    assert str(tmp_path) not in json.dumps(output)


def _walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
