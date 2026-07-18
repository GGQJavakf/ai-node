from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.purge import (
    IncompletePurgeConfirmation,
    KnowledgeAlreadyPurged,
    KnowledgeSyncPending,
    PurgeAlreadyComplete,
    PurgeBlockedError,
    PurgeKnowledgeNotFound,
    PurgeProjectionResult,
    PurgeRecoveryNotFound,
    PurgeRecoveryNotIncomplete,
    PurgeService,
    StalePurgePlan,
    UnsafePurgeRegistration,
)
from agent_retro.application.brief import BriefRequest, BriefService
from agent_retro.application.merge import MergeService
from agent_retro.application.sync import (
    ProjectionCoordinator,
    ProjectionPersistenceError,
    ProjectionResult,
    SyncService,
)
from agent_retro.domain.models import ProjectionStatus, PurgeStatus
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation import cli as retro_cli


MARKER = "agentretro-secret-6c25d4e9"
KNOWLEDGE_ID = "knowledge-purge-a"
PROJECT_ID = "project-a"


class _FailingPurgeRepository(SQLiteRetroRepository):
    fail_purge_audit = False

    def _append_audit_record(self, connection, entry):
        if self.fail_purge_audit and entry.action == "purge_started":
            raise OSError("injected purge transaction failure")
        return super()._append_audit_record(connection, entry)


def _insert_knowledge(repository: SQLiteRetroRepository) -> None:
    now = "2026-07-18T00:00:00+00:00"
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "session-a",
                "source-a",
                "redacted",
                "source-hash",
                PROJECT_ID,
                "completed",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evidence-a",
                "session-a",
                "fact",
                "source-a",
                "event-a",
                "redacted",
                "evidence-hash",
                f"evidence {MARKER}",
            ),
        )
        connection.execute(
            "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "candidate-a",
                "session-a",
                "RULE",
                PROJECT_ID,
                "project",
                MARKER,
                "accepted",
                0.99,
                json.dumps({"reason": MARKER}),
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO candidate_evidence VALUES (?, ?)",
            ("candidate-a", "evidence-a"),
        )
        connection.execute(
            "INSERT INTO knowledge VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                KNOWLEDGE_ID,
                1,
                "candidate-a",
                "RULE",
                PROJECT_ID,
                "project",
                MARKER,
                "active",
                0.99,
                "user",
                None,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO knowledge_evidence VALUES (?, ?, ?)",
            (KNOWLEDGE_ID, 1, "evidence-a"),
        )
        connection.execute(
            "INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "audit-a",
                "user",
                "accepted",
                "knowledge",
                KNOWLEDGE_ID,
                "",
                "",
                json.dumps({"detail": MARKER}),
                now,
            ),
        )
        connection.execute(
            "INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "audit-unrelated",
                "user",
                "keep",
                "knowledge",
                "knowledge-unrelated",
                "",
                "",
                '{"detail":"keep"}',
                now,
            ),
        )
        connection.execute(
            "INSERT INTO review_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "review-a",
                "candidate-a",
                "input-hash",
                1,
                "completed",
                json.dumps({"result": MARKER}),
                f"error {MARKER}",
                now,
            ),
        )
        connection.execute(
            "INSERT INTO conflicts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "conflict-a",
                KNOWLEDGE_ID,
                "candidate-a",
                f"reason {MARKER}",
                f"merge {MARKER}",
                "open",
                now,
                None,
            ),
        )
        connection.execute(
            "INSERT INTO sync_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "sync-a",
                PROJECT_ID,
                "synced",
                json.dumps({"payload": MARKER}),
                "redacted",
                f"error {MARKER}",
                now,
                now,
            ),
        )


@pytest.fixture
def purge_fixture(tmp_path: Path):
    state = tmp_path / "state"
    repository = SQLiteRetroRepository(state / "retro.db", state / "backups")
    repository.migrate()
    _insert_knowledge(repository)

    vault = tmp_path / "vault"
    managed = vault / "项目" / PROJECT_ID / "AgentRetro" / "规则.md"
    managed.parent.mkdir(parents=True)
    managed.write_text(f"managed {MARKER}\n", encoding="utf-8")
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO managed_file_state VALUES (?, ?, ?, ?, ?)",
            (
                str(managed),
                PROJECT_ID,
                "managed-hash",
                "full-hash",
                "2026-07-18T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO managed_file_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(managed),
                PROJECT_ID,
                "full",
                f"snapshot {MARKER}".encode(),
                "managed-hash",
                "full-hash",
                "event-a",
                "2026-07-18T00:00:00+00:00",
            ),
        )

    sync_root = state / "backups" / "sync"
    sync_copy = sync_root / "copy.md"
    sync_copy.parent.mkdir(parents=True)
    sync_copy.write_text(f"backup {MARKER}\n", encoding="utf-8")
    unrelated = sync_root / "unrelated.md"
    unrelated.write_text("keep me\n", encoding="utf-8")
    outside = tmp_path / "unregistered-secret.txt"
    outside.write_text(MARKER, encoding="utf-8")
    migration_root = state / "backups" / "migration"
    migration_root.mkdir(parents=True)
    (migration_root / "copy.db").write_text(MARKER, encoding="utf-8")
    merge_root = state / "backups" / "merge"
    merge_root.mkdir(parents=True)
    (merge_root / "copy.md").write_text(MARKER, encoding="utf-8")
    log = state / "logs" / "agentretro.log"
    log.parent.mkdir(parents=True)
    log.write_text(f"log {MARKER}\n", encoding="utf-8")
    trace = state / "traces" / "review.json"
    trace.parent.mkdir(parents=True)
    trace.write_text(json.dumps({"result": MARKER}), encoding="utf-8")

    service = PurgeService(
        repository,
        vault_root=vault,
        backup_roots={
            "sync_backup": sync_root,
            "migration_backup": migration_root,
            "merge_backup": merge_root,
        },
        log_paths=(log,),
        trace_paths=(trace,),
    )
    return repository, service, managed, sync_copy, unrelated, log, trace


def _snapshot(
    root: Path, repository: SQLiteRetroRepository
) -> tuple[bytes, tuple[tuple[str, bytes], ...]]:
    rows = repository.db_path.read_bytes()
    files = tuple(
        (str(path.relative_to(root)), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and path != repository.db_path
    )
    return rows, files


def _table_rows(repository: SQLiteRetroRepository, table: str):
    with sqlite3.connect(repository.db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def _database_rows(repository: SQLiteRetroRepository):
    with sqlite3.connect(repository.db_path) as connection:
        connection.row_factory = sqlite3.Row
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        return {
            table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in tables
        }


def test_plan_is_read_only_complete_redacted_and_deterministic(
    purge_fixture, tmp_path: Path
):
    repository, service, managed, sync_copy, unrelated, log, trace = purge_fixture
    before = _snapshot(tmp_path, repository)

    first = service.plan(KNOWLEDGE_ID)
    second = service.plan(KNOWLEDGE_ID)

    assert first == second
    assert _snapshot(tmp_path, repository) == before
    assert len(first.operations) == 18
    kinds = {operation.location_kind for operation in first.operations}
    assert {
        "sqlite_knowledge",
        "sqlite_candidate",
        "sqlite_evidence",
        "sqlite_review",
        "sqlite_conflict",
        "sqlite_projection",
        "sqlite_audit",
    } <= kinds
    assert {
        "managed_vault",
        "sync_backup",
        "migration_backup",
        "merge_backup",
        "agentretro_log",
        "model_trace",
    } <= kinds
    assert all(MARKER not in operation.location for operation in first.operations)
    assert all(
        not Path(operation.location).is_absolute() for operation in first.operations
    )
    assert unrelated.read_text(encoding="utf-8") == "keep me\n"
    assert {managed, sync_copy, log, trace}
    for operation in first.operations:
        assert (
            operation.id
            == hashlib.sha256(
                (
                    first.id
                    + operation.location_kind
                    + operation.location
                    + operation.expected_hash
                ).encode()
            ).hexdigest()
        )


def test_plan_refuses_missing_already_purged_and_sync_pending(purge_fixture):
    repository, service, *_ = purge_fixture
    with pytest.raises(PurgeKnowledgeNotFound):
        service.plan("missing")

    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO purge_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "old-purge",
                KNOWLEDGE_ID,
                "",
                "purged",
                "{}",
                "[]",
                "2026-07-18T00:00:00+00:00",
                "2026-07-18T00:00:00+00:00",
            ),
        )
    with pytest.raises(KnowledgeAlreadyPurged):
        service.plan(KNOWLEDGE_ID)

    with sqlite3.connect(repository.db_path) as connection:
        connection.execute("DELETE FROM purge_jobs")
        connection.execute(
            "INSERT INTO projection_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "event-a",
                PROJECT_ID,
                "accepted",
                KNOWLEDGE_ID,
                "input",
                "sync_pending",
                "",
                "2026-07-18T00:00:00+00:00",
                "2026-07-18T00:00:00+00:00",
            ),
        )
    with pytest.raises(KnowledgeSyncPending):
        service.plan(KNOWLEDGE_ID)


@pytest.mark.parametrize("confirmation", ["missing", "extra", "empty", "wildcard"])
def test_apply_requires_the_exact_confirmation_set_without_writes(
    purge_fixture, tmp_path: Path, confirmation: str
):
    repository, service, *_ = purge_fixture
    plan = service.plan(KNOWLEDGE_ID)
    expected = frozenset(operation.id for operation in plan.operations)
    supplied = {
        "missing": frozenset(tuple(expected)[:-1]),
        "extra": expected | {"unknown-operation"},
        "empty": frozenset(),
        "wildcard": frozenset({"*"}),
    }[confirmation]
    before = _snapshot(tmp_path, repository)

    with pytest.raises(IncompletePurgeConfirmation):
        service.apply(plan.id, supplied)

    assert _snapshot(tmp_path, repository) == before
    assert _table_rows(repository, "purge_jobs") == []


@pytest.mark.parametrize("change", ["planned", "new_registered_residual"])
def test_apply_rebuilds_manifest_and_refuses_stale_state_without_writes(
    purge_fixture, tmp_path: Path, change: str
):
    repository, service, managed, _, unrelated, *_ = purge_fixture
    plan = service.plan(KNOWLEDGE_ID)
    confirmations = frozenset(operation.id for operation in plan.operations)
    if change == "planned":
        managed.write_text(f"changed {MARKER}\n", encoding="utf-8")
    else:
        unrelated.write_text(f"new copy {MARKER}\n", encoding="utf-8")
    before = _snapshot(tmp_path, repository)

    with pytest.raises(StalePurgePlan):
        service.apply(plan.id, confirmations)

    assert _snapshot(tmp_path, repository) == before
    assert _table_rows(repository, "purge_jobs") == []


def test_apply_journals_and_scrubs_sqlite_in_one_stage_without_claiming_purged(
    purge_fixture,
):
    repository, service, *_ = purge_fixture
    plan = service.plan(KNOWLEDGE_ID)

    restarted_service = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
    )
    status = restarted_service.apply(
        plan.id,
        frozenset(operation.id for operation in plan.operations),
        actor="user-a",
    )

    assert status is PurgeStatus.PURGED
    assert _table_rows(repository, "knowledge") == []
    for table, fields in {
        "candidates": ("proposed_text", "review_json"),
        "evidence": ("excerpt",),
        "review_attempts": ("result_json", "error"),
        "conflicts": ("reason", "merge_text"),
        "sync_jobs": ("plan_json", "error"),
        "managed_file_snapshots": ("owned_bytes",),
        "audit_log": ("detail_json",),
    }.items():
        for row in _table_rows(repository, table):
            assert all(MARKER not in str(row[field]) for field in fields)
    assert any(
        row["id"] == "audit-unrelated" and row["detail_json"] == '{"detail":"keep"}'
        for row in _table_rows(repository, "audit_log")
    )
    jobs = _table_rows(repository, "purge_jobs")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "purged"
    tombstone = json.loads(jobs[0]["tombstone_json"])
    assert set(tombstone) == {
        "knowledge_id",
        "actor",
        "started_at",
        "updated_at",
        "status",
        "operation_count",
        "residual_count",
    }
    assert tombstone["status"] == "purged"
    assert tombstone["operation_count"] == len(plan.operations)
    assert MARKER not in json.dumps(tombstone)
    typed_tombstone = repository.get_purge_tombstone(KNOWLEDGE_ID)
    assert typed_tombstone is not None
    assert typed_tombstone.status is PurgeStatus.PURGED
    for forbidden in ("text", "excerpt", "summary", "content_hash", "filename"):
        assert not hasattr(typed_tombstone, forbidden)
    operations = _table_rows(repository, "purge_operations")
    assert operations == []
    for path in service.log_paths + service.trace_paths:
        assert MARKER.encode() not in path.read_bytes()
    for root in service.backup_roots.values():
        for path in root.rglob("*"):
            if path.is_file():
                assert MARKER.encode() not in path.read_bytes()
    for state in repository.list_managed_file_states(PROJECT_ID):
        assert MARKER.encode() not in state.path.read_bytes()
    assert not any(
        row["action"] == "purge_finished"
        for row in _table_rows(repository, "audit_log")
    )
    success = [
        row
        for row in _table_rows(repository, "audit_log")
        if row["action"] == "purge_succeeded"
    ]
    assert len(success) == 1
    assert MARKER not in success[0]["detail_json"]
    assert MARKER.encode() not in repository.db_path.read_bytes()


def test_apply_time_new_registered_residual_prevents_success(purge_fixture):
    repository, service, _, _, unrelated, *_ = purge_fixture
    created = False

    def replace_with_new_residual(source: Path, target: Path) -> None:
        nonlocal created
        source.replace(target)
        if not created:
            created = True
            unrelated.write_text(f"late {MARKER}", encoding="utf-8")

    interrupted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=replace_with_new_residual,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)

    status = interrupted.apply(
        plan.id, frozenset(operation.id for operation in plan.operations)
    )

    assert status is PurgeStatus.PURGE_INCOMPLETE
    assert _table_rows(repository, "purge_jobs")[0]["status"] == "purge_incomplete"
    assert not any(
        row["action"] == "purge_succeeded"
        for row in _table_rows(repository, "audit_log")
    )
    assert MARKER not in _table_rows(repository, "purge_jobs")[0]["residual_json"]


def test_atomic_file_failure_marks_incomplete_without_success(purge_fixture):
    repository, service, *_ = purge_fixture

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected atomic replace failure")

    interrupted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=fail_replace,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)

    status = interrupted.apply(
        plan.id, frozenset(operation.id for operation in plan.operations)
    )

    assert status is PurgeStatus.PURGE_INCOMPLETE
    assert any(
        row["status"] == "failed" for row in _table_rows(repository, "purge_operations")
    )
    assert not any(
        row["action"] == "purge_succeeded"
        for row in _table_rows(repository, "audit_log")
    )


def test_registered_backup_symlink_is_rejected_without_following_it(purge_fixture):
    _, service, *_ = purge_fixture
    root = service.backup_roots["sync_backup"]
    outside = root.parent.parent / "outside-marker.txt"
    outside.write_text(MARKER, encoding="utf-8")
    link = root / "escape.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(UnsafePurgeRegistration):
        service.plan(KNOWLEDGE_ID)

    assert outside.read_text(encoding="utf-8") == MARKER


def test_interrupted_cleanup_recovers_from_persisted_journal_only(purge_fixture):
    repository, service, *_ = purge_fixture
    replace_count = 0

    def fail_second_replace(source: Path, target: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("injected second replace failure")
        source.replace(target)

    interrupted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=fail_second_replace,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)
    assert (
        interrupted.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGE_INCOMPLETE
    )
    before = _table_rows(repository, "purge_operations")
    assert any(row["status"] == "completed" for row in before)
    assert any(row["status"] == "failed" for row in before)

    recovery_writes: list[Path] = []

    def record_replace(source: Path, target: Path) -> None:
        recovery_writes.append(target)
        source.replace(target)

    restarted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=record_replace,
    )
    status = restarted.recover(KNOWLEDGE_ID, actor="recovery-user")

    assert status is PurgeStatus.PURGED
    assert len(recovery_writes) == 1
    after = _table_rows(repository, "purge_operations")
    assert after == []
    assert MARKER.encode() not in repository.db_path.read_bytes()
    assert all(
        MARKER.encode() not in path.read_bytes()
        for path in (*restarted.log_paths, *restarted.trace_paths)
        if path.exists()
    )
    assert all(
        MARKER.encode() not in path.read_bytes()
        for root in restarted.backup_roots.values()
        for path in root.rglob("*")
        if path.is_file()
    )
    brief = BriefService(repository).build(
        BriefRequest(task="post purge", project_id=PROJECT_ID)
    )
    assert KNOWLEDGE_ID not in {item.id for item in brief.items}


def test_recover_rejects_missing_complete_and_non_incomplete_journals(purge_fixture):
    repository, service, *_ = purge_fixture

    with pytest.raises(PurgeRecoveryNotFound):
        service.recover("knowledge-without-journal")

    plan = service.plan(KNOWLEDGE_ID)
    assert (
        service.apply(plan.id, frozenset(operation.id for operation in plan.operations))
        is PurgeStatus.PURGED
    )
    with pytest.raises(PurgeAlreadyComplete):
        service.recover(KNOWLEDGE_ID)

    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE purge_jobs SET status = ? WHERE knowledge_id = ?",
            (PurgeStatus.PURGE_IN_PROGRESS.value, KNOWLEDGE_ID),
        )
    with pytest.raises(PurgeRecoveryNotIncomplete):
        service.recover(KNOWLEDGE_ID)


def test_failed_recovery_remains_incomplete(purge_fixture):
    repository, service, *_ = purge_fixture

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected cleanup failure")

    interrupted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=fail_replace,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)
    assert (
        interrupted.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGE_INCOMPLETE
    )

    assert interrupted.recover(KNOWLEDGE_ID) is PurgeStatus.PURGE_INCOMPLETE
    journal = repository.get_purge_journal(KNOWLEDGE_ID)
    assert journal is not None
    assert journal.status is PurgeStatus.PURGE_INCOMPLETE
    assert any(operation.status == "failed" for operation in journal.operations)


def test_incomplete_purge_blocks_brief_and_projection_before_writes(purge_fixture):
    repository, service, *_ = purge_fixture

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected cleanup failure")

    interrupted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=fail_replace,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)
    assert (
        interrupted.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGE_INCOMPLETE
    )
    events_before = repository.projection_event_count(PROJECT_ID)

    with pytest.raises(PurgeBlockedError, match="purge_incomplete"):
        BriefService(repository).build(
            BriefRequest(task="blocked", project_id=PROJECT_ID)
        )
    with pytest.raises(PurgeBlockedError, match="purge_incomplete"):
        ProjectionCoordinator(repository, None, None).after_commit(
            "blocked", KNOWLEDGE_ID, PROJECT_ID
        )

    assert repository.projection_event_count(PROJECT_ID) == events_before


def test_incomplete_purge_blocks_sync_reconcile_and_merge_entrypoints(
    purge_fixture, monkeypatch
):
    repository, service, *_ = purge_fixture
    vault_root = service.vault_root
    assert vault_root is not None

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected cleanup failure")

    interrupted = PurgeService(
        repository,
        vault_root=vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=fail_replace,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)
    assert (
        interrupted.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGE_INCOMPLETE
    )
    event_id = repository.save_current_projection_event(
        PROJECT_ID, "test-fixture-bypass", KNOWLEDGE_ID
    )

    sync = SyncService(repository, vault_root, vault_root.parent / "sync-backups")
    merge = MergeService(repository, vault_root, vault_root.parent / "merge-backups")
    with pytest.raises(PurgeBlockedError, match="purge_incomplete"):
        sync.synchronize(event_id, None)  # type: ignore[arg-type]
    with pytest.raises(PurgeBlockedError, match="purge_incomplete"):
        merge.find_external_edits(PROJECT_ID)

    monkeypatch.setattr(
        merge, "_load_plan", lambda _: SimpleNamespace(project_id=PROJECT_ID)
    )
    with pytest.raises(PurgeBlockedError, match="purge_incomplete"):
        merge.apply("merge-plan", confirmed=True)

    conflict_id = "reconcile-test"
    payload = json.dumps(
        {"id": conflict_id, "kind": "reconciliation", "project_id": PROJECT_ID},
        separators=(",", ":"),
        sort_keys=True,
    )
    monkeypatch.setattr(merge, "_get_job", lambda _: SimpleNamespace(plan_json=payload))
    with pytest.raises(PurgeBlockedError, match="purge_incomplete"):
        merge.reconcile(conflict_id, "manual_edit", actor="user")


def test_completed_purge_projects_once_after_commit_and_excludes_item(purge_fixture):
    repository, service, *_ = purge_fixture
    calls: list[tuple[str, str, str]] = []

    def project(cause: str, entity_id: str, project_id: str) -> ProjectionResult:
        calls.append((cause, entity_id, project_id))
        assert KNOWLEDGE_ID not in {
            item.id for item in repository.list_project_knowledge(PROJECT_ID)
        }
        event_id = repository.save_current_projection_event(
            project_id, cause, entity_id
        )
        repository.finish_projection_event(event_id, ProjectionStatus.SYNCED)
        return ProjectionResult(event_id, ProjectionStatus.SYNCED)

    projecting = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        completed_projection=project,
    )
    plan = projecting.plan(KNOWLEDGE_ID)

    assert (
        projecting.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGED
    )
    assert calls == [("sensitive_purge", KNOWLEDGE_ID, PROJECT_ID)]
    assert projecting.projection_result == PurgeProjectionResult(
        repository.list_projection_events(PROJECT_ID)[0].id,
        ProjectionStatus.SYNCED,
    )
    event = repository.list_projection_events(PROJECT_ID)[0]
    assert event.cause == "sensitive_purge"
    assert event.cause_entity_id == KNOWLEDGE_ID
    assert MARKER not in json.dumps(event.__dict__, default=str)


def test_projection_failure_keeps_purge_authoritative_and_reports_retry(
    purge_fixture,
):
    repository, service, *_ = purge_fixture

    def fail_projection(
        cause: str, entity_id: str, project_id: str
    ) -> ProjectionResult:
        error = ProjectionPersistenceError(str(service.vault_root))
        error.recovery_command = str(service.vault_root)
        raise error

    projecting = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        completed_projection=fail_projection,
    )
    plan = projecting.plan(KNOWLEDGE_ID)

    assert (
        projecting.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGED
    )
    assert KNOWLEDGE_ID not in {
        item.id for item in repository.list_project_knowledge(PROJECT_ID)
    }
    assert repository.get_purge_tombstone(KNOWLEDGE_ID).status is PurgeStatus.PURGED
    assert projecting.projection_result is not None
    assert projecting.projection_result.status is ProjectionStatus.SYNC_PENDING
    assert projecting.projection_result.reason == "projection_failed"
    assert projecting.projection_result.recovery_command == "retro doctor --repair-sync"
    assert MARKER.encode() not in repository.db_path.read_bytes()


def test_recover_success_triggers_the_same_idempotent_projection(purge_fixture):
    repository, service, *_ = purge_fixture

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected cleanup failure")

    interrupted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=fail_replace,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)
    assert (
        interrupted.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGE_INCOMPLETE
    )

    def project(cause: str, entity_id: str, project_id: str) -> ProjectionResult:
        event_id = repository.save_current_projection_event(
            project_id, cause, entity_id
        )
        repository.finish_projection_event(event_id, ProjectionStatus.SYNCED)
        return ProjectionResult(event_id, ProjectionStatus.SYNCED)

    restarted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        completed_projection=project,
    )
    assert restarted.recover(KNOWLEDGE_ID) is PurgeStatus.PURGED
    events = repository.list_projection_events(PROJECT_ID)
    assert len(events) == 1
    assert events[0].cause == "sensitive_purge"
    assert restarted.projection_result is not None
    assert restarted.projection_result.event_id == events[0].id


def test_purge_parser_requires_one_explicit_mutually_exclusive_mode():
    parser = retro_cli.build_parser()

    planned = parser.parse_args(["knowledge", "purge", KNOWLEDGE_ID, "--plan"])
    assert planned.purge_plan
    applied = parser.parse_args(
        [
            "knowledge",
            "purge",
            KNOWLEDGE_ID,
            "--apply-plan",
            "purge-plan-id",
            "--confirm-operation",
            "operation-a",
            "--confirm-operation",
            "operation-b",
        ]
    )
    assert applied.purge_plan_id == "purge-plan-id"
    assert applied.confirmed_operations == ["operation-a", "operation-b"]
    assert parser.parse_args(
        ["knowledge", "purge", KNOWLEDGE_ID, "--recover"]
    ).purge_recover
    with pytest.raises(SystemExit):
        parser.parse_args(["knowledge", "purge", KNOWLEDGE_ID])
    with pytest.raises(SystemExit):
        parser.parse_args(["knowledge", "purge", KNOWLEDGE_ID, "--plan", "--recover"])


def test_cli_plan_is_zero_write_and_emits_only_redacted_operations(
    purge_fixture, tmp_path: Path, capsys
):
    repository, service, *_ = purge_fixture
    before = _snapshot(tmp_path, repository)
    env = {
        "AGENTRETRO_HOME": str(repository.db_path.parent),
        "AGENTRETRO_OBSIDIAN_ROOT": str(service.vault_root),
    }

    assert (
        retro_cli.main(
            ["--json", "knowledge", "purge", KNOWLEDGE_ID, "--plan"],
            home=tmp_path,
            env=env,
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "RETRO_PURGE_PLANNED"
    assert payload["data"]["purge_status"] == "planned"
    assert payload["data"]["projection_status"] == "not_started"
    assert payload["data"]["operations"]
    assert all(set(item) == {"id", "kind"} for item in payload["data"]["operations"])
    serialized = json.dumps(payload, ensure_ascii=False)
    assert MARKER not in serialized
    assert str(tmp_path) not in serialized
    assert "expected_hash" not in serialized
    assert "locator" not in serialized
    assert _snapshot(tmp_path, repository) == before


def test_cli_apply_requires_confirmations_then_projects_in_the_same_command(
    purge_fixture, tmp_path: Path, capsys
):
    repository, service, *_ = purge_fixture
    env = {
        "AGENTRETRO_HOME": str(repository.db_path.parent),
        "AGENTRETRO_OBSIDIAN_ROOT": str(service.vault_root),
    }
    assert (
        retro_cli.main(
            ["--json", "knowledge", "purge", KNOWLEDGE_ID, "--plan"],
            home=tmp_path,
            env=env,
        )
        == 0
    )
    planned = json.loads(capsys.readouterr().out)["data"]

    assert (
        retro_cli.main(
            [
                "--json",
                "knowledge",
                "purge",
                KNOWLEDGE_ID,
                "--apply-plan",
                planned["plan_id"],
            ],
            home=tmp_path,
            env=env,
        )
        == 2
    )
    refused = json.loads(capsys.readouterr().out)
    assert refused["code"] == "RETRO_PURGE_CONFIRMATION_REQUIRED"
    assert refused["data"]["recovery_command"] == ("retro knowledge purge <id> --plan")

    command = [
        "--json",
        "knowledge",
        "purge",
        KNOWLEDGE_ID,
        "--apply-plan",
        planned["plan_id"],
    ]
    for operation in planned["operations"]:
        command.extend(["--confirm-operation", operation["id"]])
    assert retro_cli.main(command, home=tmp_path, env=env) == 0
    applied = json.loads(capsys.readouterr().out)

    assert applied["code"] == "RETRO_PURGE_APPLIED"
    assert applied["data"]["purge_status"] == "purged"
    assert applied["data"]["projection_status"] in {
        "synced",
        "sync_pending",
    }
    readback = SQLiteRetroRepository(repository.db_path, repository.backup_dir)
    events = readback.list_projection_events(PROJECT_ID)
    assert len(events) == 1
    assert events[0].cause == "sensitive_purge"
    assert events[0].cause_entity_id == KNOWLEDGE_ID
    serialized = json.dumps(applied, ensure_ascii=False)
    assert MARKER not in serialized
    assert str(tmp_path) not in serialized
    assert "expected_hash" not in serialized
    assert "locator" not in serialized


def test_cli_recover_resumes_registered_state_and_projects(
    purge_fixture, tmp_path: Path, capsys
):
    repository, service, *_ = purge_fixture

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("injected cleanup failure")

    interrupted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots={"agentretro_backup": repository.backup_dir},
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=fail_replace,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)
    assert (
        interrupted.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGE_INCOMPLETE
    )
    env = {
        "AGENTRETRO_HOME": str(repository.db_path.parent),
        "AGENTRETRO_OBSIDIAN_ROOT": str(service.vault_root),
    }

    assert (
        retro_cli.main(
            ["--json", "knowledge", "purge", KNOWLEDGE_ID, "--recover"],
            home=tmp_path,
            env=env,
        )
        == 0
    )
    recovered = json.loads(capsys.readouterr().out)
    assert recovered["code"] == "RETRO_PURGE_RECOVERED"
    assert recovered["data"]["purge_status"] == "purged"
    assert recovered["data"]["projection_status"] in {
        "synced",
        "sync_pending",
    }
    assert len(repository.list_projection_events(PROJECT_ID)) == 1
    serialized = json.dumps(recovered, ensure_ascii=False)
    assert MARKER not in serialized
    assert str(tmp_path) not in serialized


def test_sqlite_stage_failure_rolls_back_the_journal_and_every_scrub(purge_fixture):
    repository, service, *_ = purge_fixture
    failing = _FailingPurgeRepository(repository.db_path, repository.backup_dir)
    failing.fail_purge_audit = True
    failing_service = PurgeService(
        failing,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
    )
    plan = failing_service.plan(KNOWLEDGE_ID)
    before = _database_rows(failing)

    with pytest.raises(OSError, match="injected purge transaction failure"):
        failing_service.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )

    assert _database_rows(failing) == before
    assert failing.get_purge_tombstone(KNOWLEDGE_ID) is None


def test_purge_removes_sensitive_copies_related_to_every_knowledge_version(
    purge_fixture,
):
    repository, service, managed, *_ = purge_fixture
    current_marker = "agentretro-current-8d9cc8fb"
    now = "2026-07-18T00:01:00+00:00"
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evidence-b",
                "session-a",
                "fact",
                "source-a",
                "event-b",
                "redacted",
                "evidence-hash-b",
                f"evidence {current_marker}",
            ),
        )
        connection.execute(
            "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "candidate-b",
                "session-a",
                "RULE",
                PROJECT_ID,
                "project",
                current_marker,
                "accepted",
                0.99,
                json.dumps({"reason": current_marker}),
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO candidate_evidence VALUES (?, ?)",
            ("candidate-b", "evidence-b"),
        )
        connection.execute(
            "INSERT INTO knowledge VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                KNOWLEDGE_ID,
                2,
                "candidate-b",
                "RULE",
                PROJECT_ID,
                "project",
                current_marker,
                "active",
                0.99,
                "user",
                None,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO knowledge_evidence VALUES (?, ?, ?)",
            (KNOWLEDGE_ID, 2, "evidence-b"),
        )
        connection.execute(
            "INSERT INTO projection_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "projection-old",
                PROJECT_ID,
                "knowledge_accept",
                KNOWLEDGE_ID,
                "input-old",
                "synced",
                f"error {MARKER}",
                now,
                now,
            ),
        )

    managed.write_text(f"old {MARKER}\ncurrent {current_marker}\n", encoding="utf-8")
    plan = service.plan(KNOWLEDGE_ID)

    assert (
        service.apply(plan.id, frozenset(operation.id for operation in plan.operations))
        is PurgeStatus.PURGED
    )

    related_fields = {
        "candidates": ("proposed_text", "review_json"),
        "evidence": ("excerpt",),
        "review_attempts": ("result_json", "error"),
        "conflicts": ("reason", "merge_text"),
        "sync_jobs": ("plan_json", "error"),
        "projection_events": ("input_hash", "error"),
        "managed_file_snapshots": ("owned_bytes",),
        "audit_log": ("detail_json",),
    }
    for table, fields in related_fields.items():
        for row in _table_rows(repository, table):
            serialized = " ".join(str(row[field]) for field in fields)
            assert MARKER not in serialized
            assert current_marker not in serialized
    raw_database = repository.db_path.read_bytes()
    assert MARKER.encode() not in raw_database
    assert current_marker.encode() not in raw_database
    for path in (managed, *service.log_paths, *service.trace_paths):
        assert MARKER.encode() not in path.read_bytes()


def test_begin_purge_precommit_guard_rolls_back_when_registered_file_changes(
    purge_fixture, monkeypatch: pytest.MonkeyPatch
):
    repository, service, managed, *_ = purge_fixture
    plan = service.plan(KNOWLEDGE_ID)
    confirmations = frozenset(operation.id for operation in plan.operations)
    before_database = _database_rows(repository)
    changed_content = f"concurrent edit {MARKER}\n"
    original_begin = repository.begin_purge

    def begin_with_precommit_race(*args, **kwargs):
        guard = kwargs.get("precommit_guard")
        if guard is None:
            managed.write_text(changed_content, encoding="utf-8")
        else:

            def inject_change_then_guard():
                managed.write_text(changed_content, encoding="utf-8")
                guard()

            kwargs["precommit_guard"] = inject_change_then_guard
        return original_begin(*args, **kwargs)

    monkeypatch.setattr(repository, "begin_purge", begin_with_precommit_race)

    with pytest.raises(StalePurgePlan):
        service.apply(plan.id, confirmations)

    assert _database_rows(repository) == before_database
    assert _table_rows(repository, "purge_jobs") == []
    assert _table_rows(repository, "purge_operations") == []
    assert managed.read_text(encoding="utf-8") == changed_content


def test_success_replaces_content_derived_journal_with_opaque_tombstone(
    purge_fixture,
):
    repository, service, *_ = purge_fixture
    plan = service.plan(KNOWLEDGE_ID)
    content_derived_ids = {plan.id, *(operation.id for operation in plan.operations)}

    assert (
        service.apply(plan.id, frozenset(operation.id for operation in plan.operations))
        is PurgeStatus.PURGED
    )

    assert _table_rows(repository, "purge_operations") == []
    jobs = _table_rows(repository, "purge_jobs")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["id"] not in content_derived_ids
    assert job["knowledge_id"] == KNOWLEDGE_ID
    assert job["plan_hash"] == ""
    assert job["status"] == PurgeStatus.PURGED.value
    assert job["residual_json"] == "[]"
    tombstone = json.loads(job["tombstone_json"])
    assert set(tombstone) == {
        "knowledge_id",
        "actor",
        "started_at",
        "updated_at",
        "status",
        "operation_count",
        "residual_count",
    }
    assert tombstone["knowledge_id"] == KNOWLEDGE_ID
    assert tombstone["status"] == PurgeStatus.PURGED.value
    assert tombstone["operation_count"] == len(plan.operations)
    assert tombstone["residual_count"] == 0
    raw_database = repository.db_path.read_bytes()
    for derived_id in content_derived_ids:
        assert derived_id.encode() not in raw_database
    typed = repository.get_purge_tombstone(KNOWLEDGE_ID)
    assert typed is not None
    assert typed.status is PurgeStatus.PURGED


def test_multi_marker_incomplete_journal_recovers_all_registered_files(
    purge_fixture,
):
    repository, service, _, _, _, log, trace = purge_fixture
    current_marker = "agentretro-current-recovery-cde370"
    now = "2026-07-18T00:02:00+00:00"
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "candidate-recovery-v2",
                "session-a",
                "RULE",
                PROJECT_ID,
                "project",
                current_marker,
                "accepted",
                0.99,
                "{}",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO knowledge VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                KNOWLEDGE_ID,
                2,
                "candidate-recovery-v2",
                "RULE",
                PROJECT_ID,
                "project",
                current_marker,
                "active",
                0.99,
                "user",
                None,
                now,
            ),
        )
    log.write_text(f"old {MARKER}\n", encoding="utf-8")
    trace.write_text(f"current {current_marker}\n", encoding="utf-8")
    replace_count = 0

    def fail_second_replace(source: Path, target: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("injected multi-marker write failure")
        source.replace(target)

    interrupted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
        replace=fail_second_replace,
    )
    plan = interrupted.plan(KNOWLEDGE_ID)
    assert (
        interrupted.apply(
            plan.id, frozenset(operation.id for operation in plan.operations)
        )
        is PurgeStatus.PURGE_INCOMPLETE
    )
    journal = repository.get_purge_journal(KNOWLEDGE_ID)
    assert journal is not None
    fingerprints = set(journal.marker_fingerprints)
    assert (hashlib.sha256(MARKER.encode()).hexdigest(), len(MARKER)) in fingerprints
    assert (
        hashlib.sha256(current_marker.encode()).hexdigest(),
        len(current_marker),
    ) in fingerprints

    restarted = PurgeService(
        repository,
        vault_root=service.vault_root,
        backup_roots=service.backup_roots,
        log_paths=service.log_paths,
        trace_paths=service.trace_paths,
    )
    assert restarted.recover(KNOWLEDGE_ID) is PurgeStatus.PURGED
    for marker in (MARKER.encode(), current_marker.encode()):
        for path in (*restarted.log_paths, *restarted.trace_paths):
            if path.exists():
                assert marker not in path.read_bytes()
        for root in restarted.backup_roots.values():
            for path in root.rglob("*"):
                if path.is_file():
                    assert marker not in path.read_bytes()


def test_purge_preserves_unrelated_entity_with_identical_text(purge_fixture):
    repository, service, *_ = purge_fixture
    now = "2026-07-18T00:03:00+00:00"
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "candidate-unrelated-same-text",
                "session-a",
                "RULE",
                "project-unrelated",
                "project",
                MARKER,
                "pending_review",
                0.9,
                "{}",
                now,
                now,
            ),
        )
    plan = service.plan(KNOWLEDGE_ID)

    assert (
        service.apply(plan.id, frozenset(operation.id for operation in plan.operations))
        is PurgeStatus.PURGED
    )
    unrelated = next(
        row
        for row in _table_rows(repository, "candidates")
        if row["id"] == "candidate-unrelated-same-text"
    )
    assert unrelated["proposed_text"] == MARKER
