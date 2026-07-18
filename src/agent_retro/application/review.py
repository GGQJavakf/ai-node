"""Deterministic review policy applied after independent model review."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol, Sequence
from uuid import uuid4

from agent_retro.application.knowledge import (
    CandidateLifecycleError,
    KnowledgeService,
)
from agent_retro.application.ports import RetroRepository
from agent_retro.application.review_contracts import (
    canonical_extraction_input,
    canonical_json,
    canonical_review_input,
    redacted_result,
    review_result_from_json,
    review_result_to_json,
    safe_error,
)
from agent_retro.domain.models import (
    AcceptanceDecision,
    Candidate,
    CandidateStatus,
    Evidence,
    KnowledgeType,
    ReviewAttempt,
    ReviewResult,
    ReviewVerdict,
)


_THRESHOLDS = {
    KnowledgeType.RULE: 0.97,
    KnowledgeType.LESSON: 0.93,
    KnowledgeType.TASK_STATE: 0.90,
}
_AUTHORITY_KINDS = frozenset(
    {
        "authoritative",
        "developer_message",
        "project_rule",
        "system_message",
        "user",
        "user_instruction",
        "user_message",
    }
)
_SECRET_PATTERN = re.compile(
    r"(?:\[REDACTED\]|authorization\s*:|api[_-]?key\s*[=:]|"
    r"password\s*[=:]|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s]+:[^\s]+@)",
    re.IGNORECASE,
)
_SPECULATION_MARKERS = (
    " maybe ",
    " perhaps ",
    " probably ",
    " speculation ",
    "可能",
    "推测",
    "猜测",
)
_REAL_CAPTURE_KINDS = frozenset({"user", "assistant", "command"})
_LESSON_TEXT_PATTERNS = {
    "failure": re.compile(
        r"\b(?:failure|failed|error|exception|broken)\b|失败|报错|错误|异常|未通过",
        re.IGNORECASE,
    ),
    "correction": re.compile(
        r"\b(?:correction|corrected|fixed|repaired|replaced)\b|修复|更正|纠正|改为|替换",
        re.IGNORECASE,
    ),
    "verification": re.compile(
        r"\b(?:verification|verified|validated|confirmed|passed|exit code 0)\b|"
        r"验证|测试通过|已确认|校验通过",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    blockers: tuple[str, ...]


class ExtractedCandidateData(Protocol):
    knowledge_type: str
    proposed_text: str
    evidence_ids: list[str]
    confidence: float


class ExtractionGateway(Protocol):
    def extract(
        self, redacted_evidence_json: str, *, timeout: int
    ) -> Sequence[ExtractedCandidateData]: ...


class ReviewGateway(Protocol):
    def review(self, redacted_review_json: str, *, timeout: int) -> ReviewResult: ...


class ReviewUnavailableError(RuntimeError):
    """Stored candidates remain pending and can be retried safely."""

    def __init__(self, message: str, *, candidate_ids: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.candidate_ids = tuple(candidate_ids)


def threshold_passes(kind: KnowledgeType, confidence: float) -> bool:
    """Apply the fixed conservative acceptance floor for one knowledge type."""

    return confidence >= _THRESHOLDS[kind]


def evaluate_gates(
    candidate: Candidate,
    review: ReviewResult,
    evidence: Sequence[Evidence],
) -> GateResult:
    """Return every blocker in stable policy order.

    Model verdict and confidence never remove a deterministic blocker.
    """

    evidence_ids = {item.id for item in evidence}
    evidence_kinds = {item.kind.casefold() for item in evidence}
    texts = [candidate.proposed_text, review.normalized_text]
    texts.extend(item.excerpt for item in evidence)
    blockers: list[str] = []

    if any(_SECRET_PATTERN.search(text) for text in texts):
        blockers.append("secret")
    if not candidate.evidence_ids or not set(candidate.evidence_ids) <= evidence_ids:
        blockers.append("insufficient_evidence")
    if not candidate.project_id or candidate.project_id.startswith("awaiting:"):
        blockers.append("unknown_project")
    if review.duplicate_of:
        blockers.append("duplicate")
    if review.conflict_with:
        blockers.append("conflict")
    if _is_speculative(candidate, evidence):
        blockers.append("speculation")
    if (
        candidate.knowledge_type is KnowledgeType.RULE
        and not evidence_kinds.intersection(_AUTHORITY_KINDS)
    ):
        blockers.append("rule_authority")
    if (
        candidate.knowledge_type is KnowledgeType.LESSON
        and not _has_distinct_lesson_evidence(evidence)
    ):
        blockers.append("lesson_verification")

    result = tuple(blockers)
    return GateResult(allowed=not result, blockers=result)


def _is_speculative(candidate: Candidate, evidence: Sequence[Evidence]) -> bool:
    if any(item.kind.casefold() in {"inference", "speculation"} for item in evidence):
        return True
    normalized = f" {candidate.proposed_text.casefold()} "
    return any(marker in normalized for marker in _SPECULATION_MARKERS)


def _has_distinct_lesson_evidence(evidence: Sequence[Evidence]) -> bool:
    matches: dict[str, set[str]] = {name: set() for name in _LESSON_TEXT_PATTERNS}
    for item in evidence:
        kind = item.kind.casefold()
        for name, pattern in _LESSON_TEXT_PATTERNS.items():
            if kind == name or (
                kind in _REAL_CAPTURE_KINDS and pattern.search(item.excerpt)
            ):
                matches[name].add(item.id)
    return any(
        len({failure, correction, verification}) == 3
        for failure in matches["failure"]
        for correction in matches["correction"]
        for verification in matches["verification"]
    )


class ReviewService:
    """Persist extracted candidates, then review them through an independent call."""

    def __init__(
        self,
        repository: RetroRepository,
        extractor: ExtractionGateway,
        reviewer: ReviewGateway,
        *,
        model_timeout_seconds: int,
        redact: Callable[[str], str],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            isinstance(model_timeout_seconds, bool)
            or not isinstance(model_timeout_seconds, int)
            or model_timeout_seconds <= 0
        ):
            raise ValueError("model_timeout_seconds must be a positive integer")
        self.repository = repository
        self.extractor = extractor
        self.reviewer = reviewer
        self.model_timeout_seconds = model_timeout_seconds
        self.redact = redact
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def review_session(self, session_id: str) -> list[ReviewResult | None]:
        session = self.repository.find_session_by_source_id(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")
        existing = self.repository.candidates_for_session(session_id)
        pending = self.repository.pending_model_candidates_for_session(session_id)
        if pending:
            return self._review_candidates(pending)
        if existing:
            return [self.repository.get_review_result(item.id) for item in existing]
        evidence = self.repository.list_evidence(session.id)
        return self._extract_then_review(
            session.source_session_id, session.project_id, evidence
        )

    def review_stored_evidence(
        self,
        session_id: str,
        project_id: str,
        evidence: Sequence[Evidence],
    ) -> list[ReviewResult]:
        pending = self.repository.pending_model_candidates_for_session(session_id)
        candidates = (
            tuple(pending)
            if pending
            else self._extract_candidates(session_id, project_id, evidence)
        )
        results = self._review_candidates(candidates)
        if any(result is None for result in results):
            raise ReviewUnavailableError(
                "model review failed; retry is available for stored candidates",
                candidate_ids=tuple(item.id for item in candidates),
            )
        return [result for result in results if result is not None]

    def retry_candidate(self, candidate_id: str) -> ReviewResult | None:
        try:
            return self._retry_candidate(candidate_id)
        except ReviewUnavailableError:
            raise
        except Exception as exc:
            raise ReviewUnavailableError(
                f"model review failed; retry is available ({safe_error(exc)})",
                candidate_ids=(candidate_id,),
            ) from exc

    def _retry_candidate(self, candidate_id: str) -> ReviewResult | None:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        evidence = self.repository.evidence_for_candidate(candidate_id)
        input_json = canonical_review_input(candidate, evidence, self.redact)
        input_hash = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        completed = self.repository.find_completed_review_attempt(
            candidate_id, input_hash
        )
        if completed is not None:
            result = review_result_from_json(completed.result_json)
            self._apply_review_result(candidate, evidence, result)
            return result
        if candidate.status is not CandidateStatus.PENDING_REVIEW:
            return self.repository.get_review_result(candidate_id)

        attempt = self.repository.begin_review_attempt(
            ReviewAttempt(
                id=f"review-{uuid4()}",
                candidate_id=candidate_id,
                input_hash=input_hash,
                status="running",
                result_json="",
                error="",
            )
        )
        try:
            result = self.reviewer.review(
                input_json, timeout=self.model_timeout_seconds
            )
            result = redacted_result(result, self.redact)
        except Exception as exc:
            self.repository.finish_review_attempt(
                attempt.id, "failed", error=safe_error(exc)
            )
            return None
        self.repository.finish_review_attempt(
            attempt.id,
            "completed",
            result_json=review_result_to_json(result),
        )
        self._apply_review_result(candidate, evidence, result)
        return result

    def retry_session(self, session_id: str) -> list[ReviewResult | None]:
        return self._review_candidates(
            self.repository.pending_model_candidates_for_session(session_id)
        )

    def _extract_then_review(
        self,
        session_id: str,
        project_id: str,
        evidence: Sequence[Evidence],
    ) -> list[ReviewResult | None]:
        candidates = self._extract_candidates(session_id, project_id, evidence)
        return self._review_candidates(candidates)

    def _review_candidates(
        self, candidates: Sequence[Candidate]
    ) -> list[ReviewResult | None]:
        candidate_ids = tuple(candidate.id for candidate in candidates)
        try:
            return [
                self.retry_candidate(candidate_id) for candidate_id in candidate_ids
            ]
        except ReviewUnavailableError as exc:
            if exc.candidate_ids == candidate_ids:
                raise
            cause = exc.__cause__ or exc
            raise ReviewUnavailableError(
                f"model review failed; retry is available ({safe_error(cause)})",
                candidate_ids=candidate_ids,
            ) from cause
        except Exception as exc:
            raise ReviewUnavailableError(
                f"model review failed; retry is available ({safe_error(exc)})",
                candidate_ids=candidate_ids,
            ) from exc

    def _extract_candidates(
        self,
        session_id: str,
        project_id: str,
        evidence: Sequence[Evidence],
    ) -> tuple[Candidate, ...]:
        extraction_input = canonical_extraction_input(evidence, self.redact)
        try:
            extracted = self.extractor.extract(
                extraction_input, timeout=self.model_timeout_seconds
            )
        except Exception as exc:
            raise ReviewUnavailableError(
                f"model extraction failed; retry is available ({safe_error(exc)})"
            ) from exc
        candidates = tuple(
            self._candidate_from_extraction(session_id, project_id, item, evidence)
            for item in extracted
        )
        try:
            self.repository.save_candidates(candidates)
        except Exception as exc:
            raise ReviewUnavailableError(
                f"candidate persistence failed; retry is available ({safe_error(exc)})",
                candidate_ids=tuple(candidate.id for candidate in candidates),
            ) from exc
        return candidates

    def _candidate_from_extraction(
        self,
        session_id: str,
        project_id: str,
        item: ExtractedCandidateData,
        evidence: Sequence[Evidence],
    ) -> Candidate:
        evidence_ids = tuple(item.evidence_ids)
        known_ids = {entry.id for entry in evidence}
        if not evidence_ids or not set(evidence_ids) <= known_ids:
            raise ValueError("extracted candidate references unavailable evidence")
        text = self.redact(item.proposed_text)
        identity = canonical_json(
            [session_id, project_id, item.knowledge_type, text, evidence_ids]
        )
        return Candidate(
            id="candidate-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
            knowledge_type=KnowledgeType(item.knowledge_type),
            project_id=project_id,
            scope="project",
            proposed_text=text,
            evidence_ids=evidence_ids,
            status=CandidateStatus.PENDING_REVIEW,
            extraction_confidence=item.confidence,
        )

    def _apply_review_result(
        self,
        candidate: Candidate,
        evidence: Sequence[Evidence],
        result: ReviewResult,
    ) -> None:
        gates = evaluate_gates(candidate, result, evidence)
        threshold = _THRESHOLDS[candidate.knowledge_type]
        threshold_passed = threshold_passes(candidate.knowledge_type, result.confidence)
        decision = AcceptanceDecision(
            actor="model-review",
            threshold=threshold,
            threshold_passed=threshold_passed,
            blockers=gates.blockers,
            verdict=result.verdict,
            evidence_ids=candidate.evidence_ids,
        )
        self.repository.save_review(candidate.id, result, decision)
        if result.conflict_with is not None:
            try:
                KnowledgeService(self.repository).detect_conflict(
                    result.conflict_with,
                    candidate.id,
                    reason=result.reason,
                    merge_text=result.normalized_text,
                )
            except CandidateLifecycleError:
                # A model-supplied ID is advisory; deterministic gates and audit
                # retain the blocker even when no valid active item exists.
                pass
        if (
            result.verdict is not ReviewVerdict.ACCEPT
            or not threshold_passed
            or not gates.allowed
        ):
            return
        valid_until = (
            self.clock() + timedelta(days=14)
            if candidate.knowledge_type is KnowledgeType.TASK_STATE
            else None
        )
        self.repository.accept_candidate(
            candidate.id,
            result.normalized_text,
            actor="model-review",
            confidence=result.confidence,
            candidate_status=CandidateStatus.AUTO_ACCEPTED,
            valid_until=valid_until,
            decision=decision,
        )
