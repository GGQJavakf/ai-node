from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.purge import (
    KnowledgeAlreadyPurged,
    KnowledgeSyncPending,
    PurgeKnowledgeNotFound,
    PurgeService,
)
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


MARKER = "agentretro-secret-6c25d4e9"
KNOWLEDGE_ID = "knowledge-purge-a"
PROJECT_ID = "project-a"


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


def test_plan_is_read_only_complete_redacted_and_deterministic(
    purge_fixture, tmp_path: Path
):
    repository, service, managed, sync_copy, unrelated, log, trace = purge_fixture
    before = _snapshot(tmp_path, repository)

    first = service.plan(KNOWLEDGE_ID)
    second = service.plan(KNOWLEDGE_ID)

    assert first == second
    assert _snapshot(tmp_path, repository) == before
    assert len(first.operations) == 11
    kinds = {operation.location_kind for operation in first.operations}
    assert {
        "sqlite_knowledge",
        "sqlite_candidate",
        "sqlite_evidence",
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
