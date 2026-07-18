"""Application-facing persistence contracts for AgentRetro."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

from agent_retro.domain.models import (
    AuditEntry,
    Candidate,
    CandidateStatus,
    Evidence,
    Knowledge,
    KnowledgeConflict,
    NormalizedSession,
    ProjectMapping,
    PurgePlan,
    PurgeStatus,
    ReviewAttempt,
    ReviewResult,
    SyncJob,
)


@runtime_checkable
class RetroRepository(Protocol):
    """Typed boundary consumed by AgentRetro application services."""

    def migrate(self, target_version: int = 1) -> None: ...

    def transaction(self) -> AbstractContextManager[Any]: ...

    def find_session(
        self, source_session_id: str, source_hash: str
    ) -> NormalizedSession | None: ...

    def save_capture(
        self, session: NormalizedSession, evidence: Sequence[Evidence]
    ) -> None: ...

    def list_evidence(self, session_id: str) -> list[Evidence]: ...

    def save_candidates(self, candidates: Sequence[Candidate]) -> None: ...

    def get_candidate(self, candidate_id: str) -> Candidate | None: ...

    def list_candidates(self, status: CandidateStatus) -> list[Candidate]: ...

    def save_review(self, candidate_id: str, result: ReviewResult) -> None: ...

    def begin_review_attempt(self, attempt: ReviewAttempt) -> ReviewAttempt: ...

    def finish_review_attempt(
        self,
        attempt_id: str,
        status: str,
        result_json: str = "",
        error: str = "",
    ) -> None: ...

    def accept_candidate(
        self, candidate_id: str, text: str, actor: str, confidence: float
    ) -> Knowledge: ...

    def list_active_knowledge(
        self, project_id: str, at: datetime
    ) -> list[Knowledge]: ...

    def save_conflict(self, conflict: KnowledgeConflict) -> None: ...

    def begin_sync(self, job: SyncJob) -> None: ...

    def finish_sync(
        self, job_id: str, status: str, error: str = ""
    ) -> None: ...

    def save_project_mapping(
        self, mapping: ProjectMapping, actor: str
    ) -> None: ...

    def list_project_mappings(
        self, active_only: bool = True
    ) -> list[ProjectMapping]: ...

    def deactivate_project_mapping(self, mapping_id: str, actor: str) -> None: ...

    def save_projection_event(
        self,
        event_id: str,
        project_id: str,
        cause: str,
        cause_entity_id: str,
        input_hash: str,
    ) -> str: ...

    def save_managed_file_state(
        self,
        project_id: str,
        path: Path,
        managed_hash: str,
        full_hash: str,
    ) -> None: ...

    def save_purge_plan(
        self, plan: PurgePlan, plan_hash: str, actor: str
    ) -> None: ...

    def finish_purge(
        self,
        plan_id: str,
        status: PurgeStatus,
        tombstone_json: str,
        residual_json: str,
    ) -> None: ...

    def append_audit(self, entry: AuditEntry) -> None: ...
