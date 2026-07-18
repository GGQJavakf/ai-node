"""Core AgentRetro domain values.

The domain objects deliberately contain no persistence behavior.  They are
immutable values that can cross the application/infrastructure boundary
without exposing SQLite rows to later application services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class KnowledgeType(str, Enum):
    """Evidence-constrained knowledge categories."""

    RULE = "RULE"
    LESSON = "LESSON"
    TASK_STATE = "TASK_STATE"


class CandidateStatus(str, Enum):
    """Lifecycle states for extracted knowledge candidates."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONFLICT = "conflict"
    ARCHIVED = "archived"


class ReviewVerdict(str, Enum):
    """Structured review outcomes persisted with a candidate."""

    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REVIEW = "REVIEW"
    RETRY = "RETRY"


class PurgeStatus(str, Enum):
    """Lifecycle states for sensitive-knowledge purge plans."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PURGE_INCOMPLETE = "purge_incomplete"
    INCOMPLETE = "purge_incomplete"
    FAILED = "failed"


@dataclass(frozen=True)
class NormalizedSession:
    id: str
    source_session_id: str
    source_path: Path
    source_hash: str
    project_id: str
    status: str
    completed_at: datetime
    captured_at: datetime


@dataclass(frozen=True)
class Evidence:
    id: str
    session_id: str
    kind: str
    event_id: str
    content_hash: str
    excerpt: str


@dataclass(frozen=True)
class ReviewResult:
    verdict: ReviewVerdict
    confidence: float
    reason: str
    normalized_text: str
    duplicate: bool
    conflict: bool


@dataclass(frozen=True)
class Candidate:
    id: str
    session_id: str
    knowledge_type: KnowledgeType
    project_id: str
    scope: str
    proposed_text: str
    status: CandidateStatus
    extraction_confidence: float
    created_at: datetime
    updated_at: datetime
    evidence_ids: tuple[str, ...] = ()
    review: ReviewResult | None = None


@dataclass(frozen=True)
class ReviewAttempt:
    id: str
    candidate_id: str
    input_hash: str
    attempt_no: int
    status: str
    created_at: datetime
    result_json: str = ""
    error: str = ""


@dataclass(frozen=True)
class Knowledge:
    id: str
    version: int
    candidate_id: str
    knowledge_type: KnowledgeType
    project_id: str
    scope: str
    text: str
    status: str
    confidence: float
    accepted_by: str
    created_at: datetime
    valid_until: datetime | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeConflict:
    id: str
    active_knowledge_id: str
    candidate_id: str
    reason: str
    merge_text: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class SyncJob:
    id: str
    project_id: str
    status: str
    plan_json: str
    backup_path: Path
    created_at: datetime
    updated_at: datetime
    error: str = ""


@dataclass(frozen=True)
class ProjectMapping:
    id: str
    git_root: Path
    remote_identity: str
    obsidian_project: str
    active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PurgeOperation:
    id: str
    location_kind: str
    location: str
    expected_hash: str
    status: str
    error: str = ""


@dataclass(frozen=True)
class PurgePlan:
    id: str
    knowledge_id: str
    operations: tuple[PurgeOperation, ...]
    status: PurgeStatus
    created_at: datetime
    updated_at: datetime
    tombstone_json: str = ""
    residual_json: str = ""


@dataclass(frozen=True)
class AuditEntry:
    id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    before_hash: str
    after_hash: str
    detail: Mapping[str, Any]
    created_at: datetime
