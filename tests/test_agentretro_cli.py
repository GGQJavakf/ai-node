from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.knowledge import KnowledgeService
from agent_retro.application.review import ReviewService
from agent_retro.domain.models import (
    AcceptanceDecision,
    Candidate,
    CandidateStatus,
    Evidence,
    KnowledgeType,
    NormalizedSession,
    ProjectMapping,
    ReviewAttempt,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
)
from agent_retro.infrastructure.llm_review import ExtractedCandidate
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.settings import load_retro_settings
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation import cli as retro_cli


NOW = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)


def _seed_repository(state_home, *, project_id="project-1", with_candidate=True):
    repository = SQLiteRetroRepository(state_home / "retro.db", state_home / "backups")
    repository.migrate()
    evidence = Evidence(
        id="evidence-1",
        session_id="session-1",
        kind="user_instruction",
        locator=SourceLocator(
            session_id="source-session-1",
            event_id="event-1",
            source_path="sessions/source-session-1.jsonl",
            content_hash="a" * 64,
        ),
        excerpt="用户要求保留脱敏后的证据。",
    )
    repository.save_capture(
        NormalizedSession(
            id="session-1",
            source_session_id="source-session-1",
            source_path=state_home / "source-session-1.jsonl",
            source_hash="b" * 64,
            project_id=project_id,
            completed=True,
            completed_at=NOW,
            events=(),
        ),
        [evidence],
    )
    if with_candidate:
        repository.save_candidates(
            [
                Candidate(
                    id="candidate-1",
                    knowledge_type=KnowledgeType.RULE,
                    project_id=project_id,
                    scope="project",
                    proposed_text="只使用 typed repository。",
                    evidence_ids=(evidence.id,),
                    status=CandidateStatus.PENDING_REVIEW,
                    extraction_confidence=0.88,
                )
            ]
        )
        repository.save_review(
            "candidate-1",
            ReviewResult(
                verdict=ReviewVerdict.EDIT,
                confidence=0.91,
                reason="需要人工确认。",
                normalized_text="只使用 typed repository。",
                duplicate_of=None,
                conflict_with=None,
            ),
            AcceptanceDecision(
                actor="model-review",
                threshold=0.97,
                threshold_passed=False,
                blockers=(),
                verdict=ReviewVerdict.EDIT,
                evidence_ids=(evidence.id,),
            ),
        )
    return repository


def _save_candidate(repository, candidate_id, text="候选知识"):
    repository.save_candidates(
        [
            Candidate(
                id=candidate_id,
                knowledge_type=KnowledgeType.RULE,
                project_id="project-1",
                scope="project",
                proposed_text=text,
                evidence_ids=("evidence-1",),
                status=CandidateStatus.PENDING_REVIEW,
                extraction_confidence=0.88,
            )
        ]
    )


def _env(state_home):
    return {"AGENTRETRO_HOME": str(state_home)}


def _json_output(capsys):
    return json.loads(capsys.readouterr().out)


def test_review_parser_exposes_lifecycle_commands_and_retry_selector_is_exclusive():
    parser = retro_cli.build_parser()

    assert (
        parser.parse_args(["review", "run", "--session", "session-1"]).review_command
        == "run"
    )
    assert (
        parser.parse_args(
            ["review", "list", "--status", "pending_review"]
        ).candidate_status
        == "pending_review"
    )
    assert parser.parse_args(["review", "show", "candidate-1"]).candidate_id == (
        "candidate-1"
    )
    assert parser.parse_args(["review", "accept", "candidate-1"]).review_command == (
        "accept"
    )
    edited = parser.parse_args(
        [
            "review",
            "edit",
            "candidate-1",
            "--text",
            "updated",
            "--type",
            "TASK_STATE",
            "--scope",
            "global",
            "--valid-until",
            "2026-07-20T09:00:00+00:00",
        ]
    )
    assert edited.knowledge_type == "TASK_STATE"
    assert parser.parse_args(["review", "reject", "candidate-1"]).review_command == (
        "reject"
    )
    assert (
        parser.parse_args(
            ["review", "merge", "conflict-1", "--text", "merged"]
        ).conflict_id
        == "conflict-1"
    )
    assert parser.parse_args(["review", "promote", "knowledge-1"]).knowledge_id == (
        "knowledge-1"
    )
    assert parser.parse_args(["review", "archive", "knowledge-1"]).knowledge_id == (
        "knowledge-1"
    )
    assert (
        parser.parse_args(
            ["review", "retry", "--candidate", "candidate-1"]
        ).retry_candidate_id
        == "candidate-1"
    )
    assert (
        parser.parse_args(
            ["review", "retry", "--session", "session-1"]
        ).retry_session_id
        == "session-1"
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["review", "retry"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "review",
                "retry",
                "--candidate",
                "candidate-1",
                "--session",
                "session-1",
            ]
        )


def test_list_show_and_manual_accept_use_only_stored_state_without_model(
    tmp_path, capsys, monkeypatch
):
    state_home = tmp_path / "state"
    repository = _seed_repository(state_home)
    attempt = repository.begin_review_attempt(
        ReviewAttempt(
            "attempt-1",
            "candidate-1",
            "input-hash",
            "running",
            "",
            "",
        )
    )
    repository.finish_review_attempt(
        attempt.id,
        "failed",
        error="MODEL_REVIEW_RESPONSE_INVALID",
        duration_ms=57,
        error_category="MODEL_REVIEW_RESPONSE_INVALID",
    )

    def fail_model_builder(*args, **kwargs):
        pytest.fail("manual and read-only commands must not load model composition")

    monkeypatch.setattr(retro_cli, "_build_review_service", fail_model_builder)

    assert (
        retro_cli.main(
            ["--json", "review", "list", "--status", "pending_review"],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    listed = _json_output(capsys)
    assert listed["message"] == "Review candidates listed."
    assert listed["data"]["candidates"][0]["knowledge_type"] == "RULE"
    assert listed["data"]["candidates"][0]["status"] == "pending_review"

    assert (
        retro_cli.main(
            ["--json", "review", "show", "candidate-1"],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    shown = _json_output(capsys)
    assert shown["message"] == "Review candidate shown."
    assert shown["data"]["candidate"]["status"] == "pending_review"
    assert shown["data"]["review"]["verdict"] == "EDIT"
    assert shown["data"]["evidence"][0]["excerpt"] == "用户要求保留脱敏后的证据。"
    assert shown["data"]["evidence"][0]["locators"] == [
        shown["data"]["evidence"][0]["locator"]
    ]
    assert shown["data"]["attempts"] == [
        {
            "attempt_no": 1,
            "duration_ms": 57,
            "error_category": "MODEL_REVIEW_RESPONSE_INVALID",
            "id": "attempt-1",
            "input_hash": "input-hash",
            "status": "failed",
        }
    ]

    assert (
        retro_cli.main(
            ["--json", "review", "accept", "candidate-1"],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    accepted = _json_output(capsys)
    assert accepted["message"] == "Knowledge candidate accepted."
    assert accepted["data"]["accepted_by"] == "user"
    assert accepted["data"]["valid_until"] is None


class _ReviewService:
    def __init__(self):
        self.calls = []
        self.result = ReviewResult(
            verdict=ReviewVerdict.EDIT,
            confidence=0.91,
            reason="Needs user review.",
            normalized_text="Use typed repository operations.",
            duplicate_of=None,
            conflict_with=None,
        )

    def review_session(self, session_id):
        self.calls.append(("run", session_id))
        return [self.result]

    def retry_candidate(self, candidate_id):
        self.calls.append(("candidate", candidate_id))
        return self.result

    def retry_session(self, session_id):
        self.calls.append(("session", session_id))
        return [self.result]


def test_run_and_retry_load_model_composition_and_emit_serializable_results(
    tmp_path, capsys, monkeypatch
):
    state_home = tmp_path / "state"
    _seed_repository(state_home)
    service = _ReviewService()
    builds = []

    def build(settings, repository):
        builds.append((settings, repository))
        return service

    monkeypatch.setattr(retro_cli, "_build_review_service", build)

    assert (
        retro_cli.main(
            ["--json", "review", "run", "--session", "source-session-1"],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    run_result = _json_output(capsys)
    assert run_result["message"] == "Session review completed."
    assert run_result["data"]["results"][0]["verdict"] == "EDIT"

    assert (
        retro_cli.main(
            ["--json", "review", "retry", "--candidate", "candidate-1"],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    retry_result = _json_output(capsys)
    assert retry_result["message"] == "Review retry completed."
    assert retry_result["data"]["results"][0]["confidence"] == 0.91
    assert len(builds) == 2
    assert service.calls == [
        ("run", "source-session-1"),
        ("candidate", "candidate-1"),
    ]


def test_edit_reject_merge_promote_and_archive_are_no_model_lifecycle_commands(
    tmp_path, capsys, monkeypatch
):
    state_home = tmp_path / "state"
    repository = _seed_repository(state_home)
    _save_candidate(repository, "candidate-edit")
    _save_candidate(repository, "candidate-reject")
    _save_candidate(repository, "candidate-active", "保留 typed repository")
    _save_candidate(repository, "candidate-conflict", "绕过 typed repository")
    lifecycle = KnowledgeService(repository, clock=lambda: NOW)
    active = lifecycle.accept("candidate-active", actor="user")
    conflict = lifecycle.detect_conflict(
        active.id,
        "candidate-conflict",
        reason="冲突",
        merge_text="始终使用 typed repository",
    )

    def fail_model_builder(*args, **kwargs):
        pytest.fail("manual lifecycle commands must not load model composition")

    monkeypatch.setattr(retro_cli, "_build_review_service", fail_model_builder)

    assert (
        retro_cli.main(
            [
                "--json",
                "review",
                "edit",
                "candidate-edit",
                "--text",
                "当前审核被阻塞。",
                "--type",
                "TASK_STATE",
                "--scope",
                "global",
                "--valid-until",
                "2026-07-20T09:00:00+00:00",
            ],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    edited = _json_output(capsys)
    assert edited["message"] == "Knowledge candidate edited and accepted."
    assert edited["data"]["knowledge_type"] == "TASK_STATE"
    assert edited["data"]["valid_until"] == "2026-07-20T09:00:00+00:00"

    assert (
        retro_cli.main(
            ["--json", "review", "reject", "candidate-reject"],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    rejected = _json_output(capsys)
    assert rejected["message"] == "Knowledge candidate rejected."
    assert rejected["data"]["status"] == "rejected"

    assert (
        retro_cli.main(
            [
                "--json",
                "review",
                "merge",
                conflict.id,
                "--text",
                "始终使用 typed repository",
            ],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    merged = _json_output(capsys)
    assert merged["data"]["version"] == 2
    assert merged["data"]["supersedes"]

    assert (
        retro_cli.main(
            ["--json", "review", "promote", active.id],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    promoted = _json_output(capsys)
    assert promoted["data"]["scope"] == "global"

    assert (
        retro_cli.main(
            ["--json", "review", "archive", active.id],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    archived = _json_output(capsys)
    assert archived["data"]["status"] == "archived"


def test_human_review_output_is_unicode_safe_and_json_errors_keep_english_message(
    tmp_path, capsys, monkeypatch
):
    state_home = tmp_path / "state"
    _seed_repository(state_home)
    monkeypatch.setattr(
        retro_cli,
        "_build_review_service",
        lambda *args: pytest.fail("list must not load model composition"),
    )

    assert retro_cli.main(["review", "list"], home=tmp_path, env=_env(state_home)) == 0
    assert capsys.readouterr().out == "知识候选: 1 条\n"

    assert (
        retro_cli.main(
            ["--json", "review", "show", "missing"],
            home=tmp_path,
            env=_env(state_home),
        )
        == 2
    )
    error = _json_output(capsys)
    assert error["status"] == "error"
    assert error["message"] == "AgentRetro command failed."
    assert "candidate not found" in error["data"]["detail"]


def test_json_command_errors_redact_sensitive_values(tmp_path, capsys, monkeypatch):
    def fail_with_sensitive_detail(*args, **kwargs):
        raise RuntimeError("api_key=must-not-leak")

    monkeypatch.setattr(retro_cli, "_run_command", fail_with_sensitive_detail)

    assert retro_cli.main(["--json", "review", "list"], home=tmp_path, env={}) == 2
    error = _json_output(capsys)
    assert "must-not-leak" not in json.dumps(error)
    assert error["data"]["detail"] == "api_key=[REDACTED]"


def test_model_composition_uses_allowlisted_config_model_and_effective_timeout(
    tmp_path, monkeypatch
):
    state_home = tmp_path / "state"
    repository = _seed_repository(state_home)
    settings = load_retro_settings(home=tmp_path, env=_env(state_home))
    client = object()
    legacy = {"model": "test-model", "request_timeout": 37}
    loaded = []
    built = []
    monkeypatch.setattr(
        retro_cli,
        "load_legacy_model_config",
        lambda: loaded.append(True) or legacy,
        raising=False,
    )
    monkeypatch.setattr(
        retro_cli,
        "build_retro_llm_client_from_config",
        lambda config: built.append(dict(config)) or client,
        raising=False,
    )

    service = retro_cli._build_review_service(settings, repository)

    assert loaded == [True]
    assert built == [legacy]
    assert service.model_timeout_seconds == 37
    assert service.extractor.client is client
    assert service.extractor.model == "test-model"
    assert service.reviewer.client is client
    assert service.reviewer.model == "test-model"


def test_model_composition_fails_stably_before_client_build_when_model_is_missing(
    tmp_path, monkeypatch
):
    state_home = tmp_path / "state"
    repository = _seed_repository(state_home)
    settings = load_retro_settings(home=tmp_path, env=_env(state_home))
    monkeypatch.setattr(
        retro_cli,
        "load_legacy_model_config",
        lambda: {"model": "", "request_timeout": 37},
        raising=False,
    )
    monkeypatch.setattr(
        retro_cli,
        "build_retro_llm_client_from_config",
        lambda config: pytest.fail("client must not build without a model"),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="AgentRetro model is not configured"):
        retro_cli._build_review_service(settings, repository)


def test_merge_planner_composition_reuses_model_client_and_bounded_settings(
    tmp_path, monkeypatch
):
    state_home = tmp_path / "state"
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = _seed_repository(state_home)
    settings = load_retro_settings(
        home=tmp_path,
        env={
            "AGENTRETRO_HOME": str(state_home),
            "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
        },
    )
    client = object()
    legacy = {"model": "test-model", "request_timeout": 37}
    built = []
    monkeypatch.setattr(
        retro_cli,
        "load_legacy_model_config",
        lambda: legacy,
        raising=False,
    )
    monkeypatch.setattr(
        retro_cli,
        "build_retro_llm_client_from_config",
        lambda config: built.append(dict(config)) or client,
        raising=False,
    )

    planner = retro_cli._build_merge_planner(settings, repository)

    assert built == [legacy]
    assert planner.gateway.client is client
    assert planner.gateway.model == "test-model"
    assert planner.timeout_seconds == 37
    assert planner.max_files == 200
    assert planner.max_bytes == 4 * 1024 * 1024


def test_merge_planner_composition_fails_before_client_when_model_is_missing(
    tmp_path, monkeypatch
):
    state_home = tmp_path / "state"
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = _seed_repository(state_home)
    settings = load_retro_settings(
        home=tmp_path,
        env={
            "AGENTRETRO_HOME": str(state_home),
            "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
        },
    )
    monkeypatch.setattr(
        retro_cli,
        "load_legacy_model_config",
        lambda: {"model": "", "request_timeout": 37},
        raising=False,
    )
    monkeypatch.setattr(
        retro_cli,
        "build_retro_llm_client_from_config",
        lambda config: pytest.fail("client must not build without a model"),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="merge_proposal_unavailable"):
        retro_cli._build_merge_planner(settings, repository)


def test_cli_merge_plan_model_unavailable_is_stable_and_writes_no_plan(
    tmp_path, capsys, monkeypatch
):
    state_home = tmp_path / "state"
    vault = tmp_path / "vault"
    vault.mkdir()
    repository = _seed_repository(state_home)
    monkeypatch.setattr(
        retro_cli,
        "load_legacy_model_config",
        lambda: {"model": "", "request_timeout": 37},
        raising=False,
    )
    monkeypatch.setattr(
        retro_cli,
        "build_retro_llm_client_from_config",
        lambda config: pytest.fail("client must not build without a model"),
        raising=False,
    )

    result = retro_cli.main(
        [
            "--json",
            "merge",
            "plan",
            "--project",
            "project-1",
            "--instruction",
            "organize",
        ],
        home=tmp_path,
        env={
            "AGENTRETRO_HOME": str(state_home),
            "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
        },
    )

    assert result == 2
    assert _json_output(capsys) == {
        "status": "error",
        "code": "RETRO_MERGE_MODEL_UNAVAILABLE",
        "message": "Semantic merge model is unavailable.",
        "data": {"retryable": True},
    }
    with repository._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sync_jobs WHERE id LIKE 'merge-%'"
            ).fetchone()[0]
            == 0
        )


class _UnavailableReviewService:
    def retry_candidate(self, candidate_id):
        return None


def test_retry_model_failure_returns_stable_retryable_english_json(
    tmp_path, capsys, monkeypatch
):
    state_home = tmp_path / "state"
    _seed_repository(state_home)
    monkeypatch.setattr(
        retro_cli,
        "_build_review_service",
        lambda settings, repository: _UnavailableReviewService(),
    )

    assert (
        retro_cli.main(
            ["--json", "review", "retry", "--candidate", "candidate-1"],
            home=tmp_path,
            env=_env(state_home),
        )
        == 2
    )
    assert _json_output(capsys) == {
        "status": "error",
        "code": "RETRO_REVIEW_RETRYABLE",
        "message": "Model review is unavailable; retry is available.",
        "data": {"retryable": True},
    }


class _ExtractorGateway:
    def extract(self, input_json, *, timeout):
        return (
            ExtractedCandidate(
                knowledge_type="RULE",
                proposed_text="保留 typed repository 边界。",
                evidence_ids=["evidence-1"],
                confidence=0.90,
            ),
        )


class _ReviewerGateway:
    def __init__(self, *, unavailable=False):
        self.unavailable = unavailable

    def review(self, input_json, *, timeout):
        if self.unavailable:
            raise RuntimeError("injected model outage")
        return ReviewResult(
            verdict=ReviewVerdict.EDIT,
            confidence=0.91,
            reason="需要人工确认。",
            normalized_text="保留 typed repository 边界。",
            duplicate_of=None,
            conflict_with=None,
        )


def _review_service(repository, *, unavailable=False):
    return ReviewService(
        repository,
        _ExtractorGateway(),
        _ReviewerGateway(unavailable=unavailable),
        model_timeout_seconds=19,
        redact=Redactor().redact,
        clock=lambda: NOW,
    )


def _save_mapping(repository):
    mapping = ProjectMapping(
        id="mapping-1",
        git_root=ROOT,
        remote_identity="example.invalid/team/repo",
        obsidian_project="project-1",
    )
    repository.save_project_mapping(mapping, actor="user")
    return mapping


def test_project_reclassify_model_failure_keeps_session_and_candidate_awaiting(
    tmp_path, capsys, monkeypatch
):
    awaiting = "awaiting:unknown"
    state_home = tmp_path / "state"
    repository = _seed_repository(state_home, project_id=awaiting, with_candidate=False)
    mapping = _save_mapping(repository)
    monkeypatch.setattr(
        retro_cli,
        "_build_review_service",
        lambda settings, current: _review_service(current, unavailable=True),
    )

    assert (
        retro_cli.main(
            [
                "--json",
                "project",
                "reclassify",
                "--session",
                "source-session-1",
                "--mapping",
                mapping.id,
            ],
            home=tmp_path,
            env=_env(state_home),
        )
        == 2
    )
    assert _json_output(capsys)["code"] == "RETRO_REVIEW_RETRYABLE"
    readback = SQLiteRetroRepository(state_home / "retro.db", state_home / "backups")
    assert readback.find_session_by_source_id("source-session-1").project_id == awaiting
    candidate = readback.candidates_for_session("source-session-1")[0]
    assert candidate.project_id == awaiting
    assert candidate.status is CandidateStatus.PENDING_REVIEW


def test_project_reclassify_success_reviews_stored_evidence_then_updates_pending(
    tmp_path, capsys, monkeypatch
):
    awaiting = "awaiting:unknown"
    state_home = tmp_path / "state"
    repository = _seed_repository(state_home, project_id=awaiting, with_candidate=False)
    mapping = _save_mapping(repository)
    monkeypatch.setattr(
        retro_cli,
        "_build_review_service",
        lambda settings, current: _review_service(current),
    )

    assert (
        retro_cli.main(
            [
                "--json",
                "project",
                "reclassify",
                "--session",
                "source-session-1",
                "--mapping",
                mapping.id,
            ],
            home=tmp_path,
            env=_env(state_home),
        )
        == 0
    )
    assert _json_output(capsys)["message"] == "Project session reclassified."
    readback = SQLiteRetroRepository(state_home / "retro.db", state_home / "backups")
    assert readback.find_session_by_source_id("source-session-1").project_id == (
        "project-1"
    )
    candidate = readback.candidates_for_session("source-session-1")[0]
    assert candidate.project_id == "project-1"
    assert candidate.status is CandidateStatus.PENDING_REVIEW
