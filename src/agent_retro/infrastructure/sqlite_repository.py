"""SQLite persistence with versioned, backup-first migrations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

from agent_retro.application.ports import RetroRepository
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
    ProjectionStatus,
    PurgePlan,
    PurgeStatus,
    ReviewAttempt,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
    SyncJob,
)


_SCHEMA_VERSION = 1

_SCHEMA_V1 = (
    "CREATE TABLE schema_version (version INTEGER NOT NULL)",
    """CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        source_session_id TEXT NOT NULL,
        source_path TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        project_id TEXT NOT NULL,
        status TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        captured_at TEXT NOT NULL,
        UNIQUE(source_session_id, source_hash)
    )""",
    """CREATE TABLE session_events (
        session_id TEXT NOT NULL REFERENCES sessions(id),
        id TEXT NOT NULL,
        kind TEXT NOT NULL,
        content TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        locator_session_id TEXT NOT NULL,
        locator_event_id TEXT NOT NULL,
        locator_source_path TEXT NOT NULL,
        locator_content_hash TEXT NOT NULL,
        PRIMARY KEY(session_id, id),
        UNIQUE(session_id, ordinal)
    )""",
    """CREATE TABLE evidence (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        kind TEXT NOT NULL,
        locator_session_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        locator_source_path TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        excerpt TEXT NOT NULL,
        UNIQUE(session_id, event_id, content_hash)
    )""",
    """CREATE TABLE candidates (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        knowledge_type TEXT NOT NULL,
        project_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        proposed_text TEXT NOT NULL,
        status TEXT NOT NULL,
        extraction_confidence REAL NOT NULL,
        review_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE candidate_evidence (
        candidate_id TEXT NOT NULL REFERENCES candidates(id),
        evidence_id TEXT NOT NULL REFERENCES evidence(id),
        PRIMARY KEY(candidate_id, evidence_id)
    )""",
    """CREATE TABLE knowledge (
        id TEXT NOT NULL,
        version INTEGER NOT NULL,
        candidate_id TEXT NOT NULL,
        knowledge_type TEXT NOT NULL,
        project_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        text TEXT NOT NULL,
        status TEXT NOT NULL,
        confidence REAL NOT NULL,
        accepted_by TEXT NOT NULL,
        valid_until TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY(id, version)
    )""",
    """CREATE TABLE knowledge_evidence (
        knowledge_id TEXT NOT NULL,
        knowledge_version INTEGER NOT NULL,
        evidence_id TEXT NOT NULL REFERENCES evidence(id),
        PRIMARY KEY(knowledge_id, knowledge_version, evidence_id)
    )""",
    """CREATE TABLE conflicts (
        id TEXT PRIMARY KEY,
        active_knowledge_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        merge_text TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )""",
    """CREATE TABLE sync_jobs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        status TEXT NOT NULL,
        plan_json TEXT NOT NULL,
        backup_path TEXT NOT NULL,
        error TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE review_attempts (
        id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL REFERENCES candidates(id),
        input_hash TEXT NOT NULL,
        attempt_no INTEGER NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT NOT NULL,
        error TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(candidate_id, attempt_no)
    )""",
    """CREATE TABLE project_mappings (
        id TEXT PRIMARY KEY,
        git_root TEXT NOT NULL,
        remote_identity TEXT NOT NULL,
        obsidian_project TEXT NOT NULL,
        active INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE UNIQUE INDEX uq_active_mapping_root
        ON project_mappings(git_root) WHERE active = 1""",
    """CREATE UNIQUE INDEX uq_active_mapping_remote
        ON project_mappings(remote_identity) WHERE active = 1""",
    """CREATE TABLE projection_events (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        cause TEXT NOT NULL,
        cause_entity_id TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        error TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(project_id, cause, cause_entity_id, input_hash)
    )""",
    """CREATE TABLE managed_file_state (
        path TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        managed_hash TEXT NOT NULL,
        full_hash TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE purge_jobs (
        id TEXT PRIMARY KEY,
        knowledge_id TEXT NOT NULL,
        plan_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        tombstone_json TEXT NOT NULL,
        residual_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE purge_operations (
        id TEXT PRIMARY KEY,
        purge_job_id TEXT NOT NULL REFERENCES purge_jobs(id),
        location_kind TEXT NOT NULL,
        location TEXT NOT NULL,
        expected_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        error TEXT NOT NULL
    )""",
    """CREATE TABLE audit_log (
        id TEXT PRIMARY KEY,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        before_hash TEXT NOT NULL,
        after_hash TEXT NOT NULL,
        detail_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
)


class SQLiteRetroRepository(RetroRepository):
    """SQLite implementation of the AgentRetro persistence port."""

    def __init__(self, db_path: Path, backup_dir: Path) -> None:
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection
        except BaseException:
            try:
                connection.close()
            except BaseException:
                pass
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit all work on success and roll it all back on error."""

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def schema_version(self) -> int:
        if not self.db_path.exists():
            return 0
        connection = self._connect()
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'schema_version'"
            ).fetchone()
            if exists is None:
                return 0
            row = connection.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            return 0 if row is None else int(row[0])
        finally:
            connection.close()

    def table_names(self) -> list[str]:
        if not self.db_path.exists():
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            connection.close()

    def migrate(self, target_version: int = _SCHEMA_VERSION) -> None:
        """Migrate after a byte-for-byte backup, restoring it on failure."""

        if target_version < 1:
            raise ValueError("target_version must be at least 1")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        database_existed = self.db_path.exists()
        connection: sqlite3.Connection | None = None
        backup_path: Path | None = None
        backup_hash: str | None = None
        try:
            current_version = self.schema_version()
            if current_version == target_version:
                return
            if current_version > target_version:
                raise ValueError("database downgrades are not supported")

            if database_existed:
                self._prepare_database_for_backup()
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup_path = self.backup_dir / (
                    f"migration-{current_version}-to-{target_version}-{stamp}.db"
                )
                shutil.copy2(self.db_path, backup_path)
                backup_hash = _sha256_file(backup_path)

            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            for version in range(current_version + 1, target_version + 1):
                self._apply_migration(connection, version)
                self._append_audit_record(
                    connection,
                    self._audit_entry(
                        action="migration_applied",
                        entity_type="schema",
                        entity_id=str(version),
                        before_hash=str(version - 1),
                        after_hash=str(version),
                        detail={"from": version - 1, "to": version},
                    ),
                )
            connection.commit()
        except BaseException:
            if connection is not None:
                try:
                    connection.rollback()
                except BaseException:
                    pass
                try:
                    connection.close()
                except BaseException:
                    pass
            if backup_path is not None and backup_hash is not None:
                self._restore_backup(backup_path, backup_hash)
            elif not database_existed:
                self._remove_failed_database()
            raise
        else:
            connection.close()

    def _apply_migration(
        self, connection: sqlite3.Connection, version: int
    ) -> None:
        if version != 1:
            raise ValueError(f"unsupported schema migration: {version}")
        for statement in _SCHEMA_V1:
            connection.execute(statement)
        connection.execute("INSERT INTO schema_version(version) VALUES (1)")

    def _restore_backup(self, backup_path: Path, expected_hash: str) -> None:
        restore_path = self.db_path.with_name(f".{self.db_path.name}.restore")
        self._remove_database_sidecars()
        try:
            shutil.copy2(backup_path, restore_path)
            if _sha256_file(restore_path) != expected_hash:
                raise RuntimeError("migration backup copy hash mismatch")
            os.replace(restore_path, self.db_path)
            if _sha256_file(self.db_path) != expected_hash:
                raise RuntimeError("migration backup restoration hash mismatch")
            self._verify_database_readback()
        finally:
            restore_path.unlink(missing_ok=True)
            self._remove_database_sidecars()

    def _prepare_database_for_backup(self) -> None:
        """Recover journals and checkpoint WAL before copying the main file."""

        connection = self._connect()
        try:
            checkpoint = connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            if checkpoint is not None and int(checkpoint[0]) != 0:
                raise RuntimeError("database WAL checkpoint is busy")
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result is None or str(result[0]).lower() != "ok":
                raise RuntimeError("database failed pre-migration readback")
        finally:
            connection.close()
        self._remove_database_sidecars()

    def _verify_database_readback(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result is None or str(result[0]).lower() != "ok":
                raise RuntimeError("restored database failed readback")
        finally:
            connection.close()

    def _remove_database_sidecars(self) -> None:
        for path in (
            Path(f"{self.db_path}-journal"),
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            path.unlink(missing_ok=True)

    def _remove_failed_database(self) -> None:
        self.db_path.unlink(missing_ok=True)
        self._remove_database_sidecars()

    def find_session(
        self, source_session_id: str, source_hash: str
    ) -> NormalizedSession | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM sessions WHERE source_session_id = ? "
                "AND source_hash = ?",
                (source_session_id, source_hash),
            ).fetchone()
            if row is None:
                return None
            event_rows = connection.execute(
                "SELECT * FROM session_events WHERE session_id = ? "
                "ORDER BY ordinal",
                (row["id"],),
            ).fetchall()
            return _session_from_row(
                row, tuple(_event_from_row(event_row) for event_row in event_rows)
            )
        finally:
            connection.close()

    def find_session_by_source_id(
        self, source_session_id: str
    ) -> NormalizedSession | None:
        """Return an existing source identity regardless of its content hash.

        This concrete-adapter query lets capture distinguish a strict replay
        from a changed source without widening the fixed application port.
        """

        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM sessions WHERE source_session_id = ? "
                "ORDER BY captured_at LIMIT 1",
                (source_session_id,),
            ).fetchone()
            if row is None:
                return None
            event_rows = connection.execute(
                "SELECT * FROM session_events WHERE session_id = ? "
                "ORDER BY ordinal",
                (row["id"],),
            ).fetchall()
            return _session_from_row(
                row,
                tuple(_event_from_row(event_row) for event_row in event_rows),
            )
        finally:
            connection.close()

    def save_capture(
        self, session: NormalizedSession, evidence: Sequence[Evidence]
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO sessions(
                    id, source_session_id, source_path, source_hash, project_id,
                    status, completed_at, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id,
                    session.source_session_id,
                    str(session.source_path),
                    session.source_hash,
                    session.project_id,
                    "completed" if session.completed else "active",
                    _datetime_text(session.completed_at),
                    _now_text(),
                ),
            )
            for ordinal, event in enumerate(session.events):
                connection.execute(
                    """INSERT INTO session_events(
                        session_id, id, kind, content, ordinal,
                        locator_session_id, locator_event_id,
                        locator_source_path, locator_content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session.id,
                        event.id,
                        event.kind,
                        event.content,
                        ordinal,
                        event.locator.session_id,
                        event.locator.event_id,
                        event.locator.source_path,
                        event.locator.content_hash,
                    ),
                )
            for item in evidence:
                if item.session_id != session.id:
                    raise ValueError("evidence session_id does not match session")
                connection.execute(
                    """INSERT INTO evidence(
                        id, session_id, kind, locator_session_id, event_id,
                        locator_source_path, content_hash, excerpt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item.id,
                        item.session_id,
                        item.kind,
                        item.locator.session_id,
                        item.locator.event_id,
                        item.locator.source_path,
                        item.locator.content_hash,
                        item.excerpt,
                    ),
                )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="capture_saved",
                    entity_type="session",
                    entity_id=session.id,
                    after_hash=session.source_hash,
                    detail={"evidence_count": len(evidence)},
                ),
            )

    def list_evidence(self, session_id: str) -> list[Evidence]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM evidence WHERE session_id = ? ORDER BY rowid",
                (session_id,),
            ).fetchall()
            return [_evidence_from_row(row) for row in rows]
        finally:
            connection.close()

    def save_candidates(self, candidates: Sequence[Candidate]) -> None:
        with self.transaction() as connection:
            for candidate in candidates:
                session_id = self._candidate_session_id(connection, candidate)
                now = _now_text()
                connection.execute(
                    """INSERT INTO candidates(
                        id, session_id, knowledge_type, project_id, scope,
                        proposed_text, status, extraction_confidence,
                        review_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        candidate.id,
                        session_id,
                        candidate.knowledge_type.value,
                        candidate.project_id,
                        candidate.scope,
                        candidate.proposed_text,
                        candidate.status.value,
                        candidate.extraction_confidence,
                        _review_to_json(None),
                        now,
                        now,
                    ),
                )
                connection.executemany(
                    "INSERT INTO candidate_evidence(candidate_id, evidence_id) "
                    "VALUES (?, ?)",
                    ((candidate.id, evidence_id) for evidence_id in candidate.evidence_ids),
                )
            ids = [candidate.id for candidate in candidates]
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="candidates_saved",
                    entity_type="candidate_batch",
                    entity_id=",".join(ids),
                    after_hash=_hash_value(ids),
                    detail={"count": len(ids)},
                ),
            )

    def _candidate_session_id(
        self, connection: sqlite3.Connection, candidate: Candidate
    ) -> str:
        if not candidate.evidence_ids:
            raise ValueError("candidate must reference evidence")
        placeholders = ",".join("?" for _ in candidate.evidence_ids)
        rows = connection.execute(
            f"SELECT id, session_id FROM evidence WHERE id IN ({placeholders})",
            candidate.evidence_ids,
        ).fetchall()
        if len(rows) != len(set(candidate.evidence_ids)):
            raise ValueError("candidate references unknown evidence")
        session_ids = {str(row["session_id"]) for row in rows}
        if len(session_ids) != 1:
            raise ValueError("candidate evidence must belong to one session")
        return session_ids.pop()

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        connection = self._connect()
        try:
            return self._get_candidate(connection, candidate_id)
        finally:
            connection.close()

    def _get_candidate(
        self, connection: sqlite3.Connection, candidate_id: str
    ) -> Candidate | None:
        row = connection.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            return None
        evidence_rows = connection.execute(
            "SELECT evidence_id FROM candidate_evidence "
            "WHERE candidate_id = ? ORDER BY evidence_id",
            (candidate_id,),
        ).fetchall()
        return _candidate_from_row(
            row, tuple(str(item[0]) for item in evidence_rows)
        )

    def list_candidates(self, status: CandidateStatus) -> list[Candidate]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id FROM candidates WHERE status = ? "
                "ORDER BY created_at, id",
                (status.value,),
            ).fetchall()
            return [
                candidate
                for row in rows
                if (candidate := self._get_candidate(connection, str(row[0])))
                is not None
            ]
        finally:
            connection.close()

    def save_review(self, candidate_id: str, result: ReviewResult) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE candidates SET review_json = ?, updated_at = ? WHERE id = ?",
                (_review_to_json(result), _now_text(), candidate_id),
            )
            _require_row(cursor, "candidate", candidate_id)
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="review_saved",
                    entity_type="candidate",
                    entity_id=candidate_id,
                    after_hash=_hash_value(asdict(result)),
                    detail={"verdict": result.verdict.value},
                ),
            )

    def begin_review_attempt(self, attempt: ReviewAttempt) -> ReviewAttempt:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO review_attempts(
                    id, candidate_id, input_hash, attempt_no, status,
                    result_json, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt.id,
                    attempt.candidate_id,
                    attempt.input_hash,
                    self._next_review_attempt_no(connection, attempt.candidate_id),
                    attempt.status,
                    attempt.result_json,
                    attempt.error,
                    _now_text(),
                ),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="review_attempt_started",
                    entity_type="review_attempt",
                    entity_id=attempt.id,
                    after_hash=attempt.input_hash,
                    detail={"candidate_id": attempt.candidate_id},
                ),
            )
        return attempt

    def _next_review_attempt_no(
        self, connection: sqlite3.Connection, candidate_id: str
    ) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM review_attempts "
            "WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        return int(row[0])

    def finish_review_attempt(
        self,
        attempt_id: str,
        status: str,
        result_json: str = "",
        error: str = "",
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE review_attempts SET status = ?, result_json = ?, "
                "error = ? WHERE id = ?",
                (status, result_json, error, attempt_id),
            )
            _require_row(cursor, "review attempt", attempt_id)
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="review_attempt_finished",
                    entity_type="review_attempt",
                    entity_id=attempt_id,
                    after_hash=_hash_value(
                        {"status": status, "result_json": result_json, "error": error}
                    ),
                    detail={"status": status, "has_error": bool(error)},
                ),
            )

    def accept_candidate(
        self, candidate_id: str, text: str, actor: str, confidence: float
    ) -> Knowledge:
        with self.transaction() as connection:
            candidate = self._get_candidate(connection, candidate_id)
            if candidate is None:
                raise KeyError(f"candidate not found: {candidate_id}")
            existing = connection.execute(
                "SELECT * FROM knowledge WHERE candidate_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (candidate_id,),
            ).fetchone()
            if existing is not None:
                knowledge = self._knowledge_from_row(connection, existing)
                if (
                    knowledge.text != text
                    or knowledge.accepted_by != actor
                    or knowledge.confidence != confidence
                ):
                    raise ValueError(
                        f"candidate {candidate_id} conflicts with accepted knowledge"
                    )
                return knowledge
            else:
                updated_at = datetime.now(timezone.utc)
                knowledge = Knowledge(
                    id=f"knowledge-{candidate.id}",
                    version=1,
                    candidate_id=candidate.id,
                    knowledge_type=candidate.knowledge_type,
                    project_id=candidate.project_id,
                    scope=candidate.scope,
                    text=text,
                    status="active",
                    confidence=confidence,
                    accepted_by=actor,
                    evidence_ids=candidate.evidence_ids,
                    valid_until=None,
                    updated_at=updated_at,
                )
                connection.execute(
                    """INSERT INTO knowledge(
                        id, version, candidate_id, knowledge_type, project_id,
                        scope, text, status, confidence, accepted_by,
                        valid_until, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        knowledge.id,
                        knowledge.version,
                        knowledge.candidate_id,
                        knowledge.knowledge_type.value,
                        knowledge.project_id,
                        knowledge.scope,
                        knowledge.text,
                        knowledge.status,
                        knowledge.confidence,
                        knowledge.accepted_by,
                        _optional_datetime_text(knowledge.valid_until),
                        _datetime_text(knowledge.updated_at),
                    ),
                )
                connection.executemany(
                    """INSERT INTO knowledge_evidence(
                        knowledge_id, knowledge_version, evidence_id
                    ) VALUES (?, ?, ?)""",
                    (
                        (knowledge.id, knowledge.version, evidence_id)
                        for evidence_id in knowledge.evidence_ids
                    ),
                )
            connection.execute(
                "UPDATE candidates SET status = ?, updated_at = ? WHERE id = ?",
                (CandidateStatus.ACCEPTED.value, _now_text(), candidate_id),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="candidate_accepted",
                    entity_type="knowledge",
                    entity_id=knowledge.id,
                    before_hash=_hash_value(candidate),
                    after_hash=_hash_value(knowledge),
                    detail={"candidate_id": candidate_id},
                ),
            )
        return knowledge

    def list_active_knowledge(
        self, project_id: str, at: datetime
    ) -> list[Knowledge]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT * FROM knowledge
                WHERE project_id = ? AND status = 'active'
                  AND (valid_until IS NULL OR valid_until > ?)
                ORDER BY created_at, id, version""",
                (project_id, _datetime_text(at)),
            ).fetchall()
            return [self._knowledge_from_row(connection, row) for row in rows]
        finally:
            connection.close()

    def _knowledge_from_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> Knowledge:
        evidence_rows = connection.execute(
            """SELECT evidence_id FROM knowledge_evidence
            WHERE knowledge_id = ? AND knowledge_version = ?
            ORDER BY evidence_id""",
            (row["id"], row["version"]),
        ).fetchall()
        return Knowledge(
            id=str(row["id"]),
            version=int(row["version"]),
            candidate_id=str(row["candidate_id"]),
            knowledge_type=KnowledgeType(row["knowledge_type"]),
            project_id=str(row["project_id"]),
            scope=str(row["scope"]),
            text=str(row["text"]),
            status=str(row["status"]),
            confidence=float(row["confidence"]),
            accepted_by=str(row["accepted_by"]),
            evidence_ids=tuple(str(item[0]) for item in evidence_rows),
            valid_until=_optional_datetime(row["valid_until"]),
            updated_at=_datetime(row["created_at"]),
        )

    def save_conflict(self, conflict: KnowledgeConflict) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO conflicts(
                    id, active_knowledge_id, candidate_id, reason, merge_text,
                    status, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    conflict.id,
                    conflict.active_knowledge_id,
                    conflict.candidate_id,
                    conflict.reason,
                    conflict.merge_text,
                    conflict.status,
                    _now_text(),
                    None,
                ),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="conflict_saved",
                    entity_type="conflict",
                    entity_id=conflict.id,
                    after_hash=_hash_value(conflict),
                    detail={"candidate_id": conflict.candidate_id},
                ),
            )

    def begin_sync(self, job: SyncJob) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO sync_jobs(
                    id, project_id, status, plan_json, backup_path, error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.id,
                    job.project_id,
                    job.status,
                    job.plan_json,
                    str(job.backup_path),
                    job.error,
                    _now_text(),
                    _now_text(),
                ),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="sync_started",
                    entity_type="sync_job",
                    entity_id=job.id,
                    after_hash=_hash_value(job),
                    detail={"project_id": job.project_id},
                ),
            )

    def finish_sync(self, job_id: str, status: str, error: str = "") -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE sync_jobs SET status = ?, error = ?, updated_at = ? "
                "WHERE id = ?",
                (status, error, _now_text(), job_id),
            )
            _require_row(cursor, "sync job", job_id)
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="sync_finished",
                    entity_type="sync_job",
                    entity_id=job_id,
                    after_hash=_hash_value({"status": status, "error": error}),
                    detail={"status": status, "has_error": bool(error)},
                ),
            )

    def save_project_mapping(self, mapping: ProjectMapping, actor: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO project_mappings(
                    id, git_root, remote_identity, obsidian_project, active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    git_root = excluded.git_root,
                    remote_identity = excluded.remote_identity,
                    obsidian_project = excluded.obsidian_project,
                    active = excluded.active,
                    updated_at = excluded.updated_at""",
                (
                    mapping.id,
                    str(mapping.git_root),
                    mapping.remote_identity,
                    mapping.obsidian_project,
                    int(mapping.active),
                    _now_text(),
                    _now_text(),
                ),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="project_mapping_saved",
                    entity_type="project_mapping",
                    entity_id=mapping.id,
                    after_hash=_hash_value(mapping),
                    detail={"active": mapping.active},
                ),
            )

    def list_project_mappings(
        self, active_only: bool = True
    ) -> list[ProjectMapping]:
        connection = self._connect()
        try:
            sql = "SELECT * FROM project_mappings"
            parameters: tuple[int, ...] = ()
            if active_only:
                sql += " WHERE active = ?"
                parameters = (1,)
            sql += " ORDER BY created_at, id"
            rows = connection.execute(sql, parameters).fetchall()
            return [
                ProjectMapping(
                    id=str(row["id"]),
                    git_root=Path(row["git_root"]),
                    remote_identity=str(row["remote_identity"]),
                    obsidian_project=str(row["obsidian_project"]),
                    active=bool(row["active"]),
                )
                for row in rows
            ]
        finally:
            connection.close()

    def deactivate_project_mapping(self, mapping_id: str, actor: str) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE project_mappings SET active = 0, updated_at = ? "
                "WHERE id = ?",
                (_now_text(), mapping_id),
            )
            _require_row(cursor, "project mapping", mapping_id)
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="project_mapping_deactivated",
                    entity_type="project_mapping",
                    entity_id=mapping_id,
                    after_hash=_hash_value({"active": False}),
                    detail={},
                ),
            )

    def reclassify_session(
        self,
        session_id: str,
        project_id: str,
        mapping_id: str,
        actor: str,
    ) -> str:
        """Assign an awaiting session after its stored evidence was reviewed."""

        with self.transaction() as connection:
            mapping = connection.execute(
                "SELECT obsidian_project FROM project_mappings "
                "WHERE id = ? AND active = 1",
                (mapping_id,),
            ).fetchone()
            if mapping is None:
                raise ValueError(f"project mapping not found: {mapping_id}")
            if str(mapping["obsidian_project"]) != project_id:
                raise ValueError(
                    f"project mapping target mismatch: {mapping_id}"
                )
            row = connection.execute(
                "SELECT id, project_id FROM sessions "
                "WHERE source_session_id = ? OR id = ? "
                "ORDER BY captured_at LIMIT 1",
                (session_id, session_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"session not found: {session_id}")
            before_project = str(row["project_id"])
            if not before_project.startswith("awaiting:"):
                raise ValueError(
                    f"session is not awaiting classification: {session_id}"
                )
            internal_session_id = str(row["id"])
            connection.execute(
                "UPDATE sessions SET project_id = ? WHERE id = ?",
                (project_id, internal_session_id),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="session_reclassified",
                    entity_type="session",
                    entity_id=internal_session_id,
                    before_hash=_hash_value({"project_id": before_project}),
                    after_hash=_hash_value({"project_id": project_id}),
                    detail={"mapping_id": mapping_id},
                ),
            )
            return internal_session_id

    def save_projection_event(
        self,
        event_id: str,
        project_id: str,
        cause: str,
        cause_entity_id: str,
        input_hash: str,
    ) -> str:
        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT id FROM projection_events
                WHERE project_id = ? AND cause = ? AND cause_entity_id = ?
                  AND input_hash = ?""",
                (project_id, cause, cause_entity_id, input_hash),
            ).fetchone()
            stored_id = str(existing[0]) if existing is not None else event_id
            if existing is None:
                now = _now_text()
                connection.execute(
                    """INSERT INTO projection_events(
                        id, project_id, cause, cause_entity_id, input_hash,
                        status, error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id,
                        project_id,
                        cause,
                        cause_entity_id,
                        input_hash,
                        ProjectionStatus.SYNC_PENDING.value,
                        "",
                        now,
                        now,
                    ),
                )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="projection_event_saved",
                    entity_type="projection_event",
                    entity_id=stored_id,
                    after_hash=input_hash,
                    detail={"duplicate": existing is not None},
                ),
            )
        return stored_id

    def save_managed_file_state(
        self,
        project_id: str,
        path: Path,
        managed_hash: str,
        full_hash: str,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO managed_file_state(
                    path, project_id, managed_hash, full_hash, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    project_id = excluded.project_id,
                    managed_hash = excluded.managed_hash,
                    full_hash = excluded.full_hash,
                    updated_at = excluded.updated_at""",
                (str(path), project_id, managed_hash, full_hash, _now_text()),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="managed_file_state_saved",
                    entity_type="managed_file",
                    entity_id=str(path),
                    after_hash=full_hash,
                    detail={"project_id": project_id, "managed_hash": managed_hash},
                ),
            )

    def save_purge_plan(
        self, plan: PurgePlan, plan_hash: str, actor: str
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO purge_jobs(
                    id, knowledge_id, plan_hash, status, tombstone_json,
                    residual_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.id,
                    plan.knowledge_id,
                    plan_hash,
                    plan.status.value,
                    "",
                    "",
                    _now_text(),
                    _now_text(),
                ),
            )
            for operation in plan.operations:
                connection.execute(
                    """INSERT INTO purge_operations(
                        id, purge_job_id, location_kind, location,
                        expected_hash, status, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        operation.id,
                        plan.id,
                        operation.location_kind,
                        operation.location,
                        operation.expected_hash,
                        "planned",
                        "",
                    ),
                )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="purge_planned",
                    entity_type="purge_job",
                    entity_id=plan.id,
                    after_hash=plan_hash,
                    detail={"operation_count": len(plan.operations)},
                ),
            )

    def finish_purge(
        self,
        plan_id: str,
        status: PurgeStatus,
        tombstone_json: str,
        residual_json: str,
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE purge_jobs
                SET status = ?, tombstone_json = ?, residual_json = ?,
                    updated_at = ?
                WHERE id = ?""",
                (
                    status.value,
                    tombstone_json,
                    residual_json,
                    _now_text(),
                    plan_id,
                ),
            )
            _require_row(cursor, "purge plan", plan_id)
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="purge_finished",
                    entity_type="purge_job",
                    entity_id=plan_id,
                    after_hash=_hash_value(
                        {
                            "status": status.value,
                            "tombstone_json": tombstone_json,
                            "residual_json": residual_json,
                        }
                    ),
                    detail={"status": status.value},
                ),
            )

    def append_audit(self, entry: AuditEntry) -> None:
        with self.transaction() as connection:
            self._append_audit_record(connection, entry)

    def _append_audit_record(
        self, connection: sqlite3.Connection, entry: AuditEntry
    ) -> None:
        connection.execute(
            """INSERT INTO audit_log(
                id, actor, action, entity_type, entity_id, before_hash,
                after_hash, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.actor,
                entry.action,
                entry.entity_type,
                entry.entity_id,
                entry.before_hash,
                entry.after_hash,
                entry.detail_json,
                _datetime_text(entry.created_at),
            ),
        )

    def _audit_entry(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        before_hash: str = "",
        after_hash: str = "",
        detail: Mapping[str, Any],
        actor: str = "system",
    ) -> AuditEntry:
        return AuditEntry(
            id=str(uuid4()),
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_hash=before_hash,
            after_hash=after_hash,
            detail_json=_json_text(detail),
            created_at=datetime.now(timezone.utc),
        )


def _require_row(cursor: sqlite3.Cursor, entity_type: str, entity_id: str) -> None:
    if cursor.rowcount == 0:
        raise KeyError(f"{entity_type} not found: {entity_id}")


def _session_from_row(
    row: sqlite3.Row, events: tuple[NormalizedEvent, ...]
) -> NormalizedSession:
    return NormalizedSession(
        id=str(row["id"]),
        source_session_id=str(row["source_session_id"]),
        source_path=Path(row["source_path"]),
        source_hash=str(row["source_hash"]),
        project_id=str(row["project_id"]),
        completed=str(row["status"]) == "completed",
        completed_at=_datetime(row["completed_at"]),
        events=events,
    )


def _event_from_row(row: sqlite3.Row) -> NormalizedEvent:
    return NormalizedEvent(
        id=str(row["id"]),
        kind=str(row["kind"]),
        content=str(row["content"]),
        locator=SourceLocator(
            session_id=str(row["locator_session_id"]),
            event_id=str(row["locator_event_id"]),
            source_path=str(row["locator_source_path"]),
            content_hash=str(row["locator_content_hash"]),
        ),
    )


def _evidence_from_row(row: sqlite3.Row) -> Evidence:
    return Evidence(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        kind=str(row["kind"]),
        locator=SourceLocator(
            session_id=str(row["locator_session_id"]),
            event_id=str(row["event_id"]),
            source_path=str(row["locator_source_path"]),
            content_hash=str(row["content_hash"]),
        ),
        excerpt=str(row["excerpt"]),
    )


def _candidate_from_row(
    row: sqlite3.Row, evidence_ids: tuple[str, ...]
) -> Candidate:
    return Candidate(
        id=str(row["id"]),
        knowledge_type=KnowledgeType(row["knowledge_type"]),
        project_id=str(row["project_id"]),
        scope=str(row["scope"]),
        proposed_text=str(row["proposed_text"]),
        status=CandidateStatus(row["status"]),
        extraction_confidence=float(row["extraction_confidence"]),
        evidence_ids=evidence_ids,
    )


def _review_to_json(result: ReviewResult | None) -> str:
    if result is None:
        return "{}"
    return _json_text(
        {
            "verdict": result.verdict.value,
            "confidence": result.confidence,
            "reason": result.reason,
            "normalized_text": result.normalized_text,
            "duplicate_of": result.duplicate_of,
            "conflict_with": result.conflict_with,
        }
    )


def _review_from_json(value: str) -> ReviewResult | None:
    data = json.loads(value or "{}")
    if not data:
        return None
    return ReviewResult(
        verdict=ReviewVerdict(data["verdict"]),
        confidence=float(data["confidence"]),
        reason=str(data["reason"]),
        normalized_text=str(data["normalized_text"]),
        duplicate_of=(
            None if data.get("duplicate_of") is None else str(data["duplicate_of"])
        ),
        conflict_with=(
            None if data.get("conflict_with") is None else str(data["conflict_with"])
        ),
    )


def _datetime_text(value: datetime) -> str:
    return value.isoformat()


def _optional_datetime_text(value: datetime | None) -> str | None:
    return None if value is None else _datetime_text(value)


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _optional_datetime(value: str | None) -> datetime | None:
    return None if value is None else _datetime(value)


def _now_text() -> str:
    return _datetime_text(datetime.now(timezone.utc))


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, Path)):
        return str(value) if isinstance(value, Path) else value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
