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


class KnowledgeType(str, Enum):
    """Evidence-constrained knowledge categories."""

    RULE = "RULE"
    LESSON = "LESSON"
    TASK_STATE = "TASK_STATE"


class CandidateStatus(str, Enum):
    """Lifecycle states for extracted knowledge candidates."""

    PENDING_REVIEW = "pending_review"
    AUTO_ACCEPTED = "auto_accepted"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class ReviewVerdict(str, Enum):
    """Structured review outcomes persisted with a candidate."""

    ACCEPT = "ACCEPT"
    EDIT = "EDIT"
    REJECT = "REJECT"


class PurgeStatus(str, Enum):
    """Lifecycle states for sensitive-knowledge purge plans."""

    PLANNED = "planned"
    PURGE_INCOMPLETE = "purge_incomplete"
    PURGED = "purged"


class ProjectionStatus(str, Enum):
    """Lifecycle states for Obsidian projection work."""

    SYNCED = "synced"
    SYNC_PENDING = "sync_pending"
    ROLLBACK_REQUIRED = "rollback_required"


@dataclass(frozen=True)
class SourceLocator:
    session_id: str
    event_id: str
    source_path: str
    content_hash: str


@dataclass(frozen=True)
class NormalizedEvent:
    id: str
    kind: str
    content: str
    locator: SourceLocator


@dataclass(frozen=True)
class NormalizedSession:
    id: str
    source_session_id: str
    source_path: Path
    source_hash: str
    project_id: str
    completed: bool
    completed_at: datetime
    events: tuple[NormalizedEvent, ...]


@dataclass(frozen=True)
class Evidence:
    id: str
    session_id: str
    kind: str
    locator: SourceLocator
    excerpt: str


@dataclass(frozen=True)
class ReviewResult:
    verdict: ReviewVerdict
    confidence: float
    reason: str
    normalized_text: str
    duplicate_of: str | None
    conflict_with: str | None


@dataclass(frozen=True)
class Candidate:
    id: str
    knowledge_type: KnowledgeType
    project_id: str
    scope: str
    proposed_text: str
    evidence_ids: tuple[str, ...]
    status: CandidateStatus
    extraction_confidence: float


@dataclass(frozen=True)
class ReviewAttempt:
    id: str
    candidate_id: str
    input_hash: str
    status: str
    result_json: str
    error: str


@dataclass(frozen=True)
class AcceptanceDecision:
    """Typed automatic-acceptance facts persisted in the audit record."""

    actor: str
    threshold: float
    threshold_passed: bool
    blockers: tuple[str, ...]
    verdict: ReviewVerdict
    evidence_ids: tuple[str, ...]


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
    evidence_ids: tuple[str, ...]
    valid_until: datetime | None
    updated_at: datetime
    supersedes: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeConflict:
    id: str
    active_knowledge_id: str
    candidate_id: str
    reason: str
    merge_text: str
    status: str


@dataclass(frozen=True)
class SyncJob:
    id: str
    project_id: str
    status: str
    plan_json: str
    backup_path: Path
    error: str = ""


@dataclass(frozen=True)
class ProjectMapping:
    id: str
    git_root: Path
    remote_identity: str
    obsidian_project: str
    active: bool = True


@dataclass(frozen=True)
class Reclassification:
    """Typed compensation snapshot for a two-phase project reclassification."""

    session_id: str
    previous_project_id: str
    target_project_id: str
    mapping_id: str
    pending_candidate_ids: tuple[str, ...]
    preexisting_knowledge_versions: tuple[tuple[str, int], ...]
    preexisting_conflict_ids: tuple[str, ...]


@dataclass(frozen=True)
class PurgeOperation:
    id: str
    location_kind: str
    location: str
    expected_hash: str


@dataclass(frozen=True)
class PurgePlan:
    id: str
    knowledge_id: str
    operations: tuple[PurgeOperation, ...]
    status: PurgeStatus


@dataclass(frozen=True)
class AuditEntry:
    id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    before_hash: str
    after_hash: str
    detail_json: str
    created_at: datetime
