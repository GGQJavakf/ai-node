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
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import uuid4

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import (
    AcceptanceDecision,
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
    Reclassification,
    ManagedFileState,
    ManagedFileSnapshot,
    ManagedFileUpdate,
    ProjectionEvent,
    ProjectionStatus,
    PurgeOperation,
    PurgePlan,
    PurgeCopy,
    PurgeInspection,
    PurgeJournal,
    PurgeJournalOperation,
    PurgeStatus,
    PurgeTombstone,
    ReviewAttempt,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
    SyncJob,
    VaultAdoption,
)
from agent_retro.domain.projection import ProjectionFenceError, projection_input_hash
from agent_retro.infrastructure.obsidian import render_aggregate


_SCHEMA_VERSION = 2

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

_SCHEMA_V2 = (
    """CREATE TABLE vault_adoptions (
        candidate_id TEXT PRIMARY KEY REFERENCES candidates(id),
        project_id TEXT NOT NULL,
        knowledge_id TEXT NOT NULL,
        original_version INTEGER NOT NULL,
        original_text_hash TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        vault_managed_hash TEXT NOT NULL,
        vault_full_hash TEXT NOT NULL,
        authority_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        blocker TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE managed_file_snapshots (
        path TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        snapshot_kind TEXT NOT NULL,
        owned_bytes BLOB NOT NULL,
        managed_hash TEXT NOT NULL,
        full_hash TEXT NOT NULL,
        event_id TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
)

_PURGE_SQLITE_FIELDS = (
    ("sqlite_knowledge", "knowledge", "id || ':' || version", "text"),
    ("sqlite_candidate", "candidates", "id", "proposed_text"),
    ("sqlite_candidate", "candidates", "id", "review_json"),
    ("sqlite_evidence", "evidence", "id", "excerpt"),
    ("sqlite_review", "review_attempts", "id", "result_json"),
    ("sqlite_review", "review_attempts", "id", "error"),
    ("sqlite_conflict", "conflicts", "id", "reason"),
    ("sqlite_conflict", "conflicts", "id", "merge_text"),
    ("sqlite_projection", "projection_events", "id", "input_hash"),
    ("sqlite_projection", "projection_events", "id", "error"),
    ("sqlite_projection", "sync_jobs", "id", "plan_json"),
    ("sqlite_projection", "sync_jobs", "id", "error"),
    ("sqlite_projection", "managed_file_snapshots", "path", "owned_bytes"),
    ("sqlite_audit", "audit_log", "id", "detail_json"),
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

    def _apply_migration(self, connection: sqlite3.Connection, version: int) -> None:
        if version == 1:
            for statement in _SCHEMA_V1:
                connection.execute(statement)
            connection.execute("INSERT INTO schema_version(version) VALUES (1)")
            return
        if version == 2:
            for statement in _SCHEMA_V2:
                connection.execute(statement)
            connection.execute("UPDATE schema_version SET version = 2")
            return
        raise ValueError(f"unsupported schema migration: {version}")

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
                "SELECT * FROM session_events WHERE session_id = ? ORDER BY ordinal",
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

        This mandatory repository query lets capture distinguish a strict
        replay from a changed source through the typed application port.
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
                "SELECT * FROM session_events WHERE session_id = ? ORDER BY ordinal",
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
                    (
                        (candidate.id, evidence_id)
                        for evidence_id in candidate.evidence_ids
                    ),
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
            """SELECT ce.evidence_id, e.kind FROM candidate_evidence ce
            JOIN evidence e ON e.id = ce.evidence_id
            WHERE ce.candidate_id = ? ORDER BY ce.evidence_id""",
            (candidate_id,),
        ).fetchall()
        return _candidate_from_row(row, tuple(str(item[0]) for item in evidence_rows))

    def save_manual_edit_candidate(
        self,
        candidate: Candidate,
        *,
        relative_path: Path,
        content_hash: str,
        adoption: VaultAdoption | None = None,
    ) -> Candidate:
        """Atomically persist synthetic provenance and one pending vault edit."""

        identity = hashlib.sha256(
            f"{candidate.id}:{content_hash}".encode("utf-8")
        ).hexdigest()[:24]
        session_id = f"vault-session-{identity}"
        evidence_id = f"vault-evidence-{identity}"
        now = _now_text()
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO sessions(
                    id, source_session_id, source_path, source_hash, project_id,
                    status, completed_at, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    session_id,
                    relative_path.as_posix(),
                    content_hash,
                    candidate.project_id,
                    "completed",
                    now,
                    now,
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO evidence(
                    id, session_id, kind, locator_session_id, event_id,
                    locator_source_path, content_hash, excerpt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evidence_id,
                    session_id,
                    "obsidian-manual-edit",
                    session_id,
                    candidate.id,
                    relative_path.as_posix(),
                    content_hash,
                    candidate.proposed_text,
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO candidates(
                    id, session_id, knowledge_type, project_id, scope,
                    proposed_text, status, extraction_confidence, review_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate.id,
                    session_id,
                    candidate.knowledge_type.value,
                    candidate.project_id,
                    candidate.scope,
                    candidate.proposed_text,
                    CandidateStatus.PENDING_REVIEW.value,
                    candidate.extraction_confidence,
                    _review_to_json(None),
                    now,
                    now,
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO candidate_evidence(candidate_id, evidence_id)
                VALUES (?, ?)""",
                (candidate.id, evidence_id),
            )
            if adoption is not None:
                if adoption.candidate_id != candidate.id:
                    raise ValueError("vault adoption candidate identity mismatch")
                connection.execute(
                    """INSERT OR IGNORE INTO vault_adoptions(
                        candidate_id, project_id, knowledge_id, original_version,
                        original_text_hash, relative_path, vault_managed_hash,
                        vault_full_hash, authority_hash, status, blocker,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        adoption.candidate_id,
                        adoption.project_id,
                        adoption.knowledge_id,
                        adoption.original_version,
                        adoption.original_text_hash,
                        adoption.relative_path.as_posix(),
                        adoption.vault_managed_hash,
                        adoption.vault_full_hash,
                        adoption.authority_hash,
                        adoption.status,
                        adoption.blocker,
                        now,
                        now,
                    ),
                )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="vault_edit_candidate_saved",
                    entity_type="candidate",
                    entity_id=candidate.id,
                    after_hash=content_hash,
                    actor="user",
                    detail={
                        "source": "obsidian-manual-edit",
                        "relative_path": relative_path.as_posix(),
                    },
                ),
            )
            saved = self._get_candidate(connection, candidate.id)
            if saved is None:
                raise sqlite3.IntegrityError("candidate readback failed")
            return saved

    def get_vault_adoption(self, candidate_id: str) -> VaultAdoption | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM vault_adoptions WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            return None if row is None else _vault_adoption_from_row(row)
        finally:
            connection.close()

    def list_candidates(self, status: CandidateStatus) -> list[Candidate]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id FROM candidates WHERE status = ? ORDER BY created_at, id",
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

    def pending_model_candidates_for_session(self, session_id: str) -> list[Candidate]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT c.id FROM candidates c
                JOIN sessions s ON s.id = c.session_id
                WHERE (s.id = ? OR s.source_session_id = ?)
                  AND c.status = ?
                ORDER BY c.created_at, c.id""",
                (session_id, session_id, CandidateStatus.PENDING_REVIEW.value),
            ).fetchall()
            return [
                candidate
                for row in rows
                if (candidate := self._get_candidate(connection, str(row[0])))
                is not None
            ]
        finally:
            connection.close()

    def candidates_for_session(self, session_id: str) -> list[Candidate]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT c.id FROM candidates c
                JOIN sessions s ON s.id = c.session_id
                WHERE s.id = ? OR s.source_session_id = ?
                ORDER BY c.created_at, c.id""",
                (session_id, session_id),
            ).fetchall()
            return [
                candidate
                for row in rows
                if (candidate := self._get_candidate(connection, str(row[0])))
                is not None
            ]
        finally:
            connection.close()

    def evidence_for_candidate(self, candidate_id: str) -> list[Evidence]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT e.* FROM evidence e
                JOIN candidate_evidence ce ON ce.evidence_id = e.id
                WHERE ce.candidate_id = ? ORDER BY e.id""",
                (candidate_id,),
            ).fetchall()
            return [_evidence_from_row(row) for row in rows]
        finally:
            connection.close()

    def save_review(
        self,
        candidate_id: str,
        result: ReviewResult,
        decision: AcceptanceDecision,
    ) -> None:
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT review_json FROM candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(f"candidate not found: {candidate_id}")
            existing_result = _review_from_json(str(existing[0]))
            decision_hash = _hash_value({"result": result, "decision": decision})
            if existing_result != result:
                cursor = connection.execute(
                    "UPDATE candidates SET review_json = ?, updated_at = ? WHERE id = ?",
                    (_review_to_json(result), _now_text(), candidate_id),
                )
                _require_row(cursor, "candidate", candidate_id)
            existing_audit = connection.execute(
                """SELECT 1 FROM audit_log
                WHERE action = 'review_saved' AND entity_id = ? AND after_hash = ?
                LIMIT 1""",
                (candidate_id, decision_hash),
            ).fetchone()
            if existing_audit is not None:
                return
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="review_saved",
                    entity_type="candidate",
                    entity_id=candidate_id,
                    after_hash=decision_hash,
                    actor=decision.actor,
                    detail={
                        "threshold": decision.threshold,
                        "threshold_passed": decision.threshold_passed,
                        "blockers": list(decision.blockers),
                        "verdict": decision.verdict.value,
                        "evidence_ids": list(decision.evidence_ids),
                    },
                ),
            )

    def get_review_result(self, candidate_id: str) -> ReviewResult | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT review_json FROM candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"candidate not found: {candidate_id}")
            return _review_from_json(str(row[0]))
        finally:
            connection.close()

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
                "error = ? WHERE id = ? AND status = 'running'",
                (status, result_json, error, attempt_id),
            )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    "SELECT status FROM review_attempts WHERE id = ?",
                    (attempt_id,),
                ).fetchone()
                if existing is None:
                    raise KeyError(f"review attempt not found: {attempt_id}")
                raise ValueError(f"review attempt already finished: {attempt_id}")
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

    def find_completed_review_attempt(
        self, candidate_id: str, input_hash: str
    ) -> ReviewAttempt | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT * FROM review_attempts
                WHERE candidate_id = ? AND input_hash = ? AND status = 'completed'
                ORDER BY attempt_no LIMIT 1""",
                (candidate_id, input_hash),
            ).fetchone()
            return None if row is None else _review_attempt_from_row(row)
        finally:
            connection.close()

    def review_attempts_for_candidate(self, candidate_id: str) -> list[ReviewAttempt]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM review_attempts WHERE candidate_id = ? "
                "ORDER BY attempt_no",
                (candidate_id,),
            ).fetchall()
            return [_review_attempt_from_row(row) for row in rows]
        finally:
            connection.close()

    def accept_candidate(
        self,
        candidate_id: str,
        text: str,
        actor: str,
        confidence: float,
        *,
        candidate_status: CandidateStatus = CandidateStatus.ACCEPTED,
        valid_until: datetime | None = None,
        decision: AcceptanceDecision | None = None,
        knowledge_type: KnowledgeType | None = None,
        scope: str | None = None,
    ) -> Knowledge:
        with self.transaction() as connection:
            candidate = self._get_candidate(connection, candidate_id)
            if candidate is None:
                raise KeyError(f"candidate not found: {candidate_id}")
            adoption = connection.execute(
                "SELECT 1 FROM vault_adoptions WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if adoption is not None:
                raise ValueError("vault_adoption_requires_guarded_accept")
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
                if candidate.status is not CandidateStatus.PENDING_REVIEW:
                    raise ValueError(f"candidate {candidate_id} must be pending")
                updated_at = datetime.now(timezone.utc)
                knowledge = Knowledge(
                    id=f"knowledge-{candidate.id}",
                    version=1,
                    candidate_id=candidate.id,
                    knowledge_type=knowledge_type or candidate.knowledge_type,
                    project_id=candidate.project_id,
                    scope=scope or candidate.scope,
                    text=text,
                    status="active",
                    confidence=confidence,
                    accepted_by=actor,
                    evidence_ids=candidate.evidence_ids,
                    valid_until=valid_until,
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
                """UPDATE candidates
                SET status = ?, proposed_text = ?, knowledge_type = ?, scope = ?,
                    updated_at = ? WHERE id = ?""",
                (
                    candidate_status.value,
                    (
                        text
                        if candidate_status is CandidateStatus.EDITED
                        else candidate.proposed_text
                    ),
                    (knowledge_type or candidate.knowledge_type).value,
                    scope or candidate.scope,
                    _now_text(),
                    candidate_id,
                ),
            )
            audit_detail: dict[str, Any] = {"candidate_id": candidate_id}
            if decision is not None:
                audit_detail.update(
                    {
                        "threshold": decision.threshold,
                        "threshold_passed": decision.threshold_passed,
                        "blockers": list(decision.blockers),
                        "verdict": decision.verdict.value,
                        "evidence_ids": list(decision.evidence_ids),
                    }
                )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action=(
                        "candidate_edited"
                        if candidate_status is CandidateStatus.EDITED
                        else "candidate_accepted"
                    ),
                    entity_type="knowledge",
                    entity_id=knowledge.id,
                    before_hash=_hash_value(candidate),
                    after_hash=_hash_value(knowledge),
                    detail=audit_detail,
                ),
            )
        return knowledge

    def accept_vault_adoption(
        self,
        candidate_id: str,
        text: str,
        actor: str,
        confidence: float,
        *,
        candidate_status: CandidateStatus,
        expected_authority_hash: str,
        managed_path: Path,
        vault_managed_hash: str,
        vault_full_hash: str,
        snapshot_kind: str,
        snapshot_event_id: str,
    ) -> Knowledge:
        """Atomically supersede the adopted identity and advance its baseline."""

        with self.transaction() as connection:
            adoption_row = connection.execute(
                "SELECT * FROM vault_adoptions WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if adoption_row is None:
                raise KeyError(f"vault adoption not found: {candidate_id}")
            adoption = _vault_adoption_from_row(adoption_row)
            if adoption.status != "pending_review":
                existing = connection.execute(
                    "SELECT * FROM knowledge WHERE candidate_id = ? ORDER BY version DESC",
                    (candidate_id,),
                ).fetchone()
                if adoption.status == "accepted" and existing is not None:
                    return self._knowledge_from_row(connection, existing)
                raise ValueError("vault_adoption_not_pending")
            if adoption.blocker:
                raise ValueError("vault_adoption_blocked")
            if actor != "user":
                raise ValueError("vault_adoption_actor_must_be_user")
            candidate = self._get_candidate(connection, candidate_id)
            if candidate is None:
                raise KeyError(f"candidate not found: {candidate_id}")
            if candidate.status is not CandidateStatus.PENDING_REVIEW:
                raise ValueError("vault_adoption_candidate_not_pending")
            current = self._latest_knowledge(connection, adoption.knowledge_id)
            if (
                current is None
                or current.version != adoption.original_version
                or current.status != "active"
                or hashlib.sha256(current.text.encode("utf-8")).hexdigest()
                != adoption.original_text_hash
            ):
                raise ValueError("vault_adoption_authority_changed")
            current_authority = projection_input_hash(
                self._list_project_knowledge(connection, adoption.project_id)
            )
            if (
                current_authority != adoption.authority_hash
                or expected_authority_hash != adoption.authority_hash
                or vault_managed_hash != adoption.vault_managed_hash
                or vault_full_hash != adoption.vault_full_hash
            ):
                raise ValueError("vault_adoption_authority_changed")
            state = connection.execute(
                "SELECT * FROM managed_file_state WHERE path = ?",
                (str(managed_path),),
            ).fetchone()
            if state is None or str(state["project_id"]) != adoption.project_id:
                raise ValueError("vault_adoption_baseline_changed")
            if snapshot_kind != "full":
                raise ValueError("vault_adoption_snapshot_invalid")
            knowledge = self._transition_knowledge(
                connection,
                current,
                action="vault_adoption_accepted",
                actor=actor,
                status="active",
                supersedes=(current.id,),
                detail={"candidate_id": candidate_id, "source": "obsidian-manual-edit"},
                candidate_id=candidate_id,
                text=text,
                confidence=confidence,
                evidence_ids=candidate.evidence_ids,
            )
            connection.execute(
                """UPDATE candidates SET status = ?, proposed_text = ?, updated_at = ?
                WHERE id = ?""",
                (candidate_status.value, text, _now_text(), candidate_id),
            )
            project_knowledge = self._list_project_knowledge(
                connection, adoption.project_id
            )
            owned_bytes = render_aggregate(
                knowledge.knowledge_type,
                (
                    item
                    for item in project_knowledge
                    if item.knowledge_type is knowledge.knowledge_type
                ),
            )
            connection.execute(
                """UPDATE managed_file_state SET managed_hash = ?, full_hash = ?,
                updated_at = ? WHERE path = ?""",
                (vault_managed_hash, vault_full_hash, _now_text(), str(managed_path)),
            )
            self._upsert_managed_file_snapshot(
                connection,
                path=managed_path,
                project_id=adoption.project_id,
                snapshot_kind=snapshot_kind,
                owned_bytes=owned_bytes,
                managed_hash=vault_managed_hash,
                full_hash=vault_full_hash,
                event_id=snapshot_event_id,
            )
            connection.execute(
                """UPDATE vault_adoptions SET status = 'accepted', updated_at = ?
                WHERE candidate_id = ?""",
                (_now_text(), candidate_id),
            )
            return knowledge

    def _upsert_managed_file_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        path: Path,
        project_id: str,
        snapshot_kind: str,
        owned_bytes: bytes,
        managed_hash: str,
        full_hash: str,
        event_id: str,
    ) -> None:
        connection.execute(
            """INSERT INTO managed_file_snapshots(
                path, project_id, snapshot_kind, owned_bytes,
                managed_hash, full_hash, event_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                project_id = excluded.project_id,
                snapshot_kind = excluded.snapshot_kind,
                owned_bytes = excluded.owned_bytes,
                managed_hash = excluded.managed_hash,
                full_hash = excluded.full_hash,
                event_id = excluded.event_id,
                updated_at = excluded.updated_at""",
            (
                str(path),
                project_id,
                snapshot_kind,
                owned_bytes,
                managed_hash,
                full_hash,
                event_id,
                _now_text(),
            ),
        )

    def reject_candidate(self, candidate_id: str, actor: str) -> Candidate:
        with self.transaction() as connection:
            candidate = self._get_candidate(connection, candidate_id)
            if candidate is None:
                raise KeyError(f"candidate not found: {candidate_id}")
            if candidate.status is not CandidateStatus.PENDING_REVIEW:
                raise ValueError(f"candidate {candidate_id} must be pending")
            connection.execute(
                "UPDATE candidates SET status = ?, updated_at = ? WHERE id = ?",
                (CandidateStatus.REJECTED.value, _now_text(), candidate_id),
            )
            connection.execute(
                """UPDATE vault_adoptions SET status = 'rejected', updated_at = ?
                WHERE candidate_id = ? AND status = 'pending_review'""",
                (_now_text(), candidate_id),
            )
            rejected = self._get_candidate(connection, candidate_id)
            assert rejected is not None
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="candidate_rejected",
                    entity_type="candidate",
                    entity_id=candidate_id,
                    before_hash=_hash_value(candidate),
                    after_hash=_hash_value(rejected),
                    detail={"candidate_id": candidate_id},
                ),
            )
            return rejected

    def knowledge_for_candidate(self, candidate_id: str) -> Knowledge | None:
        versions = self.knowledge_versions_for_candidate(candidate_id)
        return versions[-1] if versions else None

    def knowledge_versions_for_candidate(self, candidate_id: str) -> list[Knowledge]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM knowledge WHERE candidate_id = ? ORDER BY version",
                (candidate_id,),
            ).fetchall()
            return [self._knowledge_from_row(connection, row) for row in rows]
        finally:
            connection.close()

    def knowledge_versions(self, knowledge_id: str) -> list[Knowledge]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM knowledge WHERE id = ? ORDER BY version",
                (knowledge_id,),
            ).fetchall()
            return [self._knowledge_from_row(connection, row) for row in rows]
        finally:
            connection.close()

    def list_active_knowledge(self, project_id: str, at: datetime) -> list[Knowledge]:
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

    def list_brief_knowledge(self, project_id: str, at: datetime) -> list[Knowledge]:
        """Return latest accepted rows relevant to a project or global scope.

        Expired, stale, and archived rows remain visible to the application so
        it can disclose deterministic omission reasons without consulting
        candidate/model state.
        """

        del at
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT item.* FROM knowledge AS item
                JOIN (
                    SELECT id, MAX(version) AS version FROM knowledge GROUP BY id
                ) AS latest ON latest.id = item.id AND latest.version = item.version
                WHERE item.project_id = ?
                   OR (item.scope = 'global' AND item.knowledge_type = 'RULE')
                ORDER BY item.id""",
                (project_id,),
            ).fetchall()
            return [self._knowledge_from_row(connection, row) for row in rows]
        finally:
            connection.close()

    def list_project_knowledge(self, project_id: str) -> list[Knowledge]:
        """Return the latest project-scoped active and archived projection rows."""

        connection = self._connect()
        try:
            return self._list_project_knowledge(connection, project_id)
        finally:
            connection.close()

    def _list_project_knowledge(
        self, connection: sqlite3.Connection, project_id: str
    ) -> list[Knowledge]:
        rows = connection.execute(
            """SELECT item.* FROM knowledge AS item
            JOIN (
                SELECT id, MAX(version) AS version FROM knowledge GROUP BY id
            ) AS latest ON latest.id = item.id AND latest.version = item.version
            WHERE item.project_id = ? AND item.scope = 'project'
              AND item.status IN ('active', 'archived')
            ORDER BY item.id""",
            (project_id,),
        ).fetchall()
        return [self._knowledge_from_row(connection, row) for row in rows]

    def _knowledge_from_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> Knowledge:
        evidence_rows = connection.execute(
            """SELECT evidence_id FROM knowledge_evidence
            WHERE knowledge_id = ? AND knowledge_version = ?
            ORDER BY evidence_id""",
            (row["id"], row["version"]),
        ).fetchall()
        supersedes: tuple[str, ...] = ()
        audit_rows = connection.execute(
            "SELECT detail_json FROM audit_log WHERE entity_id = ? "
            "ORDER BY created_at, id",
            (row["id"],),
        ).fetchall()
        for audit_row in audit_rows:
            detail = json.loads(str(audit_row["detail_json"]))
            if detail.get("knowledge_version") == int(row["version"]):
                supersedes = tuple(str(item) for item in detail.get("supersedes", ()))
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
            supersedes=supersedes,
        )

    def _latest_knowledge(
        self, connection: sqlite3.Connection, knowledge_id: str
    ) -> Knowledge | None:
        row = connection.execute(
            "SELECT * FROM knowledge WHERE id = ? ORDER BY version DESC LIMIT 1",
            (knowledge_id,),
        ).fetchone()
        return None if row is None else self._knowledge_from_row(connection, row)

    def _insert_knowledge(
        self, connection: sqlite3.Connection, knowledge: Knowledge
    ) -> None:
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

    def _transition_knowledge(
        self,
        connection: sqlite3.Connection,
        current: Knowledge,
        *,
        action: str,
        actor: str,
        status: str,
        supersedes: tuple[str, ...],
        detail: Mapping[str, Any],
        candidate_id: str | None = None,
        scope: str | None = None,
        text: str | None = None,
        confidence: float | None = None,
        evidence_ids: tuple[str, ...] | None = None,
    ) -> Knowledge:
        connection.execute(
            "UPDATE knowledge SET status = 'superseded' WHERE id = ? AND version = ?",
            (current.id, current.version),
        )
        created = Knowledge(
            id=current.id,
            version=current.version + 1,
            candidate_id=candidate_id or current.candidate_id,
            knowledge_type=current.knowledge_type,
            project_id=current.project_id,
            scope=scope or current.scope,
            text=text if text is not None else current.text,
            status=status,
            confidence=(current.confidence if confidence is None else confidence),
            accepted_by=actor,
            evidence_ids=(
                current.evidence_ids if evidence_ids is None else evidence_ids
            ),
            valid_until=current.valid_until,
            updated_at=datetime.now(timezone.utc),
            supersedes=supersedes,
        )
        self._insert_knowledge(connection, created)
        audit_detail = dict(detail)
        audit_detail.update(
            {
                "knowledge_version": created.version,
                "supersedes": list(supersedes),
            }
        )
        self._append_audit_record(
            connection,
            self._audit_entry(
                actor=actor,
                action=action,
                entity_type="knowledge",
                entity_id=current.id,
                before_hash=_hash_value(current),
                after_hash=_hash_value(created),
                detail=audit_detail,
            ),
        )
        return created

    def save_conflict(self, conflict: KnowledgeConflict) -> None:
        with self.transaction() as connection:
            self._save_conflict(connection, conflict)

    def _save_conflict(
        self, connection: sqlite3.Connection, conflict: KnowledgeConflict
    ) -> None:
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

    def create_conflict(self, conflict: KnowledgeConflict) -> KnowledgeConflict:
        with self.transaction() as connection:
            existing_row = connection.execute(
                "SELECT * FROM conflicts WHERE id = ?", (conflict.id,)
            ).fetchone()
            if existing_row is not None:
                existing = _conflict_from_row(existing_row)
                if (
                    existing.active_knowledge_id == conflict.active_knowledge_id
                    and existing.candidate_id == conflict.candidate_id
                    and existing.reason == conflict.reason
                    and existing.merge_text == conflict.merge_text
                ):
                    return existing
                raise ValueError(f"conflict identity collision: {conflict.id}")
            active = self._latest_knowledge(connection, conflict.active_knowledge_id)
            if active is None:
                raise ValueError(f"knowledge not found: {conflict.active_knowledge_id}")
            if active.status != "active":
                raise ValueError(
                    f"knowledge {active.id} must be active for conflict detection"
                )
            candidate = self._get_candidate(connection, conflict.candidate_id)
            if candidate is None:
                raise ValueError(f"candidate not found: {conflict.candidate_id}")
            if candidate.status is not CandidateStatus.PENDING_REVIEW:
                raise ValueError(
                    f"candidate {candidate.id} must be pending for conflict detection"
                )
            if (
                candidate.project_id != active.project_id
                or candidate.knowledge_type is not active.knowledge_type
                or candidate.scope != active.scope
            ):
                raise ValueError(
                    "conflict candidate must match active project, type, and scope"
                )
            self._save_conflict(connection, conflict)
            return conflict

    def get_conflict(self, conflict_id: str) -> KnowledgeConflict | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM conflicts WHERE id = ?", (conflict_id,)
            ).fetchone()
            return None if row is None else _conflict_from_row(row)
        finally:
            connection.close()

    def list_open_conflicts(self, project_id: str) -> list[KnowledgeConflict]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT conflicts.* FROM conflicts
                JOIN candidates ON candidates.id = conflicts.candidate_id
                WHERE candidates.project_id = ? AND conflicts.status != 'resolved'
                ORDER BY conflicts.id""",
                (project_id,),
            ).fetchall()
            return [_conflict_from_row(row) for row in rows]
        finally:
            connection.close()

    def resolve_conflict(self, conflict_id: str, text: str, actor: str) -> Knowledge:
        if actor != "user":
            raise ValueError("conflict resolution actor must be user")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM conflicts WHERE id = ?", (conflict_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"conflict not found: {conflict_id}")
            conflict = _conflict_from_row(row)
            if conflict.status != "open":
                raise ValueError(f"conflict {conflict_id} must be open")
            active = self._latest_knowledge(connection, conflict.active_knowledge_id)
            if active is None or active.status != "active":
                raise ValueError(
                    f"knowledge {conflict.active_knowledge_id} must be active"
                )
            candidate = self._get_candidate(connection, conflict.candidate_id)
            if candidate is None:
                raise KeyError(f"candidate not found: {conflict.candidate_id}")
            if candidate.status is not CandidateStatus.PENDING_REVIEW:
                raise ValueError(f"candidate {candidate.id} must be pending")
            candidate_row = connection.execute(
                "SELECT review_json FROM candidates WHERE id = ?",
                (candidate.id,),
            ).fetchone()
            review = _review_from_json(str(candidate_row["review_json"]))
            evidence_ids = tuple(
                dict.fromkeys((*active.evidence_ids, *candidate.evidence_ids))
            )
            supersedes = (
                f"{active.id}:v{active.version}",
                f"candidate:{candidate.id}",
            )
            merged = self._transition_knowledge(
                connection,
                active,
                action="conflict_resolved",
                actor=actor,
                status="active",
                supersedes=supersedes,
                detail={"conflict_id": conflict.id},
                candidate_id=candidate.id,
                text=text,
                confidence=(
                    candidate.extraction_confidence
                    if review is None
                    else review.confidence
                ),
                evidence_ids=evidence_ids,
            )
            connection.execute(
                "UPDATE candidates SET status = ?, updated_at = ? WHERE id = ?",
                (CandidateStatus.ACCEPTED.value, _now_text(), candidate.id),
            )
            connection.execute(
                "UPDATE conflicts SET status = 'resolved', resolved_at = ? "
                "WHERE id = ?",
                (_now_text(), conflict.id),
            )
            return merged

    def promote_global(self, knowledge_id: str, actor: str) -> Knowledge:
        if actor != "user":
            raise ValueError("global promotion actor must be user")
        with self.transaction() as connection:
            current = self._latest_knowledge(connection, knowledge_id)
            if current is None:
                raise KeyError(f"knowledge not found: {knowledge_id}")
            if current.status != "active":
                raise ValueError(f"knowledge {knowledge_id} must be active")
            if current.scope == "global":
                raise ValueError(f"knowledge {knowledge_id} is already global")
            supersedes = (f"{current.id}:v{current.version}",)
            return self._transition_knowledge(
                connection,
                current,
                action="knowledge_promoted_global",
                actor=actor,
                status="active",
                scope="global",
                supersedes=supersedes,
                detail={},
            )

    def expire_task_states(self, at: datetime) -> list[Knowledge]:
        with self.transaction() as connection:
            rows = connection.execute(
                """SELECT * FROM knowledge
                WHERE knowledge_type = ? AND status = 'active'
                  AND valid_until IS NOT NULL AND valid_until <= ?
                ORDER BY created_at, id, version""",
                (KnowledgeType.TASK_STATE.value, _datetime_text(at)),
            ).fetchall()
            expired: list[Knowledge] = []
            for row in rows:
                current = self._knowledge_from_row(connection, row)
                supersedes = (f"{current.id}:v{current.version}",)
                expired.append(
                    self._transition_knowledge(
                        connection,
                        current,
                        action="task_state_expired",
                        actor="system-expiry",
                        status="stale",
                        supersedes=supersedes,
                        detail={"expired_at": _datetime_text(at)},
                    )
                )
            return expired

    def archive_knowledge(self, knowledge_id: str, actor: str) -> Knowledge:
        if actor != "user":
            raise ValueError("archive actor must be user")
        with self.transaction() as connection:
            current = self._latest_knowledge(connection, knowledge_id)
            if current is None:
                raise KeyError(f"knowledge not found: {knowledge_id}")
            if current.status != "active":
                raise ValueError(f"knowledge {knowledge_id} must be active")
            supersedes = (f"{current.id}:v{current.version}",)
            return self._transition_knowledge(
                connection,
                current,
                action="knowledge_archived",
                actor=actor,
                status="archived",
                supersedes=supersedes,
                detail={},
            )

    def begin_sync(self, job: SyncJob) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO sync_jobs(
                    id, project_id, status, plan_json, backup_path, error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    plan_json = excluded.plan_json,
                    backup_path = excluded.backup_path,
                    error = excluded.error,
                    updated_at = excluded.updated_at""",
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

    def get_sync_job(self, job_id: str) -> SyncJob | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM sync_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            return SyncJob(
                id=str(row["id"]),
                project_id=str(row["project_id"]),
                status=str(row["status"]),
                plan_json=str(row["plan_json"]),
                backup_path=Path(row["backup_path"]),
                error=str(row["error"]),
            )
        finally:
            connection.close()

    def has_rollback_required_sync(self) -> bool:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT 1 FROM sync_jobs WHERE status = ? LIMIT 1",
                (ProjectionStatus.ROLLBACK_REQUIRED.value,),
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    def rollback_required_sync_jobs(self) -> list[SyncJob]:
        """Return redaction-safe recovery identities for blocked sync runs."""

        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM sync_jobs WHERE status = ? ORDER BY id",
                (ProjectionStatus.ROLLBACK_REQUIRED.value,),
            ).fetchall()
            return [
                SyncJob(
                    id=str(row["id"]),
                    project_id=str(row["project_id"]),
                    status=str(row["status"]),
                    plan_json=str(row["plan_json"]),
                    backup_path=Path(row["backup_path"]),
                    error=str(row["error"]),
                )
                for row in rows
            ]
        finally:
            connection.close()

    def has_purge_incomplete(self) -> bool:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT 1 FROM purge_jobs WHERE status = ? LIMIT 1",
                (PurgeStatus.PURGE_INCOMPLETE.value,),
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    def complete_sync(
        self,
        event_id: str,
        project_id: str,
        file_states: Sequence[ManagedFileUpdate],
        expected_input_hash: str,
    ) -> None:
        """Atomically publish post-write hashes and finish both journal records."""

        with self.transaction() as connection:
            if not self._projection_fence_matches(
                connection, event_id, expected_input_hash
            ):
                raise ProjectionFenceError("projection_superseded")
            for item in file_states:
                path, managed_hash, full_hash = item
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
                snapshot_kind = getattr(item, "snapshot_kind", "")
                if snapshot_kind:
                    connection.execute(
                        """INSERT INTO managed_file_snapshots(
                            path, project_id, snapshot_kind, owned_bytes,
                            managed_hash, full_hash, event_id, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            project_id = excluded.project_id,
                            snapshot_kind = excluded.snapshot_kind,
                            owned_bytes = excluded.owned_bytes,
                            managed_hash = excluded.managed_hash,
                            full_hash = excluded.full_hash,
                            event_id = excluded.event_id,
                            updated_at = excluded.updated_at""",
                        (
                            str(path),
                            project_id,
                            snapshot_kind,
                            bytes(item.owned_bytes),
                            managed_hash,
                            full_hash,
                            item.event_id,
                            _now_text(),
                        ),
                    )
            sync_cursor = connection.execute(
                "UPDATE sync_jobs SET status = ?, error = '', updated_at = ? WHERE id = ?",
                (ProjectionStatus.SYNCED.value, _now_text(), event_id),
            )
            _require_row(sync_cursor, "sync job", event_id)
            event_cursor = connection.execute(
                """UPDATE projection_events SET status = ?, error = '', updated_at = ?
                WHERE id = ?""",
                (ProjectionStatus.SYNCED.value, _now_text(), event_id),
            )
            _require_row(event_cursor, "projection event", event_id)
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="sync_completed",
                    entity_type="sync_job",
                    entity_id=event_id,
                    detail={"project_id": project_id, "file_count": len(file_states)},
                ),
            )

    def projection_fence_matches(self, event_id: str, expected_input_hash: str) -> bool:
        connection = self._connect()
        try:
            return self._projection_fence_matches(
                connection, event_id, expected_input_hash
            )
        finally:
            connection.close()

    def _projection_fence_matches(
        self,
        connection: sqlite3.Connection,
        event_id: str,
        expected_input_hash: str,
    ) -> bool:
        event = connection.execute(
            "SELECT project_id, input_hash FROM projection_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if event is None or str(event["input_hash"]) != expected_input_hash:
            return False
        knowledge = self._project_knowledge(connection, str(event["project_id"]))
        if projection_input_hash(knowledge) != expected_input_hash:
            return False
        latest = connection.execute(
            """SELECT id FROM projection_events
            WHERE project_id = ? AND input_hash = ?
            ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (str(event["project_id"]), expected_input_hash),
        ).fetchone()
        return latest is not None and str(latest["id"]) == event_id

    def _project_knowledge(
        self, connection: sqlite3.Connection, project_id: str
    ) -> list[Knowledge]:
        rows = connection.execute(
            """SELECT item.* FROM knowledge AS item
            JOIN (
                SELECT id, MAX(version) AS version FROM knowledge GROUP BY id
            ) AS current ON current.id = item.id AND current.version = item.version
            WHERE item.project_id = ? AND item.scope = 'project'
              AND item.status IN ('active', 'archived')
            ORDER BY item.id""",
            (project_id,),
        ).fetchall()
        return [self._knowledge_from_row(connection, row) for row in rows]

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

    def list_project_mappings(self, active_only: bool = True) -> list[ProjectMapping]:
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
                "UPDATE project_mappings SET active = 0, updated_at = ? WHERE id = ?",
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
    ) -> Reclassification:
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
                raise ValueError(f"project mapping target mismatch: {mapping_id}")
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
            candidate_rows = connection.execute(
                """SELECT id, project_id FROM candidates
                WHERE session_id = ? ORDER BY created_at, id""",
                (internal_session_id,),
            ).fetchall()
            state_rows = connection.execute(
                "SELECT id, project_id, status FROM candidates WHERE session_id = ?",
                (internal_session_id,),
            ).fetchall()
            pending_rows = [
                item
                for item in state_rows
                if str(item["status"]) == CandidateStatus.PENDING_REVIEW.value
            ]
            candidate_ids = tuple(str(item["id"]) for item in pending_rows)
            preexisting_knowledge_versions: tuple[tuple[str, int], ...] = ()
            preexisting_conflict_ids: tuple[str, ...] = ()
            baseline_ids = tuple(str(item["id"]) for item in candidate_rows)
            if baseline_ids:
                placeholders = ",".join("?" for _ in baseline_ids)
                knowledge_rows = connection.execute(
                    f"""SELECT id, version FROM knowledge
                    WHERE candidate_id IN ({placeholders}) ORDER BY id, version""",
                    baseline_ids,
                ).fetchall()
                preexisting_knowledge_versions = tuple(
                    (str(item["id"]), int(item["version"])) for item in knowledge_rows
                )
                conflict_rows = connection.execute(
                    f"""SELECT id FROM conflicts
                    WHERE candidate_id IN ({placeholders}) ORDER BY id""",
                    baseline_ids,
                ).fetchall()
                preexisting_conflict_ids = tuple(
                    str(item["id"]) for item in conflict_rows
                )
            before_state = {
                "project_id": before_project,
                "pending_candidates": [
                    {
                        "id": str(item["id"]),
                        "project_id": str(item["project_id"]),
                    }
                    for item in pending_rows
                ],
            }
            connection.execute(
                "UPDATE sessions SET project_id = ? WHERE id = ?",
                (project_id, internal_session_id),
            )
            connection.execute(
                """UPDATE candidates SET project_id = ?, updated_at = ?
                WHERE session_id = ? AND status = ?""",
                (
                    project_id,
                    _now_text(),
                    internal_session_id,
                    CandidateStatus.PENDING_REVIEW.value,
                ),
            )
            after_state = {
                "project_id": project_id,
                "pending_candidates": [
                    {"id": str(item["id"]), "project_id": project_id}
                    for item in pending_rows
                ],
            }
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="session_reclassified",
                    entity_type="session",
                    entity_id=internal_session_id,
                    before_hash=_hash_value(before_state),
                    after_hash=_hash_value(after_state),
                    detail={
                        "mapping_id": mapping_id,
                        "pending_candidate_count": len(pending_rows),
                    },
                ),
            )
            return Reclassification(
                session_id=internal_session_id,
                previous_project_id=before_project,
                target_project_id=project_id,
                mapping_id=mapping_id,
                pending_candidate_ids=candidate_ids,
                candidate_states=tuple(
                    (str(item["id"]), str(item["project_id"]), str(item["status"]))
                    for item in state_rows
                ),
                preexisting_knowledge_versions=preexisting_knowledge_versions,
                preexisting_conflict_ids=preexisting_conflict_ids,
            )

    def rollback_reclassification(
        self,
        reclassification: Reclassification,
        actor: str,
        affected_candidate_ids: Sequence[str] = (),
    ) -> None:
        """Compensate a failed post-reclassification review without erasing attempts."""

        with self.transaction() as connection:
            session = connection.execute(
                "SELECT project_id FROM sessions WHERE id = ?",
                (reclassification.session_id,),
            ).fetchone()
            if session is None:
                raise ValueError(f"session not found: {reclassification.session_id}")
            if str(session["project_id"]) != reclassification.target_project_id:
                raise ValueError(
                    "session target changed before reclassification rollback"
                )
            candidate_ids = tuple(
                dict.fromkeys(
                    (*reclassification.pending_candidate_ids, *affected_candidate_ids)
                )
            )
            removed_knowledge = 0
            removed_conflicts = 0
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                knowledge_rows = connection.execute(
                    f"""SELECT id, version FROM knowledge
                    WHERE candidate_id IN ({placeholders})""",
                    candidate_ids,
                ).fetchall()
                preexisting_knowledge = set(
                    reclassification.preexisting_knowledge_versions
                )
                for row in knowledge_rows:
                    identity = (str(row["id"]), int(row["version"]))
                    if identity in preexisting_knowledge:
                        continue
                    connection.execute(
                        "DELETE FROM knowledge_evidence "
                        "WHERE knowledge_id = ? AND knowledge_version = ?",
                        (str(row["id"]), int(row["version"])),
                    )
                    removed_knowledge += connection.execute(
                        "DELETE FROM knowledge WHERE id = ? AND version = ?",
                        identity,
                    ).rowcount
                conflict_rows = connection.execute(
                    f"""SELECT id FROM conflicts
                    WHERE candidate_id IN ({placeholders})""",
                    candidate_ids,
                ).fetchall()
                preexisting_conflicts = set(reclassification.preexisting_conflict_ids)
                for row in conflict_rows:
                    conflict_id = str(row["id"])
                    if conflict_id in preexisting_conflicts:
                        continue
                    removed_conflicts += connection.execute(
                        "DELETE FROM conflicts WHERE id = ?", (conflict_id,)
                    ).rowcount
                baseline = {
                    item[0]: (item[1], item[2])
                    for item in reclassification.candidate_states
                }
                for candidate_id in candidate_ids:
                    project_id, status = baseline.get(
                        candidate_id,
                        (
                            reclassification.previous_project_id,
                            CandidateStatus.PENDING_REVIEW.value,
                        ),
                    )
                    connection.execute(
                        """UPDATE candidates SET project_id = ?, status = ?, updated_at = ?
                        WHERE id = ?""",
                        (project_id, status, _now_text(), candidate_id),
                    )
            connection.execute(
                "UPDATE sessions SET project_id = ? WHERE id = ?",
                (
                    reclassification.previous_project_id,
                    reclassification.session_id,
                ),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="session_reclassification_rolled_back",
                    entity_type="session",
                    entity_id=reclassification.session_id,
                    before_hash=_hash_value(
                        {"project_id": reclassification.target_project_id}
                    ),
                    after_hash=_hash_value(
                        {"project_id": reclassification.previous_project_id}
                    ),
                    detail={
                        "mapping_id": reclassification.mapping_id,
                        "pending_candidate_count": len(candidate_ids),
                        "removed_knowledge_count": removed_knowledge,
                        "removed_conflict_count": removed_conflicts,
                    },
                ),
            )

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

    def save_current_projection_event(
        self, project_id: str, cause: str, cause_entity_id: str
    ) -> str:
        """Atomically bind a deterministic event to authoritative knowledge."""

        with self.transaction() as connection:
            input_hash = projection_input_hash(
                self._project_knowledge(connection, project_id)
            )
            identity = json.dumps(
                [project_id, cause, cause_entity_id, input_hash],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            event_id = (
                "projection-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
            )
            existing = connection.execute(
                """SELECT id FROM projection_events
                WHERE project_id = ? AND cause = ? AND cause_entity_id = ?
                  AND input_hash = ?""",
                (project_id, cause, cause_entity_id, input_hash),
            ).fetchone()
            stored_id = str(existing["id"]) if existing is not None else event_id
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

    def get_projection_event(self, event_id: str) -> ProjectionEvent | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM projection_events WHERE id = ?", (event_id,)
            ).fetchone()
            if row is None:
                return None
            return ProjectionEvent(
                id=str(row["id"]),
                project_id=str(row["project_id"]),
                cause=str(row["cause"]),
                cause_entity_id=str(row["cause_entity_id"]),
                input_hash=str(row["input_hash"]),
                status=ProjectionStatus(str(row["status"])),
                error=str(row["error"]),
            )
        finally:
            connection.close()

    def list_projection_events(self, project_id: str) -> list[ProjectionEvent]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM projection_events WHERE project_id = ? ORDER BY created_at, id",
                (project_id,),
            ).fetchall()
            return [
                ProjectionEvent(
                    id=str(row["id"]),
                    project_id=str(row["project_id"]),
                    cause=str(row["cause"]),
                    cause_entity_id=str(row["cause_entity_id"]),
                    input_hash=str(row["input_hash"]),
                    status=ProjectionStatus(str(row["status"])),
                    error=str(row["error"]),
                )
                for row in rows
            ]
        finally:
            connection.close()

    def finish_projection_event(
        self, event_id: str, status: ProjectionStatus, error: str = ""
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE projection_events SET status = ?, error = ?, updated_at = ?
                WHERE id = ?""",
                (status.value, error, _now_text(), event_id),
            )
            _require_row(cursor, "projection event", event_id)
            self._append_audit_record(
                connection,
                self._audit_entry(
                    action="projection_event_finished",
                    entity_type="projection_event",
                    entity_id=event_id,
                    after_hash=_hash_value({"status": status.value, "error": error}),
                    detail={"status": status.value, "has_error": bool(error)},
                ),
            )

    def projection_event_count(self, project_id: str) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM projection_events WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return int(row[0])
        finally:
            connection.close()

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

    def get_managed_file_state(self, path: Path) -> ManagedFileState | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM managed_file_state WHERE path = ?", (str(path),)
            ).fetchone()
            if row is None:
                return None
            return ManagedFileState(
                project_id=str(row["project_id"]),
                path=Path(row["path"]),
                managed_hash=str(row["managed_hash"]),
                full_hash=str(row["full_hash"]),
            )
        finally:
            connection.close()

    def get_managed_file_snapshot(self, path: Path) -> ManagedFileSnapshot | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM managed_file_snapshots WHERE path = ?", (str(path),)
            ).fetchone()
            if row is None:
                return None
            return ManagedFileSnapshot(
                project_id=str(row["project_id"]),
                path=Path(row["path"]),
                snapshot_kind=str(row["snapshot_kind"]),
                owned_bytes=bytes(row["owned_bytes"]),
                managed_hash=str(row["managed_hash"]),
                full_hash=str(row["full_hash"]),
                event_id=str(row["event_id"]),
            )
        finally:
            connection.close()

    def list_managed_file_states(self, project_id: str) -> list[ManagedFileState]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM managed_file_state WHERE project_id = ? ORDER BY path",
                (project_id,),
            ).fetchall()
            return [
                ManagedFileState(
                    project_id=str(row["project_id"]),
                    path=Path(row["path"]),
                    managed_hash=str(row["managed_hash"]),
                    full_hash=str(row["full_hash"]),
                )
                for row in rows
            ]
        finally:
            connection.close()

    def inspect_purge_database(self, knowledge_id: str) -> PurgeInspection:
        """Inspect only registered SQLite fields without mutating purge state."""

        connection = self._connect()
        try:
            knowledge_rows = connection.execute(
                "SELECT * FROM knowledge WHERE id = ? ORDER BY version",
                (knowledge_id,),
            ).fetchall()
            knowledge = (
                None
                if not knowledge_rows
                else self._knowledge_from_row(connection, knowledge_rows[-1])
            )
            purged = connection.execute(
                "SELECT 1 FROM purge_jobs WHERE knowledge_id = ? AND status = ? LIMIT 1",
                (knowledge_id, PurgeStatus.PURGED.value),
            ).fetchone()
            sync_pending = connection.execute(
                """SELECT 1 FROM projection_events
                WHERE cause_entity_id = ? AND status = ? LIMIT 1""",
                (knowledge_id, ProjectionStatus.SYNC_PENDING.value),
            ).fetchone()
            if knowledge is None:
                return PurgeInspection(
                    None, purged is not None, sync_pending is not None, (), ()
                )

            markers, copies = self._purge_entity_copies(
                connection, knowledge_id, knowledge_rows
            )
            return PurgeInspection(
                knowledge,
                purged is not None,
                sync_pending is not None,
                tuple(copies),
                markers,
            )
        finally:
            connection.close()

    @staticmethod
    def _purge_entity_copies(
        connection: sqlite3.Connection,
        knowledge_id: str,
        knowledge_rows: Sequence[sqlite3.Row] | None = None,
    ) -> tuple[tuple[bytes, ...], list[PurgeCopy]]:
        rows = list(
            knowledge_rows
            if knowledge_rows is not None
            else connection.execute(
                "SELECT * FROM knowledge WHERE id = ? ORDER BY version",
                (knowledge_id,),
            ).fetchall()
        )
        if not rows:
            return (), []

        candidate_ids = tuple(sorted({str(row["candidate_id"]) for row in rows}))
        candidate_placeholders = ",".join("?" for _ in candidate_ids)
        candidates = connection.execute(
            f"SELECT * FROM candidates WHERE id IN ({candidate_placeholders}) ORDER BY id",
            candidate_ids,
        ).fetchall()
        evidence_ids = {
            str(row["evidence_id"])
            for row in connection.execute(
                "SELECT evidence_id FROM knowledge_evidence WHERE knowledge_id = ?",
                (knowledge_id,),
            ).fetchall()
        }
        evidence_ids.update(
            str(row["evidence_id"])
            for row in connection.execute(
                f"SELECT evidence_id FROM candidate_evidence "
                f"WHERE candidate_id IN ({candidate_placeholders})",
                candidate_ids,
            ).fetchall()
        )
        ordered_evidence_ids = tuple(sorted(evidence_ids))
        evidence = (
            connection.execute(
                f"SELECT * FROM evidence WHERE id IN "
                f"({','.join('?' for _ in ordered_evidence_ids)}) ORDER BY id",
                ordered_evidence_ids,
            ).fetchall()
            if ordered_evidence_ids
            else []
        )
        reviews = connection.execute(
            f"SELECT * FROM review_attempts "
            f"WHERE candidate_id IN ({candidate_placeholders}) ORDER BY id",
            candidate_ids,
        ).fetchall()
        conflicts = connection.execute(
            f"SELECT * FROM conflicts WHERE active_knowledge_id = ? "
            f"OR candidate_id IN ({candidate_placeholders}) ORDER BY id",
            (knowledge_id, *candidate_ids),
        ).fetchall()

        marker_values = {
            str(value).encode("utf-8")
            for value in (
                *(row["text"] for row in rows),
                *(row["proposed_text"] for row in candidates),
                *(row["excerpt"] for row in evidence),
                *(
                    row[field]
                    for row in conflicts
                    for field in ("reason", "merge_text")
                ),
            )
            if str(value)
        }
        markers = tuple(sorted(marker_values, key=lambda item: (-len(item), item)))
        copies: list[PurgeCopy] = []

        def add(
            kind: str, table: str, key: object, row: sqlite3.Row, *fields: str
        ) -> None:
            for field in fields:
                value = row[field]
                content = (
                    bytes(value)
                    if isinstance(value, bytes)
                    else str(value).encode("utf-8")
                )
                if content:
                    copies.append(PurgeCopy(kind, f"{table}:{key}:{field}", content))

        for row in rows:
            add(
                "sqlite_knowledge",
                "knowledge",
                f"{knowledge_id}:{row['version']}",
                row,
                "text",
            )
        for row in candidates:
            add(
                "sqlite_candidate",
                "candidates",
                row["id"],
                row,
                "proposed_text",
                "review_json",
            )
        for row in evidence:
            add("sqlite_evidence", "evidence", row["id"], row, "excerpt")
        for row in reviews:
            add(
                "sqlite_review",
                "review_attempts",
                row["id"],
                row,
                "result_json",
                "error",
            )
        for row in conflicts:
            add("sqlite_conflict", "conflicts", row["id"], row, "reason", "merge_text")

        related_ids = {
            knowledge_id,
            *candidate_ids,
            *ordered_evidence_ids,
            *(str(row["id"]) for row in reviews),
            *(str(row["id"]) for row in conflicts),
        }
        placeholders = ",".join("?" for _ in related_ids)
        related_values = tuple(sorted(related_ids))
        audits = connection.execute(
            f"SELECT * FROM audit_log WHERE entity_id IN ({placeholders}) ORDER BY id",
            related_values,
        ).fetchall()
        projections = connection.execute(
            f"SELECT * FROM projection_events WHERE cause_entity_id IN ({placeholders}) ORDER BY id",
            related_values,
        ).fetchall()
        for row in audits:
            add("sqlite_audit", "audit_log", row["id"], row, "detail_json")
        for row in projections:
            for field in ("input_hash", "error"):
                content = str(row[field]).encode("utf-8")
                if content and any(marker in content for marker in markers):
                    add("sqlite_projection", "projection_events", row["id"], row, field)

        project_id = str(rows[-1]["project_id"])
        for table, key_field, fields in (
            ("sync_jobs", "id", ("plan_json", "error")),
            ("managed_file_snapshots", "path", ("owned_bytes",)),
        ):
            project_rows = connection.execute(
                f"SELECT * FROM {table} WHERE project_id = ? ORDER BY {key_field}",
                (project_id,),
            ).fetchall()
            for row in project_rows:
                for field in fields:
                    value = row[field]
                    content = (
                        bytes(value)
                        if isinstance(value, bytes)
                        else str(value).encode("utf-8")
                    )
                    if content and any(marker in content for marker in markers):
                        add("sqlite_projection", table, row[key_field], row, field)

        copies.sort(key=lambda item: (item.location_kind, item.locator))
        return markers, copies

    def begin_purge(
        self,
        plan: PurgePlan,
        *,
        plan_hash: str,
        actor: str,
        markers: Sequence[bytes],
        journal_locations: Mapping[str, str],
        database_expected_hashes: Mapping[str, str],
        recovery_payloads: Mapping[str, str],
        tombstone_json: str,
        precommit_guard: Callable[[], None],
    ) -> None:
        """Journal and scrub SQLite-owned copies in one transaction."""

        with self.transaction() as connection:
            connection.execute("PRAGMA secure_delete = ON")
            knowledge_rows = connection.execute(
                "SELECT * FROM knowledge WHERE id = ? ORDER BY version",
                (plan.knowledge_id,),
            ).fetchall()
            current_markers, current_copies = self._purge_entity_copies(
                connection, plan.knowledge_id, knowledge_rows
            )
            current_hashes = {
                item.locator: hashlib.sha256(item.content).hexdigest()
                for item in current_copies
            }
            if current_markers != tuple(markers) or current_hashes != dict(
                database_expected_hashes
            ):
                raise ValueError("purge database preflight changed")
            precommit_guard()

            now = _now_text()
            connection.execute(
                """INSERT INTO purge_jobs(
                    id, knowledge_id, plan_hash, status, tombstone_json,
                    residual_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.id,
                    plan.knowledge_id,
                    plan_hash,
                    PurgeStatus.PURGE_IN_PROGRESS.value,
                    tombstone_json,
                    "[]",
                    now,
                    now,
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
                        journal_locations[operation.id],
                        operation.expected_hash,
                        (
                            "completed"
                            if operation.location_kind.startswith("sqlite_")
                            else "pending"
                        ),
                        recovery_payloads.get(operation.id, ""),
                    ),
                )

            expected_locators = set(database_expected_hashes)
            for _, table, _, column in _PURGE_SQLITE_FIELDS:
                rows = connection.execute(
                    f"SELECT rowid AS purge_rowid, {_purge_key_expression(table)} "
                    f"AS record_key, {column} AS content FROM {table}"
                ).fetchall()
                for row in rows:
                    locator = f"{table}:{row['record_key']}:{column}"
                    if locator not in expected_locators:
                        continue
                    value = row["content"]
                    if table in {
                        "candidates",
                        "evidence",
                        "review_attempts",
                        "conflicts",
                        "audit_log",
                    }:
                        replacement: bytes | str = (
                            "{}"
                            if column in {"review_json", "result_json", "detail_json"}
                            else b""
                            if isinstance(value, bytes)
                            else ""
                        )
                    else:
                        replacement = _remove_sensitive_values(value, markers)
                    changed = replacement != value
                    if changed:
                        connection.execute(
                            f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                            (replacement, row["purge_rowid"]),
                        )

            connection.execute(
                "DELETE FROM knowledge_evidence WHERE knowledge_id = ?",
                (plan.knowledge_id,),
            )
            candidate_ids = tuple(
                sorted({str(row["candidate_id"]) for row in knowledge_rows})
            )
            if candidate_ids:
                connection.execute(
                    f"DELETE FROM candidate_evidence WHERE candidate_id IN "
                    f"({','.join('?' for _ in candidate_ids)})",
                    candidate_ids,
                )
            connection.execute(
                "DELETE FROM knowledge WHERE id = ?", (plan.knowledge_id,)
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="purge_started",
                    entity_type="purge_job",
                    entity_id=plan.id,
                    detail={
                        "operation_count": len(plan.operations),
                        "status": PurgeStatus.PURGE_IN_PROGRESS.value,
                    },
                ),
            )

    def get_purge_tombstone(self, knowledge_id: str) -> PurgeTombstone | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT tombstone_json FROM purge_jobs
                WHERE knowledge_id = ? AND tombstone_json != ''
                ORDER BY updated_at DESC, id DESC LIMIT 1""",
                (knowledge_id,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(str(row["tombstone_json"]))
            return PurgeTombstone(
                knowledge_id=str(payload["knowledge_id"]),
                actor=str(payload["actor"]),
                started_at=_datetime(payload["started_at"]),
                updated_at=_datetime(payload["updated_at"]),
                status=PurgeStatus(payload["status"]),
                operation_count=int(payload["operation_count"]),
                residual_count=int(payload["residual_count"]),
            )
        finally:
            connection.close()

    def get_purge_journal(self, knowledge_id: str) -> PurgeJournal | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT * FROM purge_jobs WHERE knowledge_id = ?
                ORDER BY updated_at DESC, id DESC LIMIT 1""",
                (knowledge_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                metadata = json.loads(str(row["plan_hash"]))
            except json.JSONDecodeError:
                metadata = {}
            operation_rows = connection.execute(
                """SELECT * FROM purge_operations WHERE purge_job_id = ?
                ORDER BY location_kind, id""",
                (row["id"],),
            ).fetchall()
            fingerprints = _purge_marker_fingerprints(metadata)
            return PurgeJournal(
                id=str(row["id"]),
                knowledge_id=str(row["knowledge_id"]),
                project_id=str(metadata.get("project_id", "")),
                marker_hash=str(metadata.get("marker_hash", "")),
                marker_length=int(metadata.get("marker_length", 0)),
                marker_fingerprints=fingerprints,
                status=PurgeStatus(row["status"]),
                tombstone_json=str(row["tombstone_json"]),
                operations=tuple(
                    PurgeJournalOperation(
                        id=str(item["id"]),
                        location_kind=str(item["location_kind"]),
                        locator=str(item["location"]),
                        expected_hash=str(item["expected_hash"]),
                        status=str(item["status"]),
                        recovery_json=str(item["error"]),
                    )
                    for item in operation_rows
                ),
            )
        finally:
            connection.close()

    def active_purge_block(
        self, *, project_id: str | None = None, knowledge_id: str | None = None
    ) -> str | None:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT knowledge_id, plan_hash, status FROM purge_jobs
                WHERE status IN (?, ?) ORDER BY updated_at, id""",
                (
                    PurgeStatus.PURGE_IN_PROGRESS.value,
                    PurgeStatus.PURGE_INCOMPLETE.value,
                ),
            ).fetchall()
            for row in rows:
                if (
                    knowledge_id is not None
                    and str(row["knowledge_id"]) != knowledge_id
                ):
                    continue
                if project_id is not None:
                    try:
                        metadata = json.loads(str(row["plan_hash"]))
                    except json.JSONDecodeError:
                        continue
                    if str(metadata.get("project_id", "")) != project_id:
                        continue
                return str(row["status"])
            return None
        finally:
            connection.close()

    def purge_database_has_fingerprint(
        self, marker_hash: str, marker_length: int
    ) -> bool:
        connection = self._connect()
        try:
            for _, table, _, column in _PURGE_SQLITE_FIELDS:
                rows = connection.execute(f"SELECT {column} AS content FROM {table}")
                for row in rows:
                    value = row["content"]
                    content = (
                        bytes(value)
                        if isinstance(value, bytes)
                        else str(value).encode("utf-8")
                    )
                    if _has_sha256_window(content, marker_hash, marker_length):
                        return True
            return False
        finally:
            connection.close()

    def mark_purge_operation(
        self, operation_id: str, status: str, error: str = ""
    ) -> None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT error FROM purge_operations WHERE id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"purge operation not found: {operation_id}")
            stored_error = ""
            if status == "failed" and row["error"]:
                try:
                    payload = json.loads(str(row["error"]))
                except json.JSONDecodeError:
                    payload = {}
                payload["last_error"] = error or "cleanup_failed"
                stored_error = json.dumps(
                    payload, separators=(",", ":"), sort_keys=True
                )
            cursor = connection.execute(
                "UPDATE purge_operations SET status = ?, error = ? WHERE id = ?",
                (status, stored_error, operation_id),
            )
            _require_row(cursor, "purge operation", operation_id)

    def purge_database_residual_kinds(
        self, markers: Sequence[bytes], locators: Sequence[str]
    ) -> tuple[str, ...]:
        connection = self._connect()
        try:
            expected = set(locators)
            kinds: set[str] = set()
            for kind, table, _, column in _PURGE_SQLITE_FIELDS:
                rows = connection.execute(
                    f"SELECT {_purge_key_expression(table)} AS record_key, "
                    f"{column} AS content FROM {table}"
                ).fetchall()
                for row in rows:
                    locator = f"{table}:{row['record_key']}:{column}"
                    if locator not in expected:
                        continue
                    value = row["content"]
                    content = (
                        bytes(value)
                        if isinstance(value, bytes)
                        else str(value).encode("utf-8")
                    )
                    if _contains_sensitive_value(content, markers):
                        kinds.add(kind)
            return tuple(sorted(kinds))
        finally:
            connection.close()

    def finish_purge_incomplete(
        self,
        plan_id: str,
        *,
        tombstone_json: str,
        residual_kinds: Sequence[str],
        residual_operations: Sequence[tuple[PurgeOperation, str, str]],
        actor: str,
    ) -> None:
        safe_kinds = tuple(sorted(set(str(item) for item in residual_kinds)))
        residual_count = int(json.loads(tombstone_json)["residual_count"])
        with self.transaction() as connection:
            for operation, locator, recovery_json in residual_operations:
                connection.execute(
                    """INSERT INTO purge_operations(
                        id, purge_job_id, location_kind, location,
                        expected_hash, status, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING""",
                    (
                        operation.id,
                        plan_id,
                        operation.location_kind,
                        locator,
                        operation.expected_hash,
                        "pending",
                        recovery_json,
                    ),
                )
            residual_labels: list[dict[str, str]] = []
            kind_ordinals: dict[str, int] = {}
            for location_kind, status in connection.execute(
                """SELECT location_kind, status FROM purge_operations
                WHERE purge_job_id = ? ORDER BY location_kind, id""",
                (plan_id,),
            ):
                if status == "completed":
                    continue
                ordinal = kind_ordinals.get(location_kind, 0) + 1
                kind_ordinals[location_kind] = ordinal
                residual_labels.append(
                    {
                        "location_kind": location_kind,
                        "location": f"{location_kind}:residual:{ordinal}",
                    }
                )
            for location_kind in safe_kinds:
                if location_kind in kind_ordinals:
                    continue
                kind_ordinals[location_kind] = 1
                residual_labels.append(
                    {
                        "location_kind": location_kind,
                        "location": f"{location_kind}:residual:1",
                    }
                )
            residual_labels.sort(
                key=lambda item: (item["location_kind"], item["location"])
            )
            cursor = connection.execute(
                """UPDATE purge_jobs SET status = ?, tombstone_json = ?,
                    residual_json = ?, updated_at = ? WHERE id = ?""",
                (
                    PurgeStatus.PURGE_INCOMPLETE.value,
                    tombstone_json,
                    json.dumps(residual_labels, separators=(",", ":")),
                    _now_text(),
                    plan_id,
                ),
            )
            _require_row(cursor, "purge plan", plan_id)
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="purge_incomplete",
                    entity_type="purge_job",
                    entity_id=plan_id,
                    detail={
                        "residual_count": residual_count,
                        "residual_kinds": safe_kinds,
                        "residual_locations": residual_labels,
                        "status": PurgeStatus.PURGE_INCOMPLETE.value,
                    },
                ),
            )

    def complete_purge(
        self,
        plan_id: str,
        *,
        tombstone_json: str,
        kind_counts: Mapping[str, int],
        actor: str,
    ) -> None:
        safe_counts = {
            str(kind): int(count) for kind, count in sorted(kind_counts.items())
        }
        with self.transaction() as connection:
            connection.execute("PRAGMA secure_delete = ON")
            job = connection.execute(
                "SELECT knowledge_id, created_at FROM purge_jobs WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if job is None:
                raise KeyError(f"purge plan not found: {plan_id}")
            operation_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM purge_operations WHERE purge_job_id = ?",
                    (plan_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "DELETE FROM purge_operations WHERE purge_job_id = ?",
                (plan_id,),
            )
            connection.execute(
                "DELETE FROM audit_log WHERE entity_type = 'purge_job' AND entity_id = ?",
                (plan_id,),
            )
            connection.execute("DELETE FROM purge_jobs WHERE id = ?", (plan_id,))
            tombstone_id = f"purged-{uuid4()}"
            now = _now_text()
            connection.execute(
                """INSERT INTO purge_jobs(
                    id, knowledge_id, plan_hash, status, tombstone_json,
                    residual_json, created_at, updated_at
                ) VALUES (?, ?, '', ?, ?, '[]', ?, ?)""",
                (
                    tombstone_id,
                    str(job["knowledge_id"]),
                    PurgeStatus.PURGED.value,
                    tombstone_json,
                    str(job["created_at"]),
                    now,
                ),
            )
            self._append_audit_record(
                connection,
                self._audit_entry(
                    actor=actor,
                    action="purge_succeeded",
                    entity_type="purge_job",
                    entity_id=tombstone_id,
                    detail={
                        "kind_counts": safe_counts,
                        "operation_count": operation_count,
                        "status": PurgeStatus.PURGED.value,
                    },
                ),
            )

    @staticmethod
    def _purge_database_copies(
        connection: sqlite3.Connection, marker: bytes
    ) -> list[PurgeCopy]:
        copies: list[PurgeCopy] = []
        for kind, table, key_expression, column in _PURGE_SQLITE_FIELDS:
            rows = connection.execute(
                f"SELECT {key_expression} AS record_key, {column} AS content "
                f"FROM {table} ORDER BY record_key"
            ).fetchall()
            for stored in rows:
                value = stored["content"]
                content = (
                    bytes(value)
                    if isinstance(value, bytes)
                    else str(value).encode("utf-8")
                )
                if marker in content:
                    copies.append(
                        PurgeCopy(
                            kind,
                            f"{table}:{stored['record_key']}:{column}",
                            content,
                        )
                    )
        copies.sort(key=lambda item: (item.location_kind, item.locator))
        return copies

    def save_purge_plan(self, plan: PurgePlan, plan_hash: str, actor: str) -> None:
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

    def list_audit_entries(
        self, *, action: str | None = None, entity_id: str | None = None
    ) -> list[AuditEntry]:
        connection = self._connect()
        try:
            clauses: list[str] = []
            parameters: list[str] = []
            if action is not None:
                clauses.append("action = ?")
                parameters.append(action)
            if entity_id is not None:
                clauses.append("entity_id = ?")
                parameters.append(entity_id)
            sql = "SELECT * FROM audit_log"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at, id"
            rows = connection.execute(sql, tuple(parameters)).fetchall()
            return [_audit_from_row(row) for row in rows]
        finally:
            connection.close()

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


def _candidate_from_row(row: sqlite3.Row, evidence_ids: tuple[str, ...]) -> Candidate:
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


def _conflict_from_row(row: sqlite3.Row) -> KnowledgeConflict:
    return KnowledgeConflict(
        id=str(row["id"]),
        active_knowledge_id=str(row["active_knowledge_id"]),
        candidate_id=str(row["candidate_id"]),
        reason=str(row["reason"]),
        merge_text=str(row["merge_text"]),
        status=str(row["status"]),
    )


def _vault_adoption_from_row(row: sqlite3.Row) -> VaultAdoption:
    return VaultAdoption(
        candidate_id=str(row["candidate_id"]),
        project_id=str(row["project_id"]),
        knowledge_id=str(row["knowledge_id"]),
        original_version=int(row["original_version"]),
        original_text_hash=str(row["original_text_hash"]),
        relative_path=Path(row["relative_path"]),
        vault_managed_hash=str(row["vault_managed_hash"]),
        vault_full_hash=str(row["vault_full_hash"]),
        authority_hash=str(row["authority_hash"]),
        status=str(row["status"]),
        blocker=str(row["blocker"]),
    )


def _review_attempt_from_row(row: sqlite3.Row) -> ReviewAttempt:
    return ReviewAttempt(
        id=str(row["id"]),
        candidate_id=str(row["candidate_id"]),
        input_hash=str(row["input_hash"]),
        status=str(row["status"]),
        result_json=str(row["result_json"]),
        error=str(row["error"]),
    )


def _audit_from_row(row: sqlite3.Row) -> AuditEntry:
    return AuditEntry(
        id=str(row["id"]),
        actor=str(row["actor"]),
        action=str(row["action"]),
        entity_type=str(row["entity_type"]),
        entity_id=str(row["entity_id"]),
        before_hash=str(row["before_hash"]),
        after_hash=str(row["after_hash"]),
        detail_json=str(row["detail_json"]),
        created_at=_datetime(str(row["created_at"])),
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


def _has_sha256_window(content: bytes, expected_hash: str, length: int) -> bool:
    if length <= 0 or len(expected_hash) != 64 or len(content) < length:
        return False
    return any(
        hashlib.sha256(content[offset : offset + length]).hexdigest() == expected_hash
        for offset in range(len(content) - length + 1)
    )


def _purge_marker_fingerprints(
    metadata: Mapping[str, Any],
) -> tuple[tuple[str, int], ...]:
    fingerprints: list[tuple[str, int]] = []
    stored = metadata.get("marker_fingerprints", ())
    if isinstance(stored, list):
        for item in stored:
            if not isinstance(item, dict):
                continue
            marker_hash = str(item.get("hash", ""))
            try:
                length = int(item.get("length", 0))
            except (TypeError, ValueError):
                continue
            if len(marker_hash) == 64 and length > 0:
                fingerprints.append((marker_hash, length))
    if not fingerprints:
        marker_hash = str(metadata.get("marker_hash", ""))
        try:
            length = int(metadata.get("marker_length", 0))
        except (TypeError, ValueError):
            length = 0
        if len(marker_hash) == 64 and length > 0:
            fingerprints.append((marker_hash, length))
    return tuple(sorted(set(fingerprints), key=lambda item: (item[1], item[0])))


def _purge_key_expression(table: str) -> str:
    if table == "knowledge":
        return "id || ':' || version"
    if table == "managed_file_snapshots":
        return "path"
    return "id"


def _remove_sensitive_values(
    value: bytes | str, markers: Sequence[bytes]
) -> bytes | str:
    if isinstance(value, bytes):
        result = bytes(value)
        for marker in markers:
            result = result.replace(marker, b"")
        return result
    result_text = str(value)
    for marker in markers:
        result_text = result_text.replace(marker.decode("utf-8"), "")
    return result_text


def _contains_sensitive_value(content: bytes, markers: Sequence[bytes]) -> bool:
    return any(marker in content for marker in markers)
