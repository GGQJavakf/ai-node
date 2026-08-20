"""Strict structured model adapters for extraction and independent review."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from agent_retro.domain.models import ReviewResult, ReviewVerdict


class StructuredModelResponseError(RuntimeError):
    """The model response did not contain the required structured content."""


class _LLMClient(Protocol):
    def request(
        self, payload: dict, stream: bool = False, timeout: int = 30
    ) -> object: ...


class ExtractedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    knowledge_type: Literal["RULE", "LESSON", "TASK_STATE"]
    proposed_text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ReviewedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    verdict: Literal["ACCEPT", "EDIT", "REJECT"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    duplicate_of: str | None = None
    conflict_with: str | None = None


_EXTRACTION_ADAPTER = TypeAdapter(list[ExtractedCandidate])
_EXTRACTION_PROMPT = (
    "Extract evidence-bound retrospective candidates. Return only a JSON array "
    "matching the supplied schema. For evidence_ids, copy only exact values from "
    "the input evidence objects' id fields; never use content_hash or invent IDs."
)
_REVIEW_PROMPT = (
    "Review one redacted retrospective candidate independently. Return only a "
    "JSON object matching the supplied schema. Judge evidence, wording, "
    "duplication, and conflict without relying on extraction reasoning."
)
_STRUCTURED_REPAIR_PROMPT = (
    "The previous response failed local structured validation. Retry once using "
    "the same input and return only content that exactly matches response_format."
)
_StructuredResult = TypeVar("_StructuredResult")


class LLMExtractionGateway:
    """Issue bounded extraction-only requests and parse them strictly."""

    def __init__(self, client: _LLMClient, *, model: str) -> None:
        self.client = client
        self.model = model

    def extract(
        self, redacted_evidence_json: str, *, timeout: int
    ) -> tuple[ExtractedCandidate, ...]:
        allowed_evidence_ids = _input_evidence_ids(redacted_evidence_json)
        item_schema = ExtractedCandidate.model_json_schema()
        if allowed_evidence_ids:
            item_schema["properties"]["evidence_ids"]["items"] = {
                "type": "string",
                "enum": list(allowed_evidence_ids),
            }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _EXTRACTION_PROMPT},
                {"role": "user", "content": redacted_evidence_json},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "agentretro_extracted_candidates",
                    "strict": True,
                    "schema": {
                        "type": "array",
                        "items": item_schema,
                    },
                },
            },
            "temperature": 0,
        }
        return tuple(
            _request_and_parse(
                self.client,
                payload,
                lambda content: _parse_extraction(
                    content, allowed_evidence_ids=allowed_evidence_ids
                ),
                timeout=timeout,
            )
        )


class LLMReviewGateway:
    """Issue distinct bounded review-only requests and parse them strictly."""

    def __init__(self, client: _LLMClient, *, model: str) -> None:
        self.client = client
        self.model = model

    def review(self, redacted_review_json: str, *, timeout: int) -> ReviewResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _REVIEW_PROMPT},
                {"role": "user", "content": redacted_review_json},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "agentretro_reviewed_candidate",
                    "strict": True,
                    "schema": ReviewedCandidate.model_json_schema(),
                },
            },
            "temperature": 0,
        }
        parsed = _request_and_parse(
            self.client,
            payload,
            lambda content: ReviewedCandidate.model_validate_json(content, strict=True),
            timeout=timeout,
        )
        return ReviewResult(
            verdict=ReviewVerdict(parsed.verdict),
            confidence=parsed.confidence,
            reason=parsed.reason,
            normalized_text=parsed.normalized_text,
            duplicate_of=parsed.duplicate_of,
            conflict_with=parsed.conflict_with,
        )


def _request_and_parse(
    client: _LLMClient,
    payload: dict,
    parser: Callable[[str], _StructuredResult],
    *,
    timeout: int,
) -> _StructuredResult:
    deadline = time.monotonic() + timeout
    response = client.request(payload, stream=False, timeout=timeout)
    try:
        return parser(_response_content(response))
    except (StructuredModelResponseError, ValidationError) as first_error:
        remaining = math.ceil(deadline - time.monotonic())
        if remaining <= 0:
            raise StructuredModelResponseError(
                "model response failed structured validation before retry deadline"
            ) from first_error
        repair_payload = {
            **payload,
            "messages": [
                *payload.get("messages", []),
                {"role": "system", "content": _STRUCTURED_REPAIR_PROMPT},
            ],
        }
        retry = getattr(client, "retry_after_structured_failure", client.request)
        retry_response = retry(
            repair_payload,
            stream=False,
            timeout=min(timeout, remaining),
        )
        try:
            return parser(_response_content(retry_response))
        except (StructuredModelResponseError, ValidationError) as retry_error:
            raise StructuredModelResponseError(
                "model response failed structured validation after one retry"
            ) from retry_error


def _input_evidence_ids(redacted_evidence_json: str) -> tuple[str, ...]:
    try:
        payload = json.loads(redacted_evidence_json)
        evidence = payload["evidence"]
        values = {
            item["id"]
            for item in evidence
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"].strip()
        }
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise StructuredModelResponseError(
            "extraction input is missing valid evidence IDs"
        ) from exc
    return tuple(sorted(values))


def _parse_extraction(
    content: str, *, allowed_evidence_ids: tuple[str, ...]
) -> list[ExtractedCandidate]:
    candidates = _EXTRACTION_ADAPTER.validate_json(content, strict=True)
    allowed = set(allowed_evidence_ids)
    if any(not set(item.evidence_ids) <= allowed for item in candidates):
        raise StructuredModelResponseError(
            "model response references unavailable evidence IDs"
        )
    return candidates


def _response_content(response: object) -> str:
    try:
        choices = response["choices"]  # type: ignore[index]
        content = choices[0]["message"]["content"]
    except (IndexError, KeyError, TypeError) as exc:
        raise StructuredModelResponseError(
            "model response is missing structured content"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise StructuredModelResponseError(
            "model response is missing structured content"
        )
    return content
