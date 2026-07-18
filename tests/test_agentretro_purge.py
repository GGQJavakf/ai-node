from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.purge import (
    IncompletePurgeConfirmation,
    KnowledgeAlreadyPurged,
    KnowledgeSyncPending,
    PurgeKnowledgeNotFound,
    PurgeService,
    StalePurgePlan,
    UnsafePurgeRegistration,
)
from agent_retro.domain.models import PurgeStatus
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


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
    assert len(operations) == len(plan.operations)
    assert all(MARKER not in json.dumps(row) for row in operations)
    assert all(row["location"] == "" for row in operations)
    assert all(row["expected_hash"] == "" for row in operations)
    assert all(row["status"] == "completed" for row in operations)
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
