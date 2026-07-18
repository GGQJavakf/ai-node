from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from _path import ROOT  # noqa: F401
from agent_retro.application.capture import CaptureService
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
    KnowledgeConflict,
    NormalizedSession,
    ProjectMapping,
    ReviewAttempt,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
)
from agent_retro.infrastructure.codex_sessions import CodexSessionSource
from agent_retro.infrastructure.llm_review import (
    ExtractedCandidate,
    LLMExtractionGateway,
    LLMReviewGateway,
    ReviewedCandidate,
    StructuredModelResponseError,
)
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.project_mapping import (
    ProjectMappingService,
    ProjectResolver,
)
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


def _synthetic_codex_event(kind: str, index: int, text: str) -> dict[str, object]:
    timestamp = f"2026-07-18T08:00:0{index}Z"
    if kind == "user":
        return {
            "version": 1,
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {
                "type": "user_message",
                "id": f"event-{index}",
                "message": text,
            },
        }
    if kind == "assistant":
        return {
            "version": 1,
            "type": "response_item",
            "timestamp": timestamp,
            "payload": {
                "type": "message",
                "id": f"event-{index}",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        }
    if kind == "command":
        return {
            "version": 1,
            "type": "response_item",
            "timestamp": timestamp,
            "payload": {
                "type": "function_call_output",
                "id": f"event-{index}",
                "call_id": f"call-{index}",
                "output": text,
            },
        }
    raise ValueError(f"unsupported synthetic Codex event kind: {kind}")


def _captured_real_vocabulary(tmp_path, events):
    codex_home = tmp_path / "codex-home"
    project_root = tmp_path / "project"
    project_root.mkdir()
    path = (
        codex_home
        / "sessions"
        / "2026"
        / "07"
        / "18"
        / "rollout-2026-07-18T08-00-00-11111111-1111-1111-1111-111111111111.jsonl"
    )
    path.parent.mkdir(parents=True)
    records = [
        {
            "version": 1,
            "type": "session_meta",
            "timestamp": "2026-07-18T08:00:00Z",
            "payload": {"id": "real-vocabulary", "cwd": str(project_root)},
        }
    ]
    records.extend(
        _synthetic_codex_event(kind, index, text)
        for index, (kind, text) in enumerate(events, start=1)
    )
    records.append(
        {
            "version": 1,
            "type": "event_msg",
            "timestamp": "2026-07-18T08:00:09Z",
            "payload": {"type": "task_complete", "id": "complete-1"},
        }
    )
    path.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8"
    )
    repository = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
    CaptureService(
        CodexSessionSource(codex_home),
        repository,
        Redactor(),
        ProjectResolver(
            [
                ProjectMapping(
                    id="mapping-1",
                    git_root=project_root,
                    remote_identity="",
                    obsidian_project="project-1",
                )
            ]
        ),
    ).capture_session("real-vocabulary")
    session = repository.find_session_by_source_id("real-vocabulary")
    assert session is not None
    return repository, repository.list_evidence(session.id)


@pytest.mark.parametrize(
    ("knowledge_type", "events", "normalized_text"),
    [
        (
            "RULE",
            [("user", "Requirement: Always run the focused test first.")],
            "Always run the focused test first.",
        ),
        (
            "LESSON",
            [
                ("user", "Failure: the focused test failed with an assertion error."),
                ("assistant", "Correction: changed the typed repository boundary."),
                ("command", "Verification: focused tests passed with exit code 0."),
            ],
            "Keep failure, correction, and verification evidence separate.",
        ),
    ],
)
def test_real_codex_capture_vocabulary_can_auto_accept_grounded_knowledge(
    tmp_path, knowledge_type, events, normalized_text
):
    repository, evidence = _captured_real_vocabulary(tmp_path, events)
    extractor = _Extractor(
        (
            ExtractedCandidate(
                knowledge_type=knowledge_type,
                proposed_text=normalized_text,
                evidence_ids=[item.id for item in evidence],
                confidence=0.99,
            ),
        )
    )
    result = replace(_review(), normalized_text=normalized_text)

    _service(repository, extractor, _Reviewer(result)).review_session("real-vocabulary")

    assert [item.kind for item in evidence] == [kind for kind, _ in events]
    accepted = repository.list_candidates(CandidateStatus.AUTO_ACCEPTED)
    assert len(accepted) == 1
    assert accepted[0].knowledge_type is KnowledgeType(knowledge_type)


def test_real_lesson_markers_must_be_explicit_and_on_distinct_evidence():
    evidence = [
        _evidence(
            "combined",
            kind="user",
            excerpt="Failure occurred. Correction applied. Verification passed.",
        ),
        _evidence("assistant", kind="assistant", excerpt="Implementation details."),
        _evidence("command", kind="command", excerpt="Process output."),
    ]
    candidate = _candidate(
        KnowledgeType.LESSON,
        evidence_ids=tuple(item.id for item in evidence),
        text="Keep evidence separate.",
    )

    result = evaluate_gates(candidate, _review(), evidence)

    assert "lesson_verification" in result.blockers


def test_real_assistant_evidence_is_not_rule_authority():
    result = evaluate_gates(_candidate(), _review(), [_evidence(kind="assistant")])

    assert "rule_authority" in result.blockers


def test_semantic_lesson_evidence_kinds_remain_supported():
    evidence = [
        _evidence("failure", kind="failure"),
        _evidence("correction", kind="correction"),
        _evidence("verification", kind="verification"),
    ]
    candidate = _candidate(
        KnowledgeType.LESSON,
        evidence_ids=tuple(item.id for item in evidence),
        text="Preserve verified corrections as lessons.",
    )

    assert evaluate_gates(candidate, _review(), evidence).allowed is True


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
            assert self.repository.list_candidates(CandidateStatus.PENDING_REVIEW)
        self.calls.append((input_json, timeout))
        return self.result


def _repository_with_evidence(
    tmp_path, evidence: Evidence | None = None, *, project_id: str = "project-1"
):
    repository = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
    item = evidence or _evidence()
    repository.save_capture(
        NormalizedSession(
            id="session-1",
            source_session_id="source-session-1",
            source_path=tmp_path / "source-session-1.jsonl",
            source_hash="b" * 64,
            project_id=project_id,
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


def test_pending_candidate_selection_does_not_hide_obsolete_completed_attempt(
    tmp_path,
):
    repository, _ = _repository_with_evidence(tmp_path)
    candidate = _candidate()
    repository.save_candidates([candidate])
    attempt = repository.begin_review_attempt(
        ReviewAttempt(
            id="attempt-obsolete",
            candidate_id=candidate.id,
            input_hash="obsolete-project-input",
            status="running",
            result_json="",
            error="",
        )
    )
    repository.finish_review_attempt(
        attempt.id,
        "completed",
        result_json=json.dumps(
            {
                "confidence": 0.99,
                "conflict_with": None,
                "duplicate_of": None,
                "normalized_text": "Old project result.",
                "reason": "Old project input.",
                "verdict": "ACCEPT",
            }
        ),
    )

    assert repository.pending_model_candidates_for_session("source-session-1") == [
        candidate
    ]


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
        service.review_stored_evidence("source-session-1", "project-1", [supplied])

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
    service = _service(repository, _Extractor((_extracted(),)), _Reviewer(result))

    assert service.review_session("source-session-1") == [result]

    candidate = repository.list_candidates(CandidateStatus.PENDING_REVIEW)[0]
    assert repository.get_review_result(candidate.id) == result
    assert repository.knowledge_for_candidate(candidate.id) is None
    assert repository.review_attempts_for_candidate(candidate.id)[0].status == (
        "completed"
    )


@pytest.mark.parametrize(
    ("evidence", "result", "threshold_passed", "blockers"),
    [
        (_evidence(), _review(), True, []),
        (_evidence(), replace(_review(), confidence=0.969), False, []),
        (
            _evidence(),
            replace(_review(), verdict=ReviewVerdict.REJECT),
            True,
            [],
        ),
        (_evidence(kind="assistant"), _review(), True, ["rule_authority"]),
    ],
    ids=["accepted", "below-threshold", "rejected", "blocked"],
)
def test_every_model_review_persists_complete_ordered_decision_audit(
    tmp_path, evidence, result, threshold_passed, blockers
):
    repository, _ = _repository_with_evidence(tmp_path, evidence)
    service = _service(repository, _Extractor((_extracted(),)), _Reviewer(result))

    service.review_session("source-session-1")

    candidate = repository.candidates_for_session("source-session-1")[0]
    entries = repository.list_audit_entries(
        action="review_saved", entity_id=candidate.id
    )
    assert len(entries) == 1
    assert entries[0].actor == "model-review"
    assert json.loads(entries[0].detail_json) == {
        "blockers": blockers,
        "evidence_ids": ["evidence-1"],
        "threshold": 0.97,
        "threshold_passed": threshold_passed,
        "verdict": result.verdict.value,
    }


def test_auto_acceptance_audit_records_threshold_gates_actor_and_evidence(
    tmp_path,
):
    repository, _ = _repository_with_evidence(tmp_path)
    service = _service(repository, _Extractor((_extracted(),)), _Reviewer(_review()))

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
        "threshold_passed": True,
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


def _repository_with_active_rule_and_pending_candidate(tmp_path):
    repository, _ = _repository_with_evidence(tmp_path)
    active_candidate = replace(_candidate(), id="candidate-active")
    repository.save_candidates([active_candidate])
    active = repository.accept_candidate(
        active_candidate.id,
        active_candidate.proposed_text,
        actor="user",
        confidence=0.99,
    )
    pending = replace(
        _candidate(text="Use a corrected typed boundary."),
        id="candidate-conflict",
    )
    repository.save_candidates([pending])
    return repository, active, pending


def test_valid_model_conflict_is_redacted_deterministic_and_idempotent(tmp_path):
    repository, active, pending = _repository_with_active_rule_and_pending_candidate(
        tmp_path
    )
    result = _review(conflict_with=active.id)
    result = replace(
        result,
        normalized_text="Use the corrected boundary; api_key=must-not-persist",
    )
    service = _service(repository, _Extractor(()), _Reviewer(result))

    first = service.retry_candidate(pending.id)
    second = service.retry_candidate(pending.id)

    assert first == second
    assert repository.get_candidate(pending.id).status is CandidateStatus.PENDING_REVIEW
    assert repository.list_active_knowledge("project-1", NOW) == [active]
    entries = repository.list_audit_entries(action="conflict_saved", entity_id=None)
    assert len(entries) == 1
    conflict = repository.get_conflict(entries[0].entity_id)
    assert conflict is not None
    assert conflict.active_knowledge_id == active.id
    assert conflict.candidate_id == pending.id
    assert "must-not-persist" not in conflict.merge_text
    assert "[REDACTED]" in conflict.merge_text


def test_hallucinated_conflict_id_is_only_an_audited_blocker(tmp_path):
    repository, _, pending = _repository_with_active_rule_and_pending_candidate(
        tmp_path
    )
    result = _review(conflict_with="knowledge-does-not-exist")
    service = _service(repository, _Extractor(()), _Reviewer(result))

    assert service.retry_candidate(pending.id) == result

    assert repository.get_candidate(pending.id).status is CandidateStatus.PENDING_REVIEW
    assert repository.list_audit_entries(action="conflict_saved") == []
    decision = repository.list_audit_entries(
        action="review_saved", entity_id=pending.id
    )[0]
    assert json.loads(decision.detail_json)["blockers"] == ["conflict"]


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


def _save_review_mapping(repository):
    mapping = ProjectMapping(
        id="mapping-1",
        git_root=Path("D:/projects/example"),
        remote_identity="example.invalid/team/repo",
        obsidian_project="project-1",
    )
    repository.save_project_mapping(mapping, actor="user")
    return mapping


def test_reclassify_reviews_new_project_then_auto_accepts_with_terminal_reuse(
    tmp_path,
):
    repository, evidence = _repository_with_evidence(
        tmp_path, project_id="awaiting:unknown"
    )
    mapping = _save_review_mapping(repository)
    reviewer = _SequenceReviewer([_review(), _review()])
    service = _service(repository, _Extractor((_extracted(),)), reviewer)
    mapping_service = ProjectMappingService(
        repository,
        vault_root=tmp_path / "vault",
        review_stored_evidence=service.review_stored_evidence,
    )

    mapping_service.reclassify("source-session-1", mapping.id)

    session = repository.find_session_by_source_id("source-session-1")
    assert session is not None and session.project_id == "project-1"
    candidate = repository.candidates_for_session("source-session-1")[0]
    assert candidate.project_id == "project-1"
    assert candidate.status is CandidateStatus.AUTO_ACCEPTED
    assert repository.knowledge_for_candidate(candidate.id) is not None
    assert len(reviewer.calls) == 2
    decisions = repository.list_audit_entries(
        action="review_saved", entity_id=candidate.id
    )
    assert [json.loads(item.detail_json)["blockers"] for item in decisions] == [
        ["unknown_project"],
        [],
    ]
    assert service.review_session("source-session-1") == [_review()]
    assert service.retry_candidate(candidate.id) == _review()
    assert len(reviewer.calls) == 2
    assert (
        len(
            repository.list_audit_entries(action="review_saved", entity_id=candidate.id)
        )
        == 2
    )
    assert not (tmp_path / "source-session-1.jsonl").exists()
    assert evidence


def test_reclassification_rollback_preserves_preexisting_candidate_conflict(tmp_path):
    awaiting = "awaiting:unknown"
    repository, _ = _repository_with_evidence(tmp_path, project_id=awaiting)
    active_candidate = replace(_candidate(project_id=awaiting), id="candidate-active")
    pending = replace(
        _candidate(project_id=awaiting, text="Conflicting pending rule."),
        id="candidate-pending",
    )
    repository.save_candidates([active_candidate, pending])
    active = repository.accept_candidate(
        active_candidate.id,
        active_candidate.proposed_text,
        actor="user",
        confidence=0.99,
    )
    existing = repository.create_conflict(
        KnowledgeConflict(
            id="conflict-preexisting",
            active_knowledge_id=active.id,
            candidate_id=pending.id,
            reason="Preexisting conflict.",
            merge_text="Preexisting merge text.",
            status="open",
        )
    )
    mapping = _save_review_mapping(repository)
    calls = 0

    def fail_second_phase(session_id, project_id, evidence):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ReviewUnavailableError("retry")

    mapping_service = ProjectMappingService(
        repository,
        vault_root=tmp_path / "vault",
        review_stored_evidence=fail_second_phase,
    )

    with pytest.raises(ReviewUnavailableError, match="retry"):
        mapping_service.reclassify("source-session-1", mapping.id)

    assert repository.get_conflict(existing.id) == existing
    assert repository.get_candidate(pending.id).project_id == awaiting


def test_reclassify_second_phase_failure_rolls_back_all_candidates_and_retries(
    tmp_path,
):
    awaiting = "awaiting:unknown"
    repository, _ = _repository_with_evidence(tmp_path, project_id=awaiting)
    mapping = _save_review_mapping(repository)
    reviewer = _SequenceReviewer(
        [
            _review(),
            _review(),
            _review(),
            RuntimeError("second phase unavailable"),
            _review(),
        ]
    )
    service = _service(
        repository,
        _Extractor(
            (
                _extracted(text="First typed rule."),
                _extracted(text="Second typed rule."),
            )
        ),
        reviewer,
    )
    mapping_service = ProjectMappingService(
        repository,
        vault_root=tmp_path / "vault",
        review_stored_evidence=service.review_stored_evidence,
    )

    with pytest.raises(ReviewUnavailableError, match="retry"):
        mapping_service.reclassify("source-session-1", mapping.id)

    session = repository.find_session_by_source_id("source-session-1")
    assert session is not None and session.project_id == awaiting
    rolled_back = repository.candidates_for_session("source-session-1")
    assert len(rolled_back) == 2
    assert all(item.project_id == awaiting for item in rolled_back)
    assert all(item.status is CandidateStatus.PENDING_REVIEW for item in rolled_back)
    assert all(
        repository.knowledge_for_candidate(item.id) is None for item in rolled_back
    )
    assert len(reviewer.calls) == 4
    attempts = [
        attempt
        for candidate in rolled_back
        for attempt in repository.review_attempts_for_candidate(candidate.id)
    ]
    assert [item.status for item in attempts].count("completed") == 3
    assert [item.status for item in attempts].count("failed") == 1
    assert repository.list_audit_entries(
        action="session_reclassification_rolled_back",
        entity_id=session.id,
    )
    assert not (tmp_path / "source-session-1.jsonl").exists()

    mapping_service.reclassify("source-session-1", mapping.id)

    accepted = repository.candidates_for_session("source-session-1")
    assert all(item.project_id == "project-1" for item in accepted)
    assert all(item.status is CandidateStatus.AUTO_ACCEPTED for item in accepted)
    assert all(
        repository.knowledge_for_candidate(item.id) is not None for item in accepted
    )
    assert len(reviewer.calls) == 5
    assert service.review_session("source-session-1") == [
        repository.get_review_result(item.id) for item in accepted
    ]
    assert len(reviewer.calls) == 5


def test_reclassify_rolls_back_candidates_created_only_in_failed_second_phase(
    tmp_path,
):
    awaiting = "awaiting:unknown"
    repository, _ = _repository_with_evidence(tmp_path, project_id=awaiting)
    mapping = _save_review_mapping(repository)

    class PhasedExtractor:
        def __init__(self):
            self.calls = 0

        def extract(self, input_json: str, *, timeout: int):
            self.calls += 1
            if self.calls == 1:
                return ()
            return (
                _extracted(text="Accepted only after classification."),
                _extracted(text="Fails only after classification."),
            )

    reviewer = _SequenceReviewer(
        [
            _review(),
            RuntimeError("second-phase review unavailable"),
            _review(),
            _review(),
            _review(),
        ]
    )
    service = _service(repository, PhasedExtractor(), reviewer)
    mapping_service = ProjectMappingService(
        repository,
        vault_root=tmp_path / "vault",
        review_stored_evidence=service.review_stored_evidence,
    )

    with pytest.raises(ReviewUnavailableError, match="retry"):
        mapping_service.reclassify("source-session-1", mapping.id)

    session = repository.find_session_by_source_id("source-session-1")
    candidates = repository.candidates_for_session("source-session-1")
    assert session is not None and session.project_id == awaiting
    assert len(candidates) == 2
    assert all(item.project_id == awaiting for item in candidates)
    assert all(item.status is CandidateStatus.PENDING_REVIEW for item in candidates)
    assert all(
        repository.knowledge_for_candidate(item.id) is None for item in candidates
    )
    assert (
        sum(
            len(repository.review_attempts_for_candidate(item.id))
            for item in candidates
        )
        == 2
    )
    assert (
        sum(
            len(repository.list_audit_entries(action="review_saved", entity_id=item.id))
            for item in candidates
        )
        == 1
    )

    mapping_service.reclassify("source-session-1", mapping.id)

    converged = repository.candidates_for_session("source-session-1")
    assert all(item.project_id == "project-1" for item in converged)
    assert all(item.status is CandidateStatus.AUTO_ACCEPTED for item in converged)
    assert all(
        repository.knowledge_for_candidate(item.id) is not None for item in converged
    )
    assert len(reviewer.calls) == 5


def test_reclassify_wraps_finish_failure_with_new_second_phase_candidate_ids(
    tmp_path, monkeypatch
):
    awaiting = "awaiting:unknown"
    repository, evidence = _repository_with_evidence(tmp_path, project_id=awaiting)
    mapping = _save_review_mapping(repository)

    class PhasedExtractor:
        def __init__(self):
            self.calls = 0

        def extract(self, input_json: str, *, timeout: int):
            self.calls += 1
            return () if self.calls == 1 else (_extracted(),)

    reviewer = _SequenceReviewer([_review(), _review()])
    service = _service(repository, PhasedExtractor(), reviewer)
    original_finish = repository.finish_review_attempt
    injected = False

    def finish_then_fail(attempt_id, status, result_json="", error=""):
        nonlocal injected
        original_finish(attempt_id, status, result_json, error)
        if status == "completed" and not injected:
            injected = True
            raise RuntimeError("api_key=must-not-leak")

    monkeypatch.setattr(repository, "finish_review_attempt", finish_then_fail)
    mapping_service = ProjectMappingService(
        repository,
        vault_root=tmp_path / "vault",
        review_stored_evidence=service.review_stored_evidence,
    )

    caught = None
    try:
        mapping_service.reclassify("source-session-1", mapping.id)
    except Exception as exc:  # asserted below after checking compensated state
        caught = exc

    session = repository.find_session_by_source_id("source-session-1")
    candidates = repository.candidates_for_session("source-session-1")
    assert session is not None and session.project_id == awaiting
    assert len(candidates) == 1
    assert candidates[0].project_id == awaiting
    assert candidates[0].status is CandidateStatus.PENDING_REVIEW
    assert repository.knowledge_for_candidate(candidates[0].id) is None
    assert len(repository.review_attempts_for_candidate(candidates[0].id)) == 1
    assert isinstance(caught, ReviewUnavailableError)
    assert caught.candidate_ids == (candidates[0].id,)
    assert isinstance(caught.__cause__, RuntimeError)
    assert "must-not-leak" not in str(caught)

    mapping_service.reclassify("source-session-1", mapping.id)

    converged = repository.get_candidate(candidates[0].id)
    assert converged is not None
    assert converged.project_id == "project-1"
    assert converged.status is CandidateStatus.AUTO_ACCEPTED
    assert repository.knowledge_for_candidate(converged.id) is not None
    assert evidence


def test_pending_review_wraps_finish_failure_with_exact_candidate_ids(
    tmp_path, monkeypatch
):
    repository, evidence = _repository_with_evidence(
        tmp_path, project_id="awaiting:unknown"
    )
    pending = _candidate(project_id="awaiting:unknown")
    repository.save_candidates([pending])
    service = _service(repository, _Extractor(()), _Reviewer(_review()))
    original_finish = repository.finish_review_attempt

    def finish_then_fail(attempt_id, status, result_json="", error=""):
        original_finish(attempt_id, status, result_json, error)
        raise RuntimeError("Authorization: Bearer must-not-leak")

    monkeypatch.setattr(repository, "finish_review_attempt", finish_then_fail)

    with pytest.raises(ReviewUnavailableError) as raised:
        service.review_stored_evidence(
            "source-session-1", "awaiting:unknown", (evidence,)
        )

    assert raised.value.candidate_ids == (pending.id,)
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert "must-not-leak" not in str(raised.value)


def test_retry_session_only_calls_model_for_pending_model_dependent_candidates(
    tmp_path,
):
    repository, _ = _repository_with_evidence(tmp_path)
    low = replace(_review(), confidence=0.969)
    reviewer = _SequenceReviewer([RuntimeError("temporary"), low, _review()])
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

    assert service.retry_session("source-session-1") == [_review(), low]
    assert len(reviewer.calls) == 3
    assert len(repository.list_candidates(CandidateStatus.AUTO_ACCEPTED)) == 1
    remaining = repository.list_candidates(CandidateStatus.PENDING_REVIEW)
    assert len(remaining) == 1
    assert remaining[0].proposed_text == "Second candidate."
