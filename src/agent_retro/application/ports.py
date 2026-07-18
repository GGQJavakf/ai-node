"""Application-facing persistence contracts for AgentRetro."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

from agent_retro.domain.models import (
    AcceptanceDecision,
    AuditEntry,
    Candidate,
    CandidateStatus,
    Evidence,
    Knowledge,
    KnowledgeConflict,
    KnowledgeType,
    NormalizedSession,
    ProjectMapping,
    ProjectionEvent,
    ProjectionStatus,
    ManagedFileState,
    ManagedFileSnapshot,
    ManagedFileUpdate,
    Reclassification,
    PurgePlan,
    PurgeStatus,
    ReviewAttempt,
    ReviewResult,
    SyncJob,
    VaultAdoption,
)


@runtime_checkable
class RetroRepository(Protocol):
    """Typed boundary consumed by AgentRetro application services."""

    def migrate(self, target_version: int = 2) -> None: ...

    def transaction(self) -> AbstractContextManager[Any]: ...

    def find_session(
        self, source_session_id: str, source_hash: str
    ) -> NormalizedSession | None: ...

    def find_session_by_source_id(
        self, source_session_id: str
    ) -> NormalizedSession | None: ...

    def save_capture(
        self, session: NormalizedSession, evidence: Sequence[Evidence]
    ) -> None: ...

    def list_evidence(self, session_id: str) -> list[Evidence]: ...

    def save_candidates(self, candidates: Sequence[Candidate]) -> None: ...

    def save_manual_edit_candidate(
        self,
        candidate: Candidate,
        *,
        relative_path: Path,
        content_hash: str,
        adoption: VaultAdoption | None = None,
    ) -> Candidate: ...

    def get_vault_adoption(self, candidate_id: str) -> VaultAdoption | None: ...

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
    ) -> Knowledge: ...

    def get_candidate(self, candidate_id: str) -> Candidate | None: ...

    def list_candidates(self, status: CandidateStatus) -> list[Candidate]: ...

    def pending_model_candidates_for_session(
        self, session_id: str
    ) -> list[Candidate]: ...

    def candidates_for_session(self, session_id: str) -> list[Candidate]: ...

    def evidence_for_candidate(self, candidate_id: str) -> list[Evidence]: ...

    def save_review(
        self,
        candidate_id: str,
        result: ReviewResult,
        decision: AcceptanceDecision,
    ) -> None: ...

    def get_review_result(self, candidate_id: str) -> ReviewResult | None: ...

    def begin_review_attempt(self, attempt: ReviewAttempt) -> ReviewAttempt: ...

    def finish_review_attempt(
        self,
        attempt_id: str,
        status: str,
        result_json: str = "",
        error: str = "",
    ) -> None: ...

    def find_completed_review_attempt(
        self, candidate_id: str, input_hash: str
    ) -> ReviewAttempt | None: ...

    def review_attempts_for_candidate(
        self, candidate_id: str
    ) -> list[ReviewAttempt]: ...

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
    ) -> Knowledge: ...

    def reject_candidate(self, candidate_id: str, actor: str) -> Candidate: ...

    def knowledge_for_candidate(self, candidate_id: str) -> Knowledge | None: ...

    def knowledge_versions_for_candidate(
        self, candidate_id: str
    ) -> list[Knowledge]: ...

    def knowledge_versions(self, knowledge_id: str) -> list[Knowledge]: ...

    def list_active_knowledge(
        self, project_id: str, at: datetime
    ) -> list[Knowledge]: ...

    def list_brief_knowledge(
        self, project_id: str, at: datetime
    ) -> list[Knowledge]: ...

    def list_project_knowledge(self, project_id: str) -> list[Knowledge]: ...

    def save_conflict(self, conflict: KnowledgeConflict) -> None: ...

    def create_conflict(self, conflict: KnowledgeConflict) -> KnowledgeConflict: ...

    def get_conflict(self, conflict_id: str) -> KnowledgeConflict | None: ...

    def list_open_conflicts(self, project_id: str) -> list[KnowledgeConflict]: ...

    def resolve_conflict(
        self, conflict_id: str, text: str, actor: str
    ) -> Knowledge: ...

    def promote_global(self, knowledge_id: str, actor: str) -> Knowledge: ...

    def expire_task_states(self, at: datetime) -> list[Knowledge]: ...

    def archive_knowledge(self, knowledge_id: str, actor: str) -> Knowledge: ...

    def begin_sync(self, job: SyncJob) -> None: ...

    def finish_sync(self, job_id: str, status: str, error: str = "") -> None: ...

    def get_sync_job(self, job_id: str) -> SyncJob | None: ...

    def complete_sync(
        self,
        event_id: str,
        project_id: str,
        file_states: Sequence[ManagedFileUpdate],
        expected_input_hash: str,
    ) -> None: ...

    def projection_fence_matches(
        self, event_id: str, expected_input_hash: str
    ) -> bool: ...

    def has_rollback_required_sync(self) -> bool: ...

    def has_purge_incomplete(self) -> bool: ...

    def save_project_mapping(self, mapping: ProjectMapping, actor: str) -> None: ...

    def list_project_mappings(
        self, active_only: bool = True
    ) -> list[ProjectMapping]: ...

    def deactivate_project_mapping(self, mapping_id: str, actor: str) -> None: ...

    def reclassify_session(
        self,
        session_id: str,
        project_id: str,
        mapping_id: str,
        actor: str,
    ) -> Reclassification: ...

    def rollback_reclassification(
        self,
        reclassification: Reclassification,
        actor: str,
        affected_candidate_ids: Sequence[str] = (),
    ) -> None: ...

    def save_projection_event(
        self,
        event_id: str,
        project_id: str,
        cause: str,
        cause_entity_id: str,
        input_hash: str,
    ) -> str: ...

    def save_current_projection_event(
        self, project_id: str, cause: str, cause_entity_id: str
    ) -> str: ...

    def get_projection_event(self, event_id: str) -> ProjectionEvent | None: ...

    def list_projection_events(self, project_id: str) -> list[ProjectionEvent]: ...

    def finish_projection_event(
        self, event_id: str, status: ProjectionStatus, error: str = ""
    ) -> None: ...

    def projection_event_count(self, project_id: str) -> int: ...

    def save_managed_file_state(
        self,
        project_id: str,
        path: Path,
        managed_hash: str,
        full_hash: str,
    ) -> None: ...

    def get_managed_file_state(self, path: Path) -> ManagedFileState | None: ...

    def get_managed_file_snapshot(self, path: Path) -> ManagedFileSnapshot | None: ...

    def list_managed_file_states(self, project_id: str) -> list[ManagedFileState]: ...

    def save_purge_plan(self, plan: PurgePlan, plan_hash: str, actor: str) -> None: ...

    def finish_purge(
        self,
        plan_id: str,
        status: PurgeStatus,
        tombstone_json: str,
        residual_json: str,
    ) -> None: ...

    def append_audit(self, entry: AuditEntry) -> None: ...

    def list_audit_entries(
        self, *, action: str | None = None, entity_id: str | None = None
    ) -> list[AuditEntry]: ...
