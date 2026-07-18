from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from _path import ROOT  # noqa: F401
from agent_retro.application.review import evaluate_gates, threshold_passes
from agent_retro.domain.models import (
    Candidate,
    CandidateStatus,
    Evidence,
    KnowledgeType,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
)
from agent_retro.infrastructure.llm_review import (
    ExtractedCandidate,
    LLMExtractionGateway,
    LLMReviewGateway,
    ReviewedCandidate,
)


def _candidate(
    knowledge_type: KnowledgeType = KnowledgeType.RULE,
    *,
    project_id: str = "project-1",
    evidence_ids: tuple[str, ...] = ("evidence-1",),
    text: str = "Always run the focused test first.",
) -> Candidate:
    return Candidate(
        id="candidate-1",
        knowledge_type=knowledge_type,
        project_id=project_id,
        scope="project",
        proposed_text=text,
        evidence_ids=evidence_ids,
        status=CandidateStatus.PENDING_REVIEW,
        extraction_confidence=0.99,
    )


def _evidence(
    evidence_id: str = "evidence-1",
    *,
    kind: str = "user_instruction",
    excerpt: str = "The user explicitly required focused tests first.",
) -> Evidence:
    return Evidence(
        id=evidence_id,
        session_id="session-1",
        kind=kind,
        locator=SourceLocator(
            session_id="source-session-1",
            event_id=evidence_id,
            source_path=str(Path("sessions") / "source-session-1.jsonl"),
            content_hash="a" * 64,
        ),
        excerpt=excerpt,
    )


def _review(
    *,
    duplicate_of: str | None = None,
    conflict_with: str | None = None,
) -> ReviewResult:
    return ReviewResult(
        verdict=ReviewVerdict.ACCEPT,
        confidence=0.99,
        reason="The evidence is explicit and traceable.",
        normalized_text="Always run the focused test first.",
        duplicate_of=duplicate_of,
        conflict_with=conflict_with,
    )


def test_extracted_candidate_is_strict_and_forbids_extra_fields():
    valid = {
        "knowledge_type": "RULE",
        "proposed_text": "Use the typed repository port.",
        "evidence_ids": ["evidence-1"],
        "confidence": 0.98,
    }

    assert ExtractedCandidate.model_validate(valid).knowledge_type == "RULE"
    with pytest.raises(ValidationError):
        ExtractedCandidate.model_validate({**valid, "confidence": "0.98"})
    with pytest.raises(ValidationError):
        ExtractedCandidate.model_validate({**valid, "reasoning": "hidden"})


def test_reviewed_candidate_is_strict_and_requires_complete_contract():
    valid = {
        "verdict": "ACCEPT",
        "confidence": 0.99,
        "reason": "Explicit evidence.",
        "normalized_text": "Use the typed repository port.",
        "duplicate_of": None,
        "conflict_with": None,
    }

    assert ReviewedCandidate.model_validate(valid).verdict == "ACCEPT"
    with pytest.raises(ValidationError):
        ReviewedCandidate.model_validate({**valid, "confidence": "0.99"})
    incomplete = dict(valid)
    incomplete.pop("reason")
    with pytest.raises(ValidationError):
        ReviewedCandidate.model_validate(incomplete)


@pytest.mark.parametrize(
    ("knowledge_type", "confidence", "expected"),
    [
        (KnowledgeType.RULE, 0.969, False),
        (KnowledgeType.RULE, 0.970, True),
        (KnowledgeType.LESSON, 0.929, False),
        (KnowledgeType.LESSON, 0.930, True),
        (KnowledgeType.TASK_STATE, 0.899, False),
        (KnowledgeType.TASK_STATE, 0.900, True),
    ],
)
def test_type_thresholds(knowledge_type, confidence, expected):
    assert threshold_passes(knowledge_type, confidence) is expected


@pytest.mark.parametrize(
    ("candidate", "review", "evidence", "blocker"),
    [
        (
            _candidate(),
            _review(),
            [_evidence(excerpt="Authorization: Bearer [REDACTED]")],
            "secret",
        ),
        (_candidate(evidence_ids=()), _review(), [], "insufficient_evidence"),
        (
            _candidate(project_id="awaiting:unknown"),
            _review(),
            [_evidence()],
            "unknown_project",
        ),
        (_candidate(), _review(duplicate_of="knowledge-1"), [_evidence()], "duplicate"),
        (_candidate(), _review(conflict_with="knowledge-1"), [_evidence()], "conflict"),
        (_candidate(), _review(), [_evidence(kind="speculation")], "speculation"),
        (
            _candidate(),
            _review(),
            [_evidence(kind="assistant_message")],
            "rule_authority",
        ),
        (
            _candidate(KnowledgeType.LESSON, evidence_ids=("failure", "correction")),
            _review(),
            [
                _evidence("failure", kind="failure"),
                _evidence("correction", kind="correction"),
            ],
            "lesson_verification",
        ),
    ],
)
def test_each_deterministic_gate_blocks(candidate, review, evidence, blocker):
    result = evaluate_gates(candidate, review, evidence)

    assert result.allowed is False
    assert blocker in result.blockers


def test_gate_blockers_are_returned_in_stable_policy_order():
    candidate = _candidate(project_id="awaiting:unknown", evidence_ids=())
    result = evaluate_gates(
        candidate,
        _review(duplicate_of="duplicate", conflict_with="conflict"),
        [_evidence(kind="speculation", excerpt="api_key=[REDACTED]")],
    )

    assert result.blockers == (
        "secret",
        "insufficient_evidence",
        "unknown_project",
        "duplicate",
        "conflict",
        "speculation",
        "rule_authority",
    )


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, bool, int]] = []
        self.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [
                                    {
                                        "knowledge_type": "RULE",
                                        "proposed_text": "Use typed ports.",
                                        "evidence_ids": ["evidence-1"],
                                        "confidence": 0.98,
                                    }
                                ]
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "verdict": "ACCEPT",
                                    "confidence": 0.99,
                                    "reason": "Explicit evidence.",
                                    "normalized_text": "Use typed ports.",
                                    "duplicate_of": None,
                                    "conflict_with": None,
                                }
                            )
                        }
                    }
                ]
            },
        ]

    def request(self, payload: dict, stream: bool = False, timeout: int = 30):
        self.calls.append((payload, stream, timeout))
        return self.responses[len(self.calls) - 1]


def test_extraction_and_review_use_independent_requests_and_forward_timeout():
    client = _RecordingClient()
    extractor = LLMExtractionGateway(client, model="test-model")
    reviewer = LLMReviewGateway(client, model="test-model")

    extracted = extractor.extract('{"evidence":[]}', timeout=17)
    reviewed = reviewer.review('{"candidate":{}}', timeout=23)

    assert len(extracted) == 1
    assert extracted[0].knowledge_type == "RULE"
    assert reviewed.verdict == ReviewVerdict.ACCEPT
    assert len(client.calls) == 2
    assert [call[2] for call in client.calls] == [17, 23]
    extraction_prompt = client.calls[0][0]["messages"][0]["content"]
    review_prompt = client.calls[1][0]["messages"][0]["content"]
    assert extraction_prompt != review_prompt
    assert "extract" in extraction_prompt.lower()
    assert "review" in review_prompt.lower()
    assert "reasoning" not in client.calls[1][0]["messages"][1]["content"].lower()
