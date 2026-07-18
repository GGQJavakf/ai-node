from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.knowledge import (
    CandidateLifecycleError,
    KnowledgeService,
)
from agent_retro.application.review import ReviewService
from agent_retro.domain.models import (
    Candidate,
    CandidateStatus,
    Evidence,
    KnowledgeType,
    NormalizedSession,
    ProjectMapping,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
)
from agent_retro.infrastructure.llm_review import ExtractedCandidate
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


NOW = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)


def _evidence() -> Evidence:
    return Evidence(
        id="evidence-1",
        session_id="session-1",
        kind="user_instruction",
        locator=SourceLocator(
            session_id="source-session-1",
            event_id="event-1",
            source_path="sessions/source-session-1.jsonl",
            content_hash="a" * 64,
        ),
        excerpt="The user explicitly required typed lifecycle operations.",
    )


def _candidate(
    candidate_id: str = "candidate-1",
    *,
    text: str = "Use typed lifecycle operations.",
    project_id: str = "project-1",
) -> Candidate:
    return Candidate(
        id=candidate_id,
        knowledge_type=KnowledgeType.RULE,
        project_id=project_id,
        scope="project",
        proposed_text=text,
        evidence_ids=("evidence-1",),
        status=CandidateStatus.PENDING_REVIEW,
        extraction_confidence=0.88,
    )


def _repository(tmp_path, candidates=(), *, project_id="project-1"):
    repository = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
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
        [_evidence()],
    )
    if candidates:
        repository.save_candidates(candidates)
    return repository


def _knowledge_service(repository):
    return KnowledgeService(repository, clock=lambda: NOW)


def test_manual_accept_is_pending_only_and_preserves_evidence_with_user_audit(
    tmp_path,
):
    repository = _repository(tmp_path, [_candidate()])
    service = _knowledge_service(repository)

    knowledge = service.accept("candidate-1", actor="user")

    assert knowledge.evidence_ids == ("evidence-1",)
    assert knowledge.accepted_by == "user"
    assert repository.get_candidate("candidate-1").status == CandidateStatus.ACCEPTED
    audit = repository.list_audit_entries(
        action="candidate_accepted", entity_id=knowledge.id
    )
    assert len(audit) == 1
    assert audit[0].actor == "user"
    assert audit[0].before_hash and audit[0].after_hash
    with pytest.raises(CandidateLifecycleError, match="pending"):
        service.accept("candidate-1", actor="user")


def test_manual_edit_can_change_text_type_scope_and_validity_before_acceptance(
    tmp_path,
):
    repository = _repository(tmp_path, [_candidate()])
    service = _knowledge_service(repository)
    valid_until = NOW + timedelta(days=3)

    knowledge = service.edit(
        "candidate-1",
        text="Current implementation is blocked on review.",
        knowledge_type=KnowledgeType.TASK_STATE,
        scope="global",
        valid_until=valid_until,
        actor="user",
    )

    assert knowledge.text == "Current implementation is blocked on review."
    assert knowledge.knowledge_type is KnowledgeType.TASK_STATE
    assert knowledge.scope == "global"
    assert knowledge.valid_until == valid_until
    assert knowledge.evidence_ids == ("evidence-1",)
    edited = repository.get_candidate("candidate-1")
    assert edited is not None
    assert edited.status == CandidateStatus.EDITED
    assert edited.proposed_text == knowledge.text
    assert edited.knowledge_type is KnowledgeType.TASK_STATE
    audit = repository.list_audit_entries(
        action="candidate_edited", entity_id=knowledge.id
    )
    assert len(audit) == 1
    assert audit[0].before_hash and audit[0].after_hash


@pytest.mark.parametrize("text", ["", "   "])
def test_manual_edit_rejects_empty_text_and_keeps_candidate_pending(tmp_path, text):
    repository = _repository(tmp_path, [_candidate()])

    with pytest.raises(CandidateLifecycleError, match="non-empty"):
        _knowledge_service(repository).edit("candidate-1", text=text, actor="user")

    assert (
        repository.get_candidate("candidate-1").status is CandidateStatus.PENDING_REVIEW
    )


def test_manual_edit_valid_until_is_timezone_aware_and_task_state_only(tmp_path):
    repository = _repository(tmp_path, [_candidate()])
    service = _knowledge_service(repository)

    with pytest.raises(CandidateLifecycleError, match="TASK_STATE"):
        service.edit(
            "candidate-1",
            text="Rule text.",
            valid_until=NOW + timedelta(days=1),
            actor="user",
        )
    with pytest.raises(CandidateLifecycleError, match="timezone-aware"):
        service.edit(
            "candidate-1",
            text="Task state text.",
            knowledge_type=KnowledgeType.TASK_STATE,
            valid_until=datetime(2026, 7, 19, 9, 0),
            actor="user",
        )

    assert (
        repository.get_candidate("candidate-1").status is CandidateStatus.PENDING_REVIEW
    )


def test_manual_reject_stays_out_of_active_knowledge_and_retains_audit(tmp_path):
    repository = _repository(tmp_path, [_candidate()])
    service = _knowledge_service(repository)

    rejected = service.reject("candidate-1", actor="user")

    assert rejected.status is CandidateStatus.REJECTED
    assert repository.knowledge_for_candidate("candidate-1") is None
    assert repository.list_active_knowledge("project-1", NOW) == []
    audit = repository.list_audit_entries(
        action="candidate_rejected", entity_id="candidate-1"
    )
    assert len(audit) == 1
    assert audit[0].actor == "user"
    assert audit[0].before_hash and audit[0].after_hash
    with pytest.raises(CandidateLifecycleError, match="pending"):
        service.edit("candidate-1", text="revive", actor="user")


class _Extractor:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, input_json: str, *, timeout: int):
        self.calls += 1
        return (
            ExtractedCandidate(
                knowledge_type="RULE",
                proposed_text="Use typed lifecycle operations.",
                evidence_ids=["evidence-1"],
                confidence=0.99,
            ),
        )


class _Reviewer:
    def __init__(self) -> None:
        self.calls = 0
        self.result = ReviewResult(
            verdict=ReviewVerdict.ACCEPT,
            confidence=0.99,
            reason="Explicit evidence.",
            normalized_text="Use typed lifecycle operations.",
            duplicate_of=None,
            conflict_with=None,
        )

    def review(self, input_json: str, *, timeout: int):
        self.calls += 1
        return self.result


def test_repeated_successful_review_session_returns_terminal_result_idempotently(
    tmp_path,
):
    repository = _repository(tmp_path)
    extractor = _Extractor()
    reviewer = _Reviewer()
    service = ReviewService(
        repository,
        extractor,
        reviewer,
        model_timeout_seconds=30,
        redact=Redactor().redact,
        clock=lambda: NOW,
    )

    first = service.review_session("source-session-1")
    second = service.review_session("source-session-1")

    assert first == second == [reviewer.result]
    assert extractor.calls == 1
    assert reviewer.calls == 1
    assert len(repository.candidates_for_session("source-session-1")) == 1
    assert (
        len(
            repository.knowledge_versions_for_candidate(
                repository.candidates_for_session("source-session-1")[0].id
            )
        )
        == 1
    )


def test_conflict_keeps_old_active_until_user_resolution_creates_version(
    tmp_path,
):
    repository = _repository(tmp_path, [_candidate()])
    service = _knowledge_service(repository)
    active = service.accept("candidate-1", actor="user")
    repository.save_candidates(
        [_candidate("candidate-2", text="Use untyped lifecycle operations.")]
    )

    conflict = service.detect_conflict(
        active.id,
        "candidate-2",
        reason="The candidate reverses the active rule.",
        merge_text="Use typed lifecycle operations for persistence boundaries.",
    )

    assert conflict.status == "open"
    assert repository.get_conflict(conflict.id) == conflict
    assert (
        repository.get_candidate("candidate-2").status is CandidateStatus.PENDING_REVIEW
    )
    assert repository.list_active_knowledge("project-1", NOW) == [active]

    merged = service.resolve_conflict(
        conflict.id,
        text="Use typed lifecycle operations for persistence boundaries.",
        actor="user",
    )

    assert merged.id == active.id
    assert merged.version == 2
    assert merged.supersedes == (
        f"{active.id}:v1",
        "candidate:candidate-2",
    )
    assert repository.get_conflict(conflict.id).status == "resolved"
    assert repository.get_candidate("candidate-2").status is CandidateStatus.ACCEPTED
    history = service.history(active.id)
    assert [item.status for item in history.versions] == ["superseded", "active"]
    assert history.versions[0].text == active.text
    assert history.versions[0].evidence_ids == ("evidence-1",)
    assert "conflict_resolved" in {item.action for item in history.audit_entries}


def test_global_promotion_and_archive_create_versions_and_preserve_history(
    tmp_path,
):
    repository = _repository(tmp_path, [_candidate()])
    service = _knowledge_service(repository)
    accepted = service.accept("candidate-1", actor="user")

    with pytest.raises(CandidateLifecycleError, match="user"):
        service.promote_global(accepted.id, actor="system")
    promoted = service.promote_global(accepted.id, actor="user")
    archived = service.archive(accepted.id, actor="user")

    assert promoted.version == 2
    assert promoted.scope == "global"
    assert promoted.accepted_by == "user"
    assert archived.version == 3
    assert archived.status == "archived"
    assert archived.text == accepted.text
    assert archived.evidence_ids == accepted.evidence_ids
    assert repository.list_active_knowledge("project-1", NOW) == []
    history = service.history(accepted.id)
    assert [item.status for item in history.versions] == [
        "superseded",
        "superseded",
        "archived",
    ]
    assert {item.action for item in history.audit_entries} >= {
        "candidate_accepted",
        "knowledge_promoted_global",
        "knowledge_archived",
    }


def test_expired_task_state_becomes_stale_without_deletion(tmp_path):
    repository = _repository(tmp_path, [_candidate()])
    service = _knowledge_service(repository)
    valid_until = NOW + timedelta(hours=1)
    task_state = service.edit(
        "candidate-1",
        text="Review is in progress.",
        knowledge_type=KnowledgeType.TASK_STATE,
        valid_until=valid_until,
        actor="user",
    )

    expired = service.expire_task_states(valid_until)

    assert len(expired) == 1
    assert expired[0].id == task_state.id
    assert expired[0].version == 2
    assert expired[0].status == "stale"
    assert expired[0].evidence_ids == task_state.evidence_ids
    assert repository.list_active_knowledge("project-1", valid_until) == []
    assert [item.status for item in service.history(task_state.id).versions] == [
        "superseded",
        "stale",
    ]


def test_reclassify_updates_only_pending_candidates_in_same_audited_transaction(
    tmp_path,
):
    awaiting = "awaiting:ambiguous"
    repository = _repository(
        tmp_path,
        [
            _candidate("candidate-pending", project_id=awaiting),
            _candidate("candidate-rejected", project_id=awaiting),
        ],
        project_id=awaiting,
    )
    _knowledge_service(repository).reject("candidate-rejected", actor="user")
    mapping = ProjectMapping(
        id="mapping-1",
        git_root=Path("D:/projects/example"),
        remote_identity="https://example.invalid/team/repo.git",
        obsidian_project="project-1",
    )
    repository.save_project_mapping(mapping, actor="user")

    repository.reclassify_session(
        "source-session-1", "project-1", mapping.id, actor="user"
    )

    assert (
        repository.find_session_by_source_id("source-session-1").project_id
        == "project-1"
    )
    assert repository.get_candidate("candidate-pending").project_id == "project-1"
    assert (
        repository.get_candidate("candidate-pending").status
        is CandidateStatus.PENDING_REVIEW
    )
    assert repository.get_candidate("candidate-rejected").project_id == awaiting
    audit = repository.list_audit_entries(
        action="session_reclassified", entity_id="session-1"
    )[-1]
    assert audit.before_hash and audit.after_hash
    assert json.loads(audit.detail_json)["pending_candidate_count"] == 1


def test_reclassify_rolls_back_session_and_pending_candidates_on_audit_failure(
    tmp_path, monkeypatch
):
    awaiting = "awaiting:ambiguous"
    repository = _repository(
        tmp_path,
        [_candidate("candidate-pending", project_id=awaiting)],
        project_id=awaiting,
    )
    mapping = ProjectMapping(
        id="mapping-1",
        git_root=Path("D:/projects/example"),
        remote_identity="https://example.invalid/team/repo.git",
        obsidian_project="project-1",
    )
    repository.save_project_mapping(mapping, actor="user")
    original_append = repository._append_audit_record

    def fail_reclassify_audit(connection, entry):
        if entry.action == "session_reclassified":
            raise RuntimeError("injected audit failure")
        return original_append(connection, entry)

    monkeypatch.setattr(repository, "_append_audit_record", fail_reclassify_audit)

    with pytest.raises(RuntimeError, match="injected audit failure"):
        repository.reclassify_session(
            "source-session-1", "project-1", mapping.id, actor="user"
        )

    assert (
        repository.find_session_by_source_id("source-session-1").project_id == awaiting
    )
    assert repository.get_candidate("candidate-pending").project_id == awaiting
