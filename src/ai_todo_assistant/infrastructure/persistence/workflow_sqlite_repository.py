"""SQLite workflow repository."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager

from ai_todo_assistant.domain.workflow import Evidence, WorkItem, WorkItemStatus, now_text


class SQLiteWorkflowRepository:
    def __init__(self, db_path: str = "data/todos.db"):
        self.db_path = db_path
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_schema()

    def save_work_item(self, item: WorkItem) -> WorkItem:
        item.updated_at = now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_items (
                    id, title, source, source_ref, status, priority, next_action,
                    project_path, sync_summary, last_synced_at, source_identities,
                    source_refs, merge_audit, merge_conflicts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    source = excluded.source,
                    source_ref = excluded.source_ref,
                    status = excluded.status,
                    priority = excluded.priority,
                    next_action = excluded.next_action,
                    project_path = excluded.project_path,
                    sync_summary = excluded.sync_summary,
                    last_synced_at = excluded.last_synced_at,
                    source_identities = excluded.source_identities,
                    source_refs = excluded.source_refs,
                    merge_audit = excluded.merge_audit,
                    merge_conflicts = excluded.merge_conflicts,
                    updated_at = excluded.updated_at
                """,
                _work_item_params(item),
            )
        return item

    def get_work_item(self, work_item_id: str) -> WorkItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
        return _row_to_work_item(row) if row else None

    def find_work_item_by_source(self, source: str, source_ref: str) -> WorkItem | None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM work_items WHERE source = ? AND source_ref = ? ORDER BY updated_at DESC LIMIT 1",
                (source, source_ref),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT * FROM work_items ORDER BY updated_at DESC",
                ).fetchall()
        for row in rows:
            item = _row_to_work_item(row)
            if item.source == source and item.source_ref == source_ref:
                return item
            if any(ref.get("source") == source and ref.get("source_ref") == source_ref for ref in item.source_refs):
                return item
        return None

    def find_work_items_by_identity(self, identity: str) -> list[WorkItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM work_items WHERE status != ? ORDER BY updated_at DESC",
                (WorkItemStatus.ARCHIVED.value,),
            ).fetchall()
        return [
            item for item in (_row_to_work_item(row) for row in rows)
            if identity in item.source_identities
        ]

    def list_work_items(self, include_closed: bool = False) -> list[WorkItem]:
        sql = "SELECT * FROM work_items"
        params: tuple = ()
        if not include_closed:
            sql += " WHERE status NOT IN (?, ?)"
            params = (WorkItemStatus.DONE.value, WorkItemStatus.ARCHIVED.value)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_work_item(row) for row in rows]

    def add_evidence(self, evidence: Evidence) -> Evidence:
        if not self.get_work_item(evidence.work_item_id):
            raise ValueError(f"未知工作项: {evidence.work_item_id}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO work_evidence (
                    id, work_item_id, evidence_type, summary, command,
                    output_excerpt, success, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _evidence_params(evidence),
            )
        return evidence

    def list_evidence(self, work_item_id: str) -> list[Evidence]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM work_evidence WHERE work_item_id = ? ORDER BY rowid ASC",
                (work_item_id,),
            ).fetchall()
        return [_row_to_evidence(row) for row in rows]

    def move_evidence(self, from_work_item_id: str, to_work_item_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM work_evidence WHERE work_item_id = ? ORDER BY rowid ASC",
                (from_work_item_id,),
            ).fetchall()
            moved = [str(row["id"]) for row in rows]
            conn.execute(
                "UPDATE work_evidence SET work_item_id = ? WHERE work_item_id = ?",
                (to_work_item_id, from_work_item_id),
            )
        return moved

    def move_evidence_ids(self, evidence_ids: list[str], to_work_item_id: str) -> list[str]:
        ids = [str(evidence_id) for evidence_id in evidence_ids if str(evidence_id).strip()]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM work_evidence WHERE id IN ({placeholders}) ORDER BY rowid ASC",
                tuple(ids),
            ).fetchall()
            moved = [str(row["id"]) for row in rows]
            if moved:
                conn.execute(
                    f"UPDATE work_evidence SET work_item_id = ? WHERE id IN ({placeholders})",
                    tuple([to_work_item_id] + moved),
                )
        return moved

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS work_items (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    next_action TEXT NOT NULL DEFAULT '',
                    project_path TEXT NOT NULL DEFAULT '',
                    sync_summary TEXT NOT NULL DEFAULT '',
                    last_synced_at TEXT,
                    source_identities TEXT NOT NULL DEFAULT '[]',
                    source_refs TEXT NOT NULL DEFAULT '[]',
                    merge_audit TEXT NOT NULL DEFAULT '[]',
                    merge_conflicts TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            _ensure_column(conn, "work_items", "source_identities", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "work_items", "source_refs", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "work_items", "merge_audit", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "work_items", "merge_conflicts", "TEXT NOT NULL DEFAULT '[]'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_work_items_source ON work_items(source, source_ref)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items(status)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS work_evidence (
                    id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    command TEXT NOT NULL DEFAULT '',
                    output_excerpt TEXT NOT NULL DEFAULT '',
                    success TEXT,
                    source TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(work_item_id) REFERENCES work_items(id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_work_evidence_work_item ON work_evidence(work_item_id)")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _work_item_params(item: WorkItem) -> tuple:
    return (
        item.id,
        item.title,
        item.source,
        item.source_ref,
        item.status,
        item.priority,
        item.next_action,
        item.project_path,
        item.sync_summary,
        item.last_synced_at,
        json.dumps(item.source_identities, ensure_ascii=False),
        json.dumps(item.source_refs, ensure_ascii=False),
        json.dumps(item.merge_audit, ensure_ascii=False),
        json.dumps(item.merge_conflicts, ensure_ascii=False),
        item.created_at,
        item.updated_at,
    )


def _evidence_params(evidence: Evidence) -> tuple:
    success = None if evidence.success is None else json.dumps(evidence.success)
    return (
        evidence.id,
        evidence.work_item_id,
        evidence.evidence_type,
        evidence.summary,
        evidence.command,
        evidence.output_excerpt,
        success,
        evidence.source,
        evidence.created_at,
    )


def _row_to_work_item(row: sqlite3.Row) -> WorkItem:
    data = dict(row)
    for key in ("source_identities", "source_refs", "merge_audit", "merge_conflicts"):
        if isinstance(data.get(key), str):
            try:
                data[key] = json.loads(data[key] or "[]")
            except json.JSONDecodeError:
                data[key] = []
    return WorkItem.from_dict(data)


def _row_to_evidence(row: sqlite3.Row) -> Evidence:
    data = dict(row)
    if data.get("success") is not None:
        data["success"] = json.loads(data["success"])
    return Evidence.from_dict(data)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
