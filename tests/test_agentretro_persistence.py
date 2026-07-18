import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import _path  # noqa: F401
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.application.bootstrap import build_retro_repository
from agent_retro.domain.models import (
    AuditEntry,
    Candidate,
    CandidateStatus,
    Evidence,
    KnowledgeConflict,
    KnowledgeType,
    NormalizedSession,
    ProjectMapping,
    PurgeOperation,
    PurgePlan,
    PurgeStatus,
    ReviewAttempt,
    ReviewResult,
    ReviewVerdict,
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
        status="captured",
        completed_at=NOW,
        captured_at=NOW + timedelta(minutes=1),
    )


def _evidence() -> Evidence:
    return Evidence(
        id="evidence-1",
        session_id="session-1",
        kind="user_instruction",
        event_id="event-1",
        content_hash="evidence-hash-1",
        excerpt="Keep persistence isolated.",
    )


def _candidate() -> Candidate:
    return Candidate(
        id="candidate-1",
        session_id="session-1",
        knowledge_type=KnowledgeType.RULE,
        project_id="project-1",
        scope="project",
        proposed_text="Use an isolated database.",
        status=CandidateStatus.PENDING,
        extraction_confidence=0.98,
        evidence_ids=("evidence-1",),
        created_at=NOW + timedelta(minutes=2),
        updated_at=NOW + timedelta(minutes=2),
    )


def _mapping(mapping_id: str = "mapping-1") -> ProjectMapping:
    return ProjectMapping(
        id=mapping_id,
        git_root=Path("D:/projects/example"),
        remote_identity="example/repository",
        obsidian_project="Projects/Example",
        active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _rows(db_path: Path, sql: str, parameters=()):
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(sql, parameters).fetchall()


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
        duplicate=False,
        conflict=False,
    )
    repo.save_review(candidate.id, result)
    attempt = repo.begin_review_attempt(
        ReviewAttempt(
            id="attempt-1",
            candidate_id=candidate.id,
            input_hash="review-input-hash",
            attempt_no=1,
            status="running",
            created_at=NOW + timedelta(minutes=3),
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
    assert reviewed.review == result
    assert repo.list_candidates(CandidateStatus.ACCEPTED) == [reviewed]
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
            created_at=NOW,
        )
    )
    repo.begin_sync(
        SyncJob(
            id="sync-1",
            project_id="project-1",
            status="running",
            plan_json='{"targets":[]}',
            backup_path=Path("backups/sync-1"),
            created_at=NOW,
            updated_at=NOW,
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
        created_at=mapping.created_at,
        updated_at=saved_mapping.updated_at,
    )
    assert abs(saved_mapping.updated_at - mapping.updated_at) <= timedelta(days=1)
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
                status="planned",
            ),
        ),
        status=PurgeStatus.PLANNED,
        created_at=NOW,
        updated_at=NOW,
    )

    repo.save_purge_plan(plan, plan_hash="plan-hash", actor="tester")
    repo.finish_purge(
        plan.id,
        status=PurgeStatus.COMPLETED,
        tombstone_json='{"knowledge_id":"knowledge-1"}',
        residual_json="[]",
    )

    job = _rows(repo.db_path, "SELECT * FROM purge_jobs WHERE id = 'purge-1'")[0]
    operation = _rows(repo.db_path, "SELECT * FROM purge_operations")[0]
    assert job["status"] == PurgeStatus.COMPLETED.value
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
        detail={"reason": "test"},
        created_at=NOW,
    )

    repo.append_audit(entry)

    rows = _rows(repo.db_path, "SELECT * FROM audit_log WHERE id = ?", (entry.id,))
    assert len(rows) == 1
    assert rows[0]["actor"] == entry.actor
    assert rows[0]["detail_json"] == '{"reason":"test"}'
