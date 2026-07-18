"""User-controlled lifecycle operations for reviewed knowledge candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import (
    AuditEntry,
    Candidate,
    CandidateStatus,
    Knowledge,
    KnowledgeConflict,
    KnowledgeType,
)


class CandidateLifecycleError(ValueError):
    """The requested candidate transition is not allowed."""


@dataclass(frozen=True)
class KnowledgeHistory:
    knowledge_id: str
    versions: tuple[Knowledge, ...]
    audit_entries: tuple[AuditEntry, ...]


class KnowledgeService:
    """Apply explicit user decisions without weakening repository invariants."""

    def __init__(
        self,
        repository: RetroRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def accept(self, candidate_id: str, *, actor: str) -> Knowledge:
        candidate = self._pending_user_candidate(candidate_id, actor)
        return self.repository.accept_candidate(
            candidate.id,
            candidate.proposed_text,
            actor,
            self._confidence(candidate),
            valid_until=self._default_valid_until(candidate.knowledge_type),
        )

    def edit(
        self,
        candidate_id: str,
        *,
        text: str,
        actor: str,
        knowledge_type: KnowledgeType | None = None,
        scope: str | None = None,
        valid_until: datetime | None = None,
    ) -> Knowledge:
        candidate = self._pending_user_candidate(candidate_id, actor)
        selected_type = knowledge_type or candidate.knowledge_type
        selected_valid_until = (
            valid_until
            if valid_until is not None
            else self._default_valid_until(selected_type)
        )
        return self.repository.accept_candidate(
            candidate.id,
            text,
            actor,
            self._confidence(candidate),
            candidate_status=CandidateStatus.EDITED,
            valid_until=selected_valid_until,
            knowledge_type=selected_type,
            scope=scope or candidate.scope,
        )

    def reject(self, candidate_id: str, *, actor: str) -> Candidate:
        self._pending_user_candidate(candidate_id, actor)
        return self.repository.reject_candidate(candidate_id, actor)

    def detect_conflict(
        self,
        active_knowledge_id: str,
        candidate_id: str,
        *,
        reason: str,
        merge_text: str,
    ) -> KnowledgeConflict:
        identity = json.dumps(
            [active_knowledge_id, candidate_id, reason, merge_text],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        conflict = KnowledgeConflict(
            id="conflict-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
            active_knowledge_id=active_knowledge_id,
            candidate_id=candidate_id,
            reason=reason,
            merge_text=merge_text,
            status="open",
        )
        try:
            return self.repository.create_conflict(conflict)
        except ValueError as exc:
            raise CandidateLifecycleError(str(exc)) from exc

    def resolve_conflict(
        self,
        conflict_id: str,
        *,
        text: str,
        actor: str,
    ) -> Knowledge:
        self._require_user(actor)
        try:
            return self.repository.resolve_conflict(conflict_id, text, actor)
        except ValueError as exc:
            raise CandidateLifecycleError(str(exc)) from exc

    def promote_global(self, knowledge_id: str, *, actor: str) -> Knowledge:
        self._require_user(actor)
        try:
            return self.repository.promote_global(knowledge_id, actor)
        except ValueError as exc:
            raise CandidateLifecycleError(str(exc)) from exc

    def expire_task_states(self, at: datetime) -> list[Knowledge]:
        return self.repository.expire_task_states(at)

    def archive(self, knowledge_id: str, *, actor: str) -> Knowledge:
        self._require_user(actor)
        try:
            return self.repository.archive_knowledge(knowledge_id, actor)
        except ValueError as exc:
            raise CandidateLifecycleError(str(exc)) from exc

    def history(self, knowledge_id: str) -> KnowledgeHistory:
        versions = tuple(self.repository.knowledge_versions(knowledge_id))
        if not versions:
            raise KeyError(f"knowledge not found: {knowledge_id}")
        return KnowledgeHistory(
            knowledge_id=knowledge_id,
            versions=versions,
            audit_entries=tuple(
                self.repository.list_audit_entries(entity_id=knowledge_id)
            ),
        )

    def _pending_user_candidate(self, candidate_id: str, actor: str) -> Candidate:
        self._require_user(actor)
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        if candidate.status is not CandidateStatus.PENDING_REVIEW:
            raise CandidateLifecycleError(
                f"candidate {candidate_id} must be pending for manual lifecycle"
            )
        return candidate

    @staticmethod
    def _require_user(actor: str) -> None:
        if actor != "user":
            raise CandidateLifecycleError("manual lifecycle actor must be user")

    def _confidence(self, candidate: Candidate) -> float:
        review = self.repository.get_review_result(candidate.id)
        return candidate.extraction_confidence if review is None else review.confidence

    def _default_valid_until(self, kind: KnowledgeType) -> datetime | None:
        if kind is KnowledgeType.TASK_STATE:
            return self.clock() + timedelta(days=14)
        return None
