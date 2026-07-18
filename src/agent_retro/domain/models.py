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
    PURGE_IN_PROGRESS = "purge_in_progress"
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
class ProjectionEvent:
    id: str
    project_id: str
    cause: str
    cause_entity_id: str
    input_hash: str
    status: ProjectionStatus
    error: str = ""


@dataclass(frozen=True)
class ManagedFileState:
    project_id: str
    path: Path
    managed_hash: str
    full_hash: str


@dataclass(frozen=True)
class ManagedFileSnapshot:
    project_id: str
    path: Path
    snapshot_kind: str
    owned_bytes: bytes
    managed_hash: str
    full_hash: str
    event_id: str


@dataclass(frozen=True)
class ManagedFileUpdate:
    path: Path
    managed_hash: str
    full_hash: str
    snapshot_kind: str
    owned_bytes: bytes
    event_id: str

    def __iter__(self):
        # Preserve the established tuple-shaped port for lightweight test doubles.
        yield self.path
        yield self.managed_hash
        yield self.full_hash


@dataclass(frozen=True)
class VaultAdoption:
    candidate_id: str
    project_id: str
    knowledge_id: str
    original_version: int
    original_text_hash: str
    relative_path: Path
    vault_managed_hash: str
    vault_full_hash: str
    authority_hash: str
    status: str = "pending_review"
    blocker: str = ""


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
    candidate_states: tuple[tuple[str, str, str], ...]
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
class PurgeCopy:
    """One ephemeral AgentRetro-owned SQLite copy considered by purge planning."""

    location_kind: str
    locator: str
    content: bytes


@dataclass(frozen=True)
class PurgeInspection:
    """Read-only database facts used to construct a purge manifest."""

    knowledge: Knowledge | None
    already_purged: bool
    sync_pending: bool
    copies: tuple[PurgeCopy, ...]


@dataclass(frozen=True)
class PurgeTombstone:
    """Content-free identity retained after an explicit purge begins."""

    knowledge_id: str
    actor: str
    started_at: datetime
    updated_at: datetime
    status: PurgeStatus
    operation_count: int
    residual_count: int


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
