"""SQLite purge inspection mechanics used by the repository facade."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from agent_retro.domain.models import (
    PurgeCopy,
    PurgeJournal,
    PurgeJournalOperation,
    PurgeStatus,
    PurgeTombstone,
)


@dataclass(frozen=True)
class _RelatedRows:
    candidate_ids: tuple[str, ...]
    candidates: Sequence[Any]
    evidence_ids: tuple[str, ...]
    evidence: Sequence[Any]
    reviews: Sequence[Any]
    conflicts: Sequence[Any]


def purge_entity_copies(
    connection: Any,
    knowledge_id: str,
    knowledge_rows: Sequence[Any] | None = None,
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
    related = _load_related_rows(connection, knowledge_id, rows)
    markers = _marker_values(rows, related)
    copies = _entity_copies(rows, knowledge_id, related)
    _append_related_copies(connection, knowledge_id, related, markers, copies)
    _append_project_copies(connection, rows, markers, copies)
    copies.sort(key=lambda item: (item.location_kind, item.locator))
    return markers, copies


def purge_tombstone_from_json(
    tombstone_json: str, datetime_parser: Callable[[str], Any]
) -> PurgeTombstone:
    payload = json.loads(tombstone_json)
    return PurgeTombstone(
        knowledge_id=str(payload["knowledge_id"]),
        actor=str(payload["actor"]),
        started_at=datetime_parser(str(payload["started_at"])),
        updated_at=datetime_parser(str(payload["updated_at"])),
        status=PurgeStatus(payload["status"]),
        operation_count=int(payload["operation_count"]),
        residual_count=int(payload["residual_count"]),
    )


def purge_journal_from_rows(
    job_row: Any,
    operation_rows: Sequence[Any],
    marker_fingerprints: Callable[[dict[str, object]], tuple[tuple[str, int], ...]],
) -> PurgeJournal:
    try:
        metadata = json.loads(str(job_row["plan_hash"]))
    except json.JSONDecodeError:
        metadata = {}
    return PurgeJournal(
        id=str(job_row["id"]),
        knowledge_id=str(job_row["knowledge_id"]),
        project_id=str(metadata.get("project_id", "")),
        marker_hash=str(metadata.get("marker_hash", "")),
        marker_length=int(metadata.get("marker_length", 0)),
        marker_fingerprints=marker_fingerprints(metadata),
        status=PurgeStatus(job_row["status"]),
        tombstone_json=str(job_row["tombstone_json"]),
        operations=tuple(_purge_journal_operation(row) for row in operation_rows),
    )


def purge_operation_error(existing: object, status: str, error: str) -> str:
    if status != "failed" or not existing:
        return ""
    try:
        payload = json.loads(str(existing))
    except json.JSONDecodeError:
        payload = {}
    payload["last_error"] = error or "cleanup_failed"
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def purge_residual_labels(
    operation_rows: Sequence[Sequence[object]], safe_kinds: Sequence[str]
) -> list[dict[str, str]]:
    labels: list[dict[str, str]] = []
    kind_ordinals: dict[str, int] = {}
    for location_kind_value, status_value in operation_rows:
        location_kind = str(location_kind_value)
        if status_value == "completed":
            continue
        ordinal = kind_ordinals.get(location_kind, 0) + 1
        kind_ordinals[location_kind] = ordinal
        labels.append(_residual_label(location_kind, ordinal))
    for location_kind in safe_kinds:
        if location_kind in kind_ordinals:
            continue
        kind_ordinals[location_kind] = 1
        labels.append(_residual_label(location_kind, 1))
    labels.sort(key=lambda item: (item["location_kind"], item["location"]))
    return labels


def _purge_journal_operation(row: Any) -> PurgeJournalOperation:
    return PurgeJournalOperation(
        id=str(row["id"]),
        location_kind=str(row["location_kind"]),
        locator=str(row["location"]),
        expected_hash=str(row["expected_hash"]),
        status=str(row["status"]),
        recovery_json=str(row["error"]),
    )


def _residual_label(location_kind: str, ordinal: int) -> dict[str, str]:
    return {
        "location_kind": location_kind,
        "location": f"{location_kind}:residual:{ordinal}",
    }


def _load_related_rows(
    connection: Any, knowledge_id: str, rows: Sequence[Any]
) -> _RelatedRows:
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
    evidence = _load_evidence(connection, ordered_evidence_ids)
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
    return _RelatedRows(
        candidate_ids,
        candidates,
        ordered_evidence_ids,
        evidence,
        reviews,
        conflicts,
    )


def _load_evidence(connection: Any, evidence_ids: tuple[str, ...]) -> Sequence[Any]:
    if not evidence_ids:
        return ()
    placeholders = ",".join("?" for _ in evidence_ids)
    return connection.execute(
        f"SELECT * FROM evidence WHERE id IN ({placeholders}) ORDER BY id",
        evidence_ids,
    ).fetchall()


def _marker_values(
    knowledge_rows: Sequence[Any], related: _RelatedRows
) -> tuple[bytes, ...]:
    values = {
        str(value).encode("utf-8")
        for value in (
            *(row["text"] for row in knowledge_rows),
            *(row["proposed_text"] for row in related.candidates),
            *(row["excerpt"] for row in related.evidence),
            *(
                row[field]
                for row in related.conflicts
                for field in ("reason", "merge_text")
            ),
        )
        if str(value)
    }
    return tuple(sorted(values, key=lambda item: (-len(item), item)))


def _entity_copies(
    knowledge_rows: Sequence[Any],
    knowledge_id: str,
    related: _RelatedRows,
) -> list[PurgeCopy]:
    copies: list[PurgeCopy] = []
    for row in knowledge_rows:
        _append_fields(
            copies,
            "sqlite_knowledge",
            "knowledge",
            f"{knowledge_id}:{row['version']}",
            row,
            "text",
        )
    _append_rows(
        copies,
        "sqlite_candidate",
        "candidates",
        related.candidates,
        ("proposed_text", "review_json"),
    )
    _append_rows(
        copies,
        "sqlite_evidence",
        "evidence",
        related.evidence,
        ("excerpt",),
    )
    _append_rows(
        copies,
        "sqlite_review",
        "review_attempts",
        related.reviews,
        ("result_json", "error"),
    )
    _append_rows(
        copies,
        "sqlite_conflict",
        "conflicts",
        related.conflicts,
        ("reason", "merge_text"),
    )
    return copies


def _append_rows(
    copies: list[PurgeCopy],
    kind: str,
    table: str,
    rows: Sequence[Any],
    fields: tuple[str, ...],
) -> None:
    for row in rows:
        _append_fields(copies, kind, table, row["id"], row, *fields)


def _append_fields(
    copies: list[PurgeCopy],
    kind: str,
    table: str,
    key: object,
    row: Any,
    *fields: str,
) -> None:
    for field in fields:
        value = row[field]
        content = bytes(value) if isinstance(value, bytes) else str(value).encode("utf-8")
        if content:
            copies.append(PurgeCopy(kind, f"{table}:{key}:{field}", content))


def _append_related_copies(
    connection: Any,
    knowledge_id: str,
    related: _RelatedRows,
    markers: tuple[bytes, ...],
    copies: list[PurgeCopy],
) -> None:
    related_values = tuple(
        sorted(
            {
                knowledge_id,
                *related.candidate_ids,
                *related.evidence_ids,
                *(str(row["id"]) for row in related.reviews),
                *(str(row["id"]) for row in related.conflicts),
            }
        )
    )
    placeholders = ",".join("?" for _ in related_values)
    audits = connection.execute(
        f"SELECT * FROM audit_log WHERE entity_id IN ({placeholders}) ORDER BY id",
        related_values,
    ).fetchall()
    projections = connection.execute(
        f"SELECT * FROM projection_events "
        f"WHERE cause_entity_id IN ({placeholders}) ORDER BY id",
        related_values,
    ).fetchall()
    _append_rows(
        copies, "sqlite_audit", "audit_log", audits, ("detail_json",)
    )
    for row in projections:
        _append_matching_fields(
            copies,
            "projection_events",
            row["id"],
            row,
            ("input_hash", "error"),
            markers,
        )


def _append_project_copies(
    connection: Any,
    knowledge_rows: Sequence[Any],
    markers: tuple[bytes, ...],
    copies: list[PurgeCopy],
) -> None:
    project_id = str(knowledge_rows[-1]["project_id"])
    for table, key_field, fields in (
        ("sync_jobs", "id", ("plan_json", "error")),
        ("managed_file_snapshots", "path", ("owned_bytes",)),
    ):
        project_rows = connection.execute(
            f"SELECT * FROM {table} WHERE project_id = ? ORDER BY {key_field}",
            (project_id,),
        ).fetchall()
        for row in project_rows:
            _append_matching_fields(
                copies, table, row[key_field], row, fields, markers
            )


def _append_matching_fields(
    copies: list[PurgeCopy],
    table: str,
    key: object,
    row: Any,
    fields: tuple[str, ...],
    markers: tuple[bytes, ...],
) -> None:
    for field in fields:
        value = row[field]
        content = bytes(value) if isinstance(value, bytes) else str(value).encode("utf-8")
        if content and any(marker in content for marker in markers):
            _append_fields(
                copies, "sqlite_projection", table, key, row, field
            )
