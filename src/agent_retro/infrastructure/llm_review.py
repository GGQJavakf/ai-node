"""Strict structured model adapters for extraction and independent review."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

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
    "matching the supplied schema; do not invent evidence IDs."
)
_REVIEW_PROMPT = (
    "Review one redacted retrospective candidate independently. Return only a "
    "JSON object matching the supplied schema. Judge evidence, wording, "
    "duplication, and conflict without relying on extraction reasoning."
)


class LLMExtractionGateway:
    """Issue one extraction-only model request and parse it strictly."""

    def __init__(self, client: _LLMClient, *, model: str) -> None:
        self.client = client
        self.model = model

    def extract(
        self, redacted_evidence_json: str, *, timeout: int
    ) -> tuple[ExtractedCandidate, ...]:
        response = self.client.request(
            {
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
                            "items": ExtractedCandidate.model_json_schema(),
                        },
                    },
                },
                "temperature": 0,
            },
            stream=False,
            timeout=timeout,
        )
        content = _response_content(response)
        return tuple(_EXTRACTION_ADAPTER.validate_json(content, strict=True))


class LLMReviewGateway:
    """Issue a distinct review-only model request and parse it strictly."""

    def __init__(self, client: _LLMClient, *, model: str) -> None:
        self.client = client
        self.model = model

    def review(self, redacted_review_json: str, *, timeout: int) -> ReviewResult:
        response = self.client.request(
            {
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
            },
            stream=False,
            timeout=timeout,
        )
        parsed = ReviewedCandidate.model_validate_json(
            _response_content(response), strict=True
        )
        return ReviewResult(
            verdict=ReviewVerdict(parsed.verdict),
            confidence=parsed.confidence,
            reason=parsed.reason,
            normalized_text=parsed.normalized_text,
            duplicate_of=parsed.duplicate_of,
            conflict_with=parsed.conflict_with,
        )


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
