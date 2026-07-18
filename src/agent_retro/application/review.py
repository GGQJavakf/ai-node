"""Deterministic review policy applied after independent model review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from agent_retro.domain.models import (
    Candidate,
    Evidence,
    KnowledgeType,
    ReviewResult,
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


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    blockers: tuple[str, ...]


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
    if candidate.knowledge_type is KnowledgeType.LESSON and not {
        "failure",
        "correction",
        "verification",
    } <= evidence_kinds:
        blockers.append("lesson_verification")

    result = tuple(blockers)
    return GateResult(allowed=not result, blockers=result)


def _is_speculative(candidate: Candidate, evidence: Sequence[Evidence]) -> bool:
    if any(item.kind.casefold() in {"inference", "speculation"} for item in evidence):
        return True
    normalized = f" {candidate.proposed_text.casefold()} "
    return any(marker in normalized for marker in _SPECULATION_MARKERS)
