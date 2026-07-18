from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from _path import ROOT  # noqa: F401
from agent_retro.application.review import (
    ReviewService,
    ReviewUnavailableError,
    evaluate_gates,
    threshold_passes,
)
from agent_retro.domain.models import (
    Candidate,
    CandidateStatus,
    Evidence,
    KnowledgeType,
    NormalizedSession,
    ReviewAttempt,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
)
from agent_retro.infrastructure.llm_review import (
    ExtractedCandidate,
    LLMExtractionGateway,
    LLMReviewGateway,
    ReviewedCandidate,
    StructuredModelResponseError,
)
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


NOW = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)


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


class _Extractor:
    def __init__(self, candidates: tuple[ExtractedCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[str, int]] = []

    def extract(self, input_json: str, *, timeout: int):
        self.calls.append((input_json, timeout))
        return self.candidates


class _Reviewer:
    def __init__(self, result: ReviewResult, repository=None) -> None:
        self.result = result
        self.repository = repository
        self.calls: list[tuple[str, int]] = []

    def review(self, input_json: str, *, timeout: int):
        if self.repository is not None:
            assert self.repository.list_candidates(
                CandidateStatus.PENDING_REVIEW
            )
        self.calls.append((input_json, timeout))
        return self.result


def _repository_with_evidence(tmp_path, evidence: Evidence | None = None):
    repository = SQLiteRetroRepository(
        tmp_path / "retro.db", tmp_path / "backups"
    )
    repository.migrate()
    item = evidence or _evidence()
    repository.save_capture(
        NormalizedSession(
            id="session-1",
            source_session_id="source-session-1",
            source_path=tmp_path / "source-session-1.jsonl",
            source_hash="b" * 64,
            project_id="project-1",
            completed=True,
            completed_at=NOW,
            events=(),
        ),
        [item],
    )
    return repository, item


def _extracted(
    knowledge_type: str = "RULE",
    *,
    text: str = "Always run the focused test first.",
    confidence: float = 0.99,
) -> ExtractedCandidate:
    return ExtractedCandidate(
        knowledge_type=knowledge_type,
        proposed_text=text,
        evidence_ids=["evidence-1"],
        confidence=confidence,
    )


def _service(repository, extractor, reviewer):
    return ReviewService(
        repository,
        extractor,
        reviewer,
        model_timeout_seconds=19,
        redact=Redactor().redact,
        clock=lambda: NOW,
    )


def test_review_session_persists_candidate_before_independent_review(tmp_path):
    repository, _ = _repository_with_evidence(tmp_path)
    extractor = _Extractor((_extracted(),))
    reviewer = _Reviewer(_review(), repository)
    service = _service(repository, extractor, reviewer)

    results = service.review_session("source-session-1")

    assert results == [_review()]
    assert len(extractor.calls) == 1
    assert len(reviewer.calls) == 1
    assert extractor.calls[0][1] == reviewer.calls[0][1] == 19
    accepted = repository.list_candidates(CandidateStatus.AUTO_ACCEPTED)
    assert len(accepted) == 1
    knowledge = repository.knowledge_for_candidate(accepted[0].id)
    assert knowledge is not None
    assert knowledge.accepted_by == "model-review"
    assert repository.get_review_result(accepted[0].id) == _review()


def test_completed_review_retry_reuses_result_without_new_request_or_knowledge(
    tmp_path,
):
    repository, _ = _repository_with_evidence(tmp_path)
    extractor = _Extractor((_extracted(),))
    reviewer = _Reviewer(_review())
    service = _service(repository, extractor, reviewer)

    first = service.review_session("source-session-1")[0]
    candidate = repository.list_candidates(CandidateStatus.AUTO_ACCEPTED)[0]
    second = service.retry_candidate(candidate.id)

    assert first == second == _review()
    assert len(extractor.calls) == 1
    assert len(reviewer.calls) == 1
    assert len(repository.review_attempts_for_candidate(candidate.id)) == 1
    assert len(repository.knowledge_versions_for_candidate(candidate.id)) == 1


class _FailingReviewer:
    def __init__(self, error: Exception) -> None:
        self.error: Exception | None = error
        self.result = _review()
        self.calls: list[tuple[str, int]] = []

    def review(self, input_json: str, *, timeout: int):
        self.calls.append((input_json, timeout))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("model failed with SECRET_VALUE"),
        StructuredModelResponseError("invalid SECRET_VALUE response"),
        TimeoutError("timeout while using SECRET_VALUE"),
    ],
    ids=["model", "strict-parse", "timeout"],
)
def test_review_failure_is_sanitized_immutable_and_keeps_candidate_pending(
    tmp_path, failure
):
    repository, _ = _repository_with_evidence(tmp_path)
    reviewer = _FailingReviewer(failure)
    service = _service(repository, _Extractor((_extracted(),)), reviewer)

    assert service.review_session("source-session-1") == [None]

    candidate = repository.list_candidates(CandidateStatus.PENDING_REVIEW)[0]
    attempts = repository.review_attempts_for_candidate(candidate.id)
    assert len(attempts) == 1
    assert attempts[0].status == "failed"
    assert attempts[0].input_hash
    assert "SECRET_VALUE" not in attempts[0].error
    with pytest.raises(ValueError, match="already finished"):
        repository.finish_review_attempt(attempts[0].id, "completed")


def test_review_stored_evidence_redacts_inputs_and_reuses_pending_extraction(
    tmp_path,
):
    repository, evidence = _repository_with_evidence(tmp_path)
    supplied = replace(
        evidence,
        excerpt="Authorization: Bearer SECRET_VALUE",
    )
    extractor = _Extractor(
        (_extracted(text="api_key=SECRET_VALUE must never persist"),)
    )
    reviewer = _FailingReviewer(RuntimeError("SECRET_VALUE unavailable"))
    service = _service(repository, extractor, reviewer)

    with pytest.raises(ReviewUnavailableError, match="retry"):
        service.review_stored_evidence(
            "source-session-1", "project-1", [supplied]
        )

    candidate = repository.list_candidates(CandidateStatus.PENDING_REVIEW)[0]
    assert "SECRET_VALUE" not in candidate.proposed_text
    assert "[REDACTED]" in candidate.proposed_text
    assert "SECRET_VALUE" not in extractor.calls[0][0]
    assert "SECRET_VALUE" not in reviewer.calls[0][0]
    reviewer.error = None

    assert service.review_stored_evidence(
        "source-session-1", "project-1", [supplied]
    ) == [_review()]
    assert len(extractor.calls) == 1
    assert len(reviewer.calls) == 2


@pytest.mark.parametrize(
    ("evidence", "result"),
    [
        (_evidence(), replace(_review(), confidence=0.969)),
        (_evidence(), replace(_review(), verdict=ReviewVerdict.REJECT)),
        (_evidence(kind="assistant_message"), _review()),
    ],
    ids=["below-threshold", "model-reject", "blocked"],
)
def test_non_acceptable_review_result_is_saved_but_candidate_stays_pending(
    tmp_path, evidence, result
):
    repository, _ = _repository_with_evidence(tmp_path, evidence)
    service = _service(
        repository, _Extractor((_extracted(),)), _Reviewer(result)
    )

    assert service.review_session("source-session-1") == [result]

    candidate = repository.list_candidates(CandidateStatus.PENDING_REVIEW)[0]
    assert repository.get_review_result(candidate.id) == result
    assert repository.knowledge_for_candidate(candidate.id) is None
    assert repository.review_attempts_for_candidate(candidate.id)[0].status == (
        "completed"
    )


def test_auto_acceptance_audit_records_threshold_gates_actor_and_evidence(
    tmp_path,
):
    repository, _ = _repository_with_evidence(tmp_path)
    service = _service(
        repository, _Extractor((_extracted(),)), _Reviewer(_review())
    )

    service.review_session("source-session-1")

    candidate = repository.list_candidates(CandidateStatus.AUTO_ACCEPTED)[0]
    knowledge = repository.knowledge_for_candidate(candidate.id)
    assert knowledge is not None
    entries = repository.list_audit_entries(
        action="candidate_accepted", entity_id=knowledge.id
    )
    assert len(entries) == 1
    assert entries[0].actor == "model-review"
    detail = json.loads(entries[0].detail_json)
    assert detail == {
        "blockers": [],
        "candidate_id": candidate.id,
        "evidence_ids": ["evidence-1"],
        "threshold": 0.97,
        "verdict": "ACCEPT",
    }


def test_auto_accepted_task_state_defaults_to_fourteen_day_validity(tmp_path):
    repository, _ = _repository_with_evidence(tmp_path)
    result = replace(_review(), confidence=0.91)
    service = _service(
        repository,
        _Extractor((_extracted("TASK_STATE", confidence=0.91),)),
        _Reviewer(result),
    )

    service.review_session("source-session-1")

    candidate = repository.list_candidates(CandidateStatus.AUTO_ACCEPTED)[0]
    knowledge = repository.knowledge_for_candidate(candidate.id)
    assert knowledge is not None
    assert knowledge.valid_until == NOW + timedelta(days=14)


class _SequenceReviewer:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def review(self, input_json: str, *, timeout: int):
        self.calls.append(input_json)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_retry_session_only_calls_model_for_pending_model_dependent_candidates(
    tmp_path,
):
    repository, _ = _repository_with_evidence(tmp_path)
    low = replace(_review(), confidence=0.969)
    reviewer = _SequenceReviewer(
        [RuntimeError("temporary"), low, _review()]
    )
    service = _service(
        repository,
        _Extractor(
            (
                _extracted(text="First candidate."),
                _extracted(text="Second candidate."),
            )
        ),
        reviewer,
    )

    assert service.review_session("source-session-1") == [None, low]
    assert len(repository.list_candidates(CandidateStatus.PENDING_REVIEW)) == 2

    assert service.retry_session("source-session-1") == [_review()]
    assert len(reviewer.calls) == 3
    assert len(repository.list_candidates(CandidateStatus.AUTO_ACCEPTED)) == 1
    remaining = repository.list_candidates(CandidateStatus.PENDING_REVIEW)
    assert len(remaining) == 1
    assert remaining[0].proposed_text == "Second candidate."
