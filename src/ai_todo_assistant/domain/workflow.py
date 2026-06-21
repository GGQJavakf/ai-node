"""Workflow domain models for the personal work assistant."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
import uuid


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class WorkItemStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    ARCHIVED = "archived"


class WorkItemSource(str, Enum):
    MANUAL = "manual"
    REDMINE = "redmine"
    CODEX = "codex"
    OPENSPEC = "openspec"
    GIT = "git"
    PLAYBOOK = "playbook"


class EvidenceType(str, Enum):
    COMMAND = "command"
    TEST = "test"
    NOTE = "note"
    REVIEW = "review"
    LINK = "link"
    SNAPSHOT = "snapshot"


@dataclass
class SourceSnapshot:
    source: str
    project_path: str = ""
    summary: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    command: str = ""
    success: bool = True
    error: str = ""
    captured_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "project_path": self.project_path,
            "summary": self.summary,
            "facts": self.facts,
            "command": self.command,
            "success": self.success,
            "error": self.error,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SourceSnapshot | None":
        if not data:
            return None
        raw_facts = data.get("facts")
        facts: dict[str, Any] = raw_facts if isinstance(raw_facts, dict) else {}
        return cls(
            source=str(data.get("source", "")),
            project_path=str(data.get("project_path", "")),
            summary=str(data.get("summary", "")),
            facts=facts,
            command=str(data.get("command", "")),
            success=bool(data.get("success", True)),
            error=str(data.get("error", "")),
            captured_at=str(data.get("captured_at") or now_text()),
        )


@dataclass
class WorkItem:
    title: str
    source: str = WorkItemSource.MANUAL.value
    source_ref: str = ""
    source_identities: list[str] = field(default_factory=list)
    source_refs: list[dict[str, str]] = field(default_factory=list)
    merge_audit: list[dict[str, Any]] = field(default_factory=list)
    merge_conflicts: list[str] = field(default_factory=list)
    status: str = WorkItemStatus.ACTIVE.value
    priority: str = "medium"
    next_action: str = ""
    project_path: str = ""
    sync_summary: str = ""
    last_synced_at: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=now_text)
    updated_at: str = field(default_factory=now_text)

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("工作项标题不能为空")
        if self.priority not in {"high", "medium", "low"}:
            self.priority = "medium"
        if self.status not in {item.value for item in WorkItemStatus}:
            self.status = WorkItemStatus.ACTIVE.value
        self.source_identities = _unique_texts(self.source_identities)
        self.source_refs = _clean_source_refs(self.source_refs)
        if self.source_ref:
            _append_source_ref(self.source_refs, self.source, self.source_ref)
        self.merge_audit = [item for item in self.merge_audit if isinstance(item, dict)]
        self.merge_conflicts = _unique_texts(self.merge_conflicts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "source_ref": self.source_ref,
            "source_identities": list(self.source_identities),
            "source_refs": list(self.source_refs),
            "merge_audit": list(self.merge_audit),
            "merge_conflicts": list(self.merge_conflicts),
            "status": self.status,
            "priority": self.priority,
            "next_action": self.next_action,
            "project_path": self.project_path,
            "sync_summary": self.sync_summary,
            "last_synced_at": self.last_synced_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkItem":
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            title=str(data["title"]),
            source=str(data.get("source") or WorkItemSource.MANUAL.value),
            source_ref=str(data.get("source_ref") or ""),
            source_identities=_list_of_text(data.get("source_identities")),
            source_refs=_list_of_dict(data.get("source_refs")),
            merge_audit=_list_of_dict(data.get("merge_audit")),
            merge_conflicts=_list_of_text(data.get("merge_conflicts")),
            status=str(data.get("status") or WorkItemStatus.ACTIVE.value),
            priority=str(data.get("priority") or "medium"),
            next_action=str(data.get("next_action") or ""),
            project_path=str(data.get("project_path") or ""),
            sync_summary=str(data.get("sync_summary") or ""),
            last_synced_at=data.get("last_synced_at"),
            created_at=str(data.get("created_at") or now_text()),
            updated_at=str(data.get("updated_at") or now_text()),
        )


def _list_of_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return _unique_texts(value)


def _unique_texts(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _list_of_dict(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _clean_source_refs(value: Any) -> list[dict[str, str]]:
    refs = _list_of_dict(value)
    cleaned: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        source = str(ref.get("source") or "").strip()
        source_ref = str(ref.get("source_ref") or "").strip()
        if not source or not source_ref or (source, source_ref) in seen:
            continue
        cleaned.append(
            {
                "source": source,
                "source_ref": source_ref,
                "label": str(ref.get("label") or "").strip(),
            }
        )
        seen.add((source, source_ref))
    return cleaned


def _append_source_ref(refs: list[dict[str, str]], source: str, source_ref: str, label: str = "") -> None:
    source = source.strip()
    source_ref = source_ref.strip()
    if not source or not source_ref:
        return
    if any(ref.get("source") == source and ref.get("source_ref") == source_ref for ref in refs):
        return
    refs.append({"source": source, "source_ref": source_ref, "label": label})


@dataclass
class Evidence:
    work_item_id: str
    evidence_type: str
    summary: str
    command: str = ""
    output_excerpt: str = ""
    success: bool | None = None
    source: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=now_text)

    def __post_init__(self) -> None:
        self.summary = self.summary.strip()
        if not self.work_item_id.strip():
            raise ValueError("证据必须关联工作项")
        if not self.summary:
            raise ValueError("证据摘要不能为空")
        if self.evidence_type not in {item.value for item in EvidenceType}:
            self.evidence_type = EvidenceType.NOTE.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "work_item_id": self.work_item_id,
            "evidence_type": self.evidence_type,
            "summary": self.summary,
            "command": self.command,
            "output_excerpt": self.output_excerpt,
            "success": self.success,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            work_item_id=str(data["work_item_id"]),
            evidence_type=str(data.get("evidence_type") or EvidenceType.NOTE.value),
            summary=str(data["summary"]),
            command=str(data.get("command") or ""),
            output_excerpt=str(data.get("output_excerpt") or ""),
            success=data.get("success"),
            source=str(data.get("source") or ""),
            created_at=str(data.get("created_at") or now_text()),
        )
