import sqlite3
import subprocess
import sys
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import _path  # noqa: F401
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.infrastructure import sqlite_repository as sqlite_repository_module
from agent_retro.application.bootstrap import build_retro_repository
from agent_retro.domain.models import (
    AuditEntry,
    Candidate,
    CandidateStatus,
    Evidence,
    Knowledge,
    KnowledgeConflict,
    KnowledgeType,
    NormalizedEvent,
    NormalizedSession,
    ProjectMapping,
    PurgeOperation,
    PurgePlan,
    PurgeStatus,
    ReviewAttempt,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
    SyncJob,
)
from agent_retro.infrastructure.settings import load_retro_settings


NOW = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)


def _session() -> NormalizedSession:
    return NormalizedSession(
        id="session-1",
        source_session_id="codex-session-1",
        source_path=Path("sessions/2026/session-1.jsonl"),
        source_hash="source-hash-1",
        project_id="project-1",
        completed=True,
        completed_at=NOW,
        events=(),
    )


def _evidence() -> Evidence:
    return Evidence(
        id="evidence-1",
        session_id="session-1",
        kind="user_instruction",
        locator=SourceLocator(
            session_id="codex-session-1",
            event_id="event-1",
            source_path=Path("sessions/2026/session-1.jsonl"),
            content_hash="evidence-hash-1",
        ),
        excerpt="Keep persistence isolated.",
    )


def _candidate() -> Candidate:
    return Candidate(
        id="candidate-1",
        knowledge_type=KnowledgeType.RULE,
        project_id="project-1",
        scope="project",
        proposed_text="Use an isolated database.",
        status=CandidateStatus.PENDING_REVIEW,
        extraction_confidence=0.98,
        evidence_ids=("evidence-1",),
    )


def _mapping(mapping_id: str = "mapping-1") -> ProjectMapping:
    return ProjectMapping(
        id=mapping_id,
        git_root=Path("D:/projects/example"),
        remote_identity="example/repository",
        obsidian_project="Projects/Example",
    )


def _rows(db_path: Path, sql: str, parameters=()):
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(sql, parameters).fetchall()


def _repository_with_candidate(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()
    repo.save_capture(_session(), [_evidence()])
    repo.save_candidates([_candidate()])
    return repo


def test_domain_contracts_are_not_polluted_by_sqlite_columns():
    expected_fields = {
        SourceLocator: ("session_id", "event_id", "source_path", "content_hash"),
        NormalizedEvent: ("id", "kind", "content", "locator"),
        Evidence: ("id", "session_id", "kind", "locator", "excerpt"),
        NormalizedSession: (
            "id",
            "source_session_id",
            "source_path",
            "source_hash",
            "project_id",
            "completed",
            "completed_at",
            "events",
        ),
        Candidate: (
            "id",
            "knowledge_type",
            "project_id",
            "scope",
            "proposed_text",
            "evidence_ids",
            "status",
            "extraction_confidence",
        ),
        ReviewResult: (
            "verdict",
            "confidence",
            "reason",
            "normalized_text",
            "duplicate_of",
            "conflict_with",
        ),
        Knowledge: (
            "id",
            "version",
            "candidate_id",
            "knowledge_type",
            "project_id",
            "scope",
            "text",
            "status",
            "confidence",
            "accepted_by",
            "evidence_ids",
            "valid_until",
            "updated_at",
        ),
        KnowledgeConflict: (
            "id",
            "active_knowledge_id",
            "candidate_id",
            "reason",
            "merge_text",
            "status",
        ),
        SyncJob: (
            "id",
            "project_id",
            "status",
            "plan_json",
            "backup_path",
            "error",
        ),
        ProjectMapping: (
            "id",
            "git_root",
            "remote_identity",
            "obsidian_project",
            "active",
        ),
        ReviewAttempt: (
            "id",
            "candidate_id",
            "input_hash",
            "status",
            "result_json",
            "error",
        ),
        PurgeOperation: ("id", "location_kind", "location", "expected_hash"),
        PurgePlan: ("id", "knowledge_id", "operations", "status"),
        AuditEntry: (
            "id",
            "actor",
            "action",
            "entity_type",
            "entity_id",
            "before_hash",
            "after_hash",
            "detail_json",
            "created_at",
        ),
    }

    for model, names in expected_fields.items():
        assert tuple(field.name for field in fields(model)) == names

    assert [item.value for item in ReviewVerdict] == ["ACCEPT", "EDIT", "REJECT"]
    assert [item.value for item in CandidateStatus] == [
        "pending_review",
        "auto_accepted",
        "accepted",
        "edited",
        "rejected",
    ]
    assert [item.value for item in PurgeStatus] == [
        "planned",
        "purge_incomplete",
        "purged",
    ]
    assert _mapping().active is True
    assert SyncJob("s", "p", "running", "{}", Path("b")).error == ""


def test_repository_creates_schema_version_one(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")

    repo.migrate()

    assert repo.schema_version() == 1
    assert set(repo.table_names()) >= {
        "sessions",
        "evidence",
        "candidates",
        "review_attempts",
        "knowledge",
        "conflicts",
        "projection_events",
        "sync_jobs",
        "project_mappings",
        "purge_jobs",
        "purge_operations",
        "managed_file_state",
        "audit_log",
    }
    with repo.transaction() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_failed_migration_restores_database(tmp_path, monkeypatch):
    db_path = tmp_path / "retro.db"
    backup_dir = tmp_path / "backups"
    repo = SQLiteRetroRepository(db_path, backup_dir)
    repo.migrate()
    before = db_path.read_bytes()

    monkeypatch.setattr(
        repo,
        "_apply_migration",
        lambda connection, version: (_ for _ in ()).throw(RuntimeError("injected")),
    )

    with pytest.raises(RuntimeError, match="injected"):
        repo.migrate(target_version=2)

    backups = list(backup_dir.glob("migration-1-to-2-*.db"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before
    assert db_path.read_bytes() == before
    assert repo.schema_version() == 1


def test_new_database_connect_failure_removes_database_and_sidecars(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "retro.db"
    repo = SQLiteRetroRepository(db_path, tmp_path / "backups")
    residue = [
        db_path,
        Path(f"{db_path}-journal"),
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ]

    def fail_after_creating_files():
        for path in residue:
            path.touch()
        raise RuntimeError("connect failed")

    monkeypatch.setattr(repo, "_connect", fail_after_creating_files)

    with pytest.raises(RuntimeError, match="connect failed"):
        repo.migrate()

    assert all(not path.exists() for path in residue)


def test_new_database_pragma_failure_closes_connection_and_removes_residue(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "retro.db"
    repo = SQLiteRetroRepository(db_path, tmp_path / "backups")
    residue = [
        db_path,
        Path(f"{db_path}-journal"),
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ]

    class PragmaFailureConnection:
        row_factory = None
        closed = False

        def execute(self, statement):
            for path in residue:
                path.touch()
            raise RuntimeError("pragma failed")

        def close(self):
            self.closed = True

    connection = PragmaFailureConnection()
    monkeypatch.setattr(
        sqlite_repository_module.sqlite3,
        "connect",
        lambda path: connection,
    )

    with pytest.raises(RuntimeError, match="pragma failed"):
        repo.migrate()

    assert connection.closed is True
    assert all(not path.exists() for path in residue)


def test_rollback_failure_does_not_skip_restore_or_replace_original_error(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "retro.db"
    repo = SQLiteRetroRepository(db_path, tmp_path / "backups")
    repo.migrate()
    before = db_path.read_bytes()
    original_connect = repo._connect
    connect_count = 0

    class RollbackFailureConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, parameters=()):
            return self.connection.execute(statement, parameters)

        def commit(self):
            return self.connection.commit()

        def rollback(self):
            self.connection.rollback()
            raise RuntimeError("rollback failed")

        def close(self):
            return self.connection.close()

    def connect_with_rollback_failure():
        nonlocal connect_count
        connect_count += 1
        connection = original_connect()
        if connect_count == 3:
            return RollbackFailureConnection(connection)
        return connection

    monkeypatch.setattr(repo, "_connect", connect_with_rollback_failure)
    monkeypatch.setattr(
        repo,
        "_apply_migration",
        lambda connection, version: (_ for _ in ()).throw(RuntimeError("injected")),
    )

    with pytest.raises(RuntimeError, match="injected"):
        repo.migrate(target_version=2)

    assert db_path.read_bytes() == before


def test_failed_migration_removes_sidecars_before_restoring_backup(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "retro.db"
    repo = SQLiteRetroRepository(db_path, tmp_path / "backups")
    repo.migrate()
    before = db_path.read_bytes()
    sidecars = [
        Path(f"{db_path}-journal"),
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ]
    original_restore = repo._restore_backup

    def restore_with_stale_sidecars(backup_path, expected_hash):
        for path in sidecars:
            path.write_bytes(b"stale")
        original_restore(backup_path, expected_hash)

    monkeypatch.setattr(repo, "_restore_backup", restore_with_stale_sidecars)
    monkeypatch.setattr(
        repo,
        "_apply_migration",
        lambda connection, version: (_ for _ in ()).throw(RuntimeError("injected")),
    )

    with pytest.raises(RuntimeError, match="injected"):
        repo.migrate(target_version=2)

    assert db_path.read_bytes() == before
    assert all(not path.exists() for path in sidecars)


def test_migration_backup_checkpoints_wal_before_copy(tmp_path, monkeypatch):
    db_path = tmp_path / "retro.db"
    repo = SQLiteRetroRepository(db_path, tmp_path / "backups")
    repo.migrate()
    sidecars = [
        Path(f"{db_path}-journal"),
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ]

    def schema_version_after_uncheckpointed_write():
        script = (
            "import os, sqlite3, sys\n"
            "connection = sqlite3.connect(sys.argv[1])\n"
            "connection.execute('PRAGMA journal_mode=WAL')\n"
            "connection.execute('PRAGMA wal_autocheckpoint=0')\n"
            "connection.execute('CREATE TABLE wal_probe(value TEXT NOT NULL)')\n"
            "connection.execute(\"INSERT INTO wal_probe VALUES ('preserved')\")\n"
            "connection.commit()\n"
            "os._exit(0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(db_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert Path(f"{db_path}-wal").exists()
        return 1

    monkeypatch.setattr(repo, "schema_version", schema_version_after_uncheckpointed_write)
    monkeypatch.setattr(
        repo,
        "_apply_migration",
        lambda connection, version: (_ for _ in ()).throw(RuntimeError("injected")),
    )

    with pytest.raises(RuntimeError, match="injected"):
        repo.migrate(target_version=2)

    assert all(not path.exists() for path in sidecars)
    assert _rows(db_path, "SELECT value FROM wal_probe")[0][0] == "preserved"


def test_transaction_commits_on_success_and_rolls_back_on_exception(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()

    with repo.transaction() as connection:
        connection.execute(
            "INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("committed", "test", "commit", "test", "1", "", "", "{}", NOW.isoformat()),
        )

    with pytest.raises(RuntimeError, match="rollback"):
        with repo.transaction() as connection:
            connection.execute(
                "INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("rolled-back", "test", "rollback", "test", "2", "", "", "{}", NOW.isoformat()),
            )
            raise RuntimeError("rollback")

    audit_ids = {row["id"] for row in _rows(repo.db_path, "SELECT id FROM audit_log")}
    assert "committed" in audit_ids
    assert "rolled-back" not in audit_ids


def test_audit_failure_rolls_back_the_lifecycle_mutation(tmp_path, monkeypatch):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()
    monkeypatch.setattr(
        repo,
        "_append_audit_record",
        lambda connection, entry: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        repo.save_project_mapping(_mapping(), actor="tester")

    assert repo.list_project_mappings(active_only=False) == []


def test_bootstrap_uses_agentretro_settings_and_migrates_the_isolated_database(tmp_path):
    settings = load_retro_settings(home=tmp_path, env={})

    repo = build_retro_repository(settings)

    assert repo.db_path == tmp_path / ".agentretro" / "retro.db"
    assert repo.schema_version() == 1
    assert not (tmp_path / "data" / "todos.db").exists()


def test_capture_candidates_review_and_acceptance_round_trip_with_audit(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()
    session = _session()
    evidence = _evidence()
    candidate = _candidate()

    repo.save_capture(session, [evidence])
    repo.save_candidates([candidate])
    result = ReviewResult(
        verdict=ReviewVerdict.ACCEPT,
        confidence=0.99,
        reason="Evidence is explicit.",
        normalized_text="Use an isolated database.",
        duplicate_of=None,
        conflict_with=None,
    )
    repo.save_review(candidate.id, result)
    attempt = repo.begin_review_attempt(
        ReviewAttempt(
            id="attempt-1",
            candidate_id=candidate.id,
            input_hash="review-input-hash",
            status="running",
            result_json="",
            error="",
        )
    )
    repo.finish_review_attempt(
        attempt.id,
        status="completed",
        result_json='{"verdict":"ACCEPT"}',
    )
    knowledge = repo.accept_candidate(
        candidate.id,
        text="Use an isolated database.",
        actor="tester",
        confidence=0.99,
    )

    assert repo.find_session(session.source_session_id, session.source_hash) == session
    reviewed = repo.get_candidate(candidate.id)
    assert reviewed is not None
    assert reviewed.status == CandidateStatus.ACCEPTED
    assert repo.list_candidates(CandidateStatus.ACCEPTED) == [reviewed]
    review_json = _rows(
        repo.db_path,
        "SELECT review_json FROM candidates WHERE id = ?",
        (candidate.id,),
    )[0][0]
    assert review_json == (
        '{"confidence":0.99,"conflict_with":null,"duplicate_of":null,'
        '"normalized_text":"Use an isolated database.",'
        '"reason":"Evidence is explicit.","verdict":"ACCEPT"}'
    )
    assert knowledge.candidate_id == candidate.id
    assert knowledge.evidence_ids == (evidence.id,)
    assert repo.list_active_knowledge("project-1", NOW + timedelta(days=1)) == [knowledge]
    actions = {
        row["action"] for row in _rows(repo.db_path, "SELECT action FROM audit_log")
    }
    assert {
        "migration_applied",
        "capture_saved",
        "candidates_saved",
        "review_saved",
        "review_attempt_started",
        "review_attempt_finished",
        "candidate_accepted",
    } <= actions


def test_conflict_and_sync_lifecycle_are_persisted_and_audited(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()
    repo.save_conflict(
        KnowledgeConflict(
            id="conflict-1",
            active_knowledge_id="knowledge-1",
            candidate_id="candidate-1",
            reason="Contradictory guidance",
            merge_text="Keep the explicit project rule.",
            status="open",
        )
    )
    repo.begin_sync(
        SyncJob(
            id="sync-1",
            project_id="project-1",
            status="running",
            plan_json='{"targets":[]}',
            backup_path=Path("backups/sync-1"),
        )
    )
    repo.finish_sync("sync-1", status="completed")

    assert _rows(repo.db_path, "SELECT status FROM conflicts WHERE id = 'conflict-1'")[0][0] == "open"
    sync = _rows(repo.db_path, "SELECT status, error FROM sync_jobs WHERE id = 'sync-1'")[0]
    assert tuple(sync) == ("completed", "")
    actions = [row[0] for row in _rows(repo.db_path, "SELECT action FROM audit_log")]
    assert "conflict_saved" in actions
    assert "sync_started" in actions
    assert "sync_finished" in actions


def test_mapping_projection_and_managed_file_state_lifecycle(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()
    mapping = _mapping()

    repo.save_project_mapping(mapping, actor="tester")
    event_id = repo.save_projection_event(
        event_id="projection-1",
        project_id="project-1",
        cause="candidate_accepted",
        cause_entity_id="knowledge-1",
        input_hash="projection-input-hash",
    )
    duplicate_id = repo.save_projection_event(
        event_id="projection-duplicate",
        project_id="project-1",
        cause="candidate_accepted",
        cause_entity_id="knowledge-1",
        input_hash="projection-input-hash",
    )
    repo.save_managed_file_state(
        "project-1",
        Path("Projects/Example/AgentRetro/规则.md"),
        managed_hash="managed-hash",
        full_hash="full-hash",
    )
    repo.deactivate_project_mapping(mapping.id, actor="tester")

    assert event_id == "projection-1"
    assert duplicate_id == "projection-1"
    assert repo.list_project_mappings() == []
    saved_mapping = repo.list_project_mappings(active_only=False)[0]
    assert saved_mapping == ProjectMapping(
        id=mapping.id,
        git_root=mapping.git_root,
        remote_identity=mapping.remote_identity,
        obsidian_project=mapping.obsidian_project,
        active=False,
    )
    state = _rows(repo.db_path, "SELECT * FROM managed_file_state")[0]
    assert state["managed_hash"] == "managed-hash"
    assert state["full_hash"] == "full-hash"


def test_purge_plan_and_completion_persist_operations_and_audit(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()
    plan = PurgePlan(
        id="purge-1",
        knowledge_id="knowledge-1",
        operations=(
            PurgeOperation(
                id="purge-op-1",
                location_kind="sqlite",
                location="knowledge:knowledge-1",
                expected_hash="sensitive-hash",
            ),
        ),
        status=PurgeStatus.PLANNED,
    )

    repo.save_purge_plan(plan, plan_hash="plan-hash", actor="tester")
    repo.finish_purge(
        plan.id,
        status=PurgeStatus.PURGED,
        tombstone_json='{"knowledge_id":"knowledge-1"}',
        residual_json="[]",
    )

    job = _rows(repo.db_path, "SELECT * FROM purge_jobs WHERE id = 'purge-1'")[0]
    operation = _rows(repo.db_path, "SELECT * FROM purge_operations")[0]
    assert job["status"] == PurgeStatus.PURGED.value
    assert job["plan_hash"] == "plan-hash"
    assert operation["purge_job_id"] == plan.id
    assert operation["location"] == "knowledge:knowledge-1"
    actions = [row[0] for row in _rows(repo.db_path, "SELECT action FROM audit_log")]
    assert "purge_planned" in actions
    assert "purge_finished" in actions


def test_append_audit_persists_the_supplied_entry_without_recursive_audit(tmp_path):
    repo = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repo.migrate()
    entry = AuditEntry(
        id="audit-explicit",
        actor="tester",
        action="manual_note",
        entity_type="knowledge",
        entity_id="knowledge-1",
        before_hash="before",
        after_hash="after",
        detail_json='{"reason":"test"}',
        created_at=NOW,
    )

    repo.append_audit(entry)

    rows = _rows(repo.db_path, "SELECT * FROM audit_log WHERE id = ?", (entry.id,))
    assert len(rows) == 1
    assert rows[0]["actor"] == entry.actor
    assert rows[0]["detail_json"] == '{"reason":"test"}'


def test_accept_candidate_is_strictly_idempotent_for_identical_input(tmp_path):
    repo = _repository_with_candidate(tmp_path)
    first = repo.accept_candidate(
        "candidate-1",
        text="Use an isolated database.",
        actor="tester",
        confidence=0.99,
    )
    audit_count = _rows(
        repo.db_path,
        "SELECT COUNT(*) FROM audit_log WHERE action = 'candidate_accepted'",
    )[0][0]

    second = repo.accept_candidate(
        "candidate-1",
        text="Use an isolated database.",
        actor="tester",
        confidence=0.99,
    )

    assert second == first
    assert _rows(
        repo.db_path,
        "SELECT COUNT(*) FROM audit_log WHERE action = 'candidate_accepted'",
    )[0][0] == audit_count


@pytest.mark.parametrize(
    ("text", "actor", "confidence"),
    [
        ("Use a shared database.", "tester", 0.99),
        ("Use an isolated database.", "other", 0.99),
        ("Use an isolated database.", "tester", 0.50),
    ],
)
def test_accept_candidate_rejects_conflicting_reacceptance_without_writes(
    tmp_path, text, actor, confidence
):
    repo = _repository_with_candidate(tmp_path)
    repo.accept_candidate(
        "candidate-1",
        text="Use an isolated database.",
        actor="tester",
        confidence=0.99,
    )
    before_knowledge = [
        tuple(row) for row in _rows(repo.db_path, "SELECT * FROM knowledge")
    ]
    before_candidate = [
        tuple(row)
        for row in _rows(
            repo.db_path,
            "SELECT status, updated_at FROM candidates WHERE id = 'candidate-1'",
        )
    ]
    before_audit = [
        tuple(row) for row in _rows(repo.db_path, "SELECT * FROM audit_log")
    ]

    with pytest.raises(ValueError, match="conflicts with accepted knowledge"):
        repo.accept_candidate(
            "candidate-1",
            text=text,
            actor=actor,
            confidence=confidence,
        )

    assert [
        tuple(row) for row in _rows(repo.db_path, "SELECT * FROM knowledge")
    ] == before_knowledge
    assert [
        tuple(row)
        for row in _rows(
            repo.db_path,
            "SELECT status, updated_at FROM candidates WHERE id = 'candidate-1'",
        )
    ] == before_candidate
    assert [
        tuple(row) for row in _rows(repo.db_path, "SELECT * FROM audit_log")
    ] == before_audit
