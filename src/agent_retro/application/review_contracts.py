"""Pure canonicalization, redaction, and safe-error helpers for review."""

from __future__ import annotations

import json
from typing import Callable, Sequence

from agent_retro.domain.models import Candidate, Evidence, ReviewResult, ReviewVerdict


def canonical_extraction_input(
    evidence: Sequence[Evidence], redact: Callable[[str], str]
) -> str:
    return canonical_json(
        {"evidence": [evidence_data(item, redact) for item in evidence]}
    )


def canonical_review_input(
    candidate: Candidate,
    evidence: Sequence[Evidence],
    redact: Callable[[str], str],
) -> str:
    return canonical_json(
        {
            "candidate": {
                "id": candidate.id,
                "knowledge_type": candidate.knowledge_type.value,
                "project_id": candidate.project_id,
                "scope": candidate.scope,
                "proposed_text": redact(candidate.proposed_text),
                "evidence_ids": list(candidate.evidence_ids),
                "extraction_confidence": candidate.extraction_confidence,
            },
            "evidence": [evidence_data(item, redact) for item in evidence],
        }
    )


def safe_error(exc: Exception) -> str:
    """Return a stable error code without retaining exception text."""

    name = type(exc).__name__
    if isinstance(exc, TimeoutError) or "Timeout" in name:
        return "MODEL_REVIEW_TIMEOUT"
    if name in {
        "StructuredModelResponseError",
        "ValidationError",
        "JSONDecodeError",
    }:
        return "MODEL_REVIEW_RESPONSE_INVALID"
    return "MODEL_REVIEW_FAILED"


def evidence_data(
    evidence: Evidence, redact: Callable[[str], str]
) -> dict[str, object]:
    return {
        "id": evidence.id,
        "kind": evidence.kind,
        "content_hash": evidence.locator.content_hash,
        "excerpt": redact(evidence.excerpt),
    }


def redacted_result(
    result: ReviewResult, redact: Callable[[str], str]
) -> ReviewResult:
    return ReviewResult(
        verdict=result.verdict,
        confidence=result.confidence,
        reason=redact(result.reason),
        normalized_text=redact(result.normalized_text),
        duplicate_of=(
            None if result.duplicate_of is None else redact(result.duplicate_of)
        ),
        conflict_with=(
            None if result.conflict_with is None else redact(result.conflict_with)
        ),
    )


def review_result_to_json(result: ReviewResult) -> str:
    return canonical_json(
        {
            "verdict": result.verdict.value,
            "confidence": result.confidence,
            "reason": result.reason,
            "normalized_text": result.normalized_text,
            "duplicate_of": result.duplicate_of,
            "conflict_with": result.conflict_with,
        }
    )


def review_result_from_json(value: str) -> ReviewResult:
    data = json.loads(value)
    return ReviewResult(
        verdict=ReviewVerdict(data["verdict"]),
        confidence=float(data["confidence"]),
        reason=str(data["reason"]),
        normalized_text=str(data["normalized_text"]),
        duplicate_of=data.get("duplicate_of"),
        conflict_with=data.get("conflict_with"),
    )


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
