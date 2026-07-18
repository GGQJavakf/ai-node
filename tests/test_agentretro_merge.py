from __future__ import annotations

import json
import os
import sqlite3
import threading
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
from agent_retro.application.sync import SyncService
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

    # Seed a canonical projection directly through the same immutable renderer,
    # then record the last synchronized hashes as Task 5 does.
    plan = ObsidianProjection(vault, tmp_path / "backups").plan("NPKI", [item])
    for write in plan.writes:
        write.target.parent.mkdir(parents=True, exist_ok=True)
        write.target.write_bytes(write.after_bytes)
        repository.save_managed_file_state(
            "NPKI",
            write.target,
            write.after_managed_hash,
            sha256_bytes(write.after_bytes),
        )
    target = vault / "项目" / "NPKI" / "AgentRetro" / "规则.md"
    return repository, service, vault, target


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
