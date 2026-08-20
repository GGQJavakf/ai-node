from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from _path import SRC
from agent_retro.application.brief import (
    BriefBudgetError,
    BriefRequest,
    BriefService,
    brief_json_data,
)
from agent_retro.application.inbox import InboxLimitError, ReviewInboxService
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
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation import cli as retro_cli


NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
_RETRO_ENTRY = (
    "import sys; from agent_retro.presentation.cli import main; "
    "raise SystemExit(main(sys.argv[1:]))"
)


def _repository(state_home: Path) -> SQLiteRetroRepository:
    repository = SQLiteRetroRepository(
        state_home / "retro.db", state_home / "backups"
    )
    repository.migrate()
    return repository


def _capture(
    repository: SQLiteRetroRepository,
    identity: str,
    project_id: str,
    *,
    source_path: str = "C:/safe/session.jsonl",
) -> str:
    internal_id = f"session-{identity}"
    locator = SourceLocator(identity, "event-1", source_path, identity * 8)
    session = NormalizedSession(
        id=internal_id,
        source_session_id=identity,
        source_path=Path(source_path),
        source_hash=(identity * 64)[:64],
        project_id=project_id,
        completed=True,
        completed_at=NOW,
        events=(),
    )
    evidence = Evidence(
        id=f"evidence-{identity}",
        session_id=internal_id,
        kind="user",
        locator=locator,
        excerpt="Authorization: Bearer synthetic-secret",
    )
    repository.save_capture(session, (evidence,))
    return evidence.id


def _candidate(
    repository: SQLiteRetroRepository,
    candidate_id: str,
    evidence_id: str,
    project_id: str = "PROJECT-A",
) -> None:
    repository.save_candidates(
        (
            Candidate(
                id=candidate_id,
                knowledge_type=KnowledgeType.LESSON,
                project_id=project_id,
                scope="project",
                proposed_text="password=synthetic-secret",
                evidence_ids=(evidence_id,),
                status=CandidateStatus.PENDING_REVIEW,
                extraction_confidence=0.5,
            ),
        )
    )


def _set_time(db_path: Path, table: str, identity: str, value: str) -> None:
    with sqlite3.connect(db_path) as connection:
        key = "source_session_id" if table == "sessions" else "id"
        column = "captured_at" if table == "sessions" else "created_at"
        connection.execute(
            f"UPDATE {table} SET {column} = ? WHERE {key} = ?", (value, identity)
        )


def _subprocess_retro(
    tmp_path: Path, state_home: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("AI_SETTINGS_FILE", None)
    environment.update(
        {
            "AGENTRETRO_HOME": str(state_home),
            "PYTHONIOENCODING": "utf-8:strict",
            "PYTHONPATH": str(SRC),
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    return subprocess.run(
        [sys.executable, "-c", _RETRO_ENTRY, *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
        timeout=20,
    )


def _seed_inbox(state_home: Path, workspace: Path) -> SQLiteRetroRepository:
    repository = _repository(state_home)
    repository.save_project_mapping(
        ProjectMapping(
            "mapping-b", workspace / "b", "", "PROJECT-B", mapping_kind="workspace"
        ),
        "tester",
    )
    repository.save_project_mapping(
        ProjectMapping(
            "mapping-a", workspace / "a", "", "PROJECT-A", mapping_kind="workspace"
        ),
        "tester",
    )
    evidence_id = _capture(
        repository,
        "a",
        "PROJECT-A",
        source_path="C:/private/synthetic-secret/session.jsonl",
    )
    _capture(repository, "u", "awaiting:unknown")
    _capture(repository, "x", "awaiting:ambiguous")
    for candidate_id in (
        "candidate-1",
        "candidate-2",
        "candidate-3",
        "candidate-4",
        "candidate-5",
    ):
        _candidate(repository, candidate_id, evidence_id)
    for candidate_id, created_at in (
        ("candidate-1", "2026-08-20T08:00:00+00:00"),
        ("candidate-2", "2026-08-20T09:00:00+00:00"),
        ("candidate-3", "2026-08-20T10:00:00+00:00"),
        ("candidate-4", "2026-08-20T11:00:00+00:00"),
        ("candidate-5", "2026-08-20T11:30:00+00:00"),
    ):
        _set_time(repository.db_path, "candidates", candidate_id, created_at)
    _set_time(
        repository.db_path, "sessions", "u", "2026-08-20T06:00:00+00:00"
    )
    _set_time(
        repository.db_path, "sessions", "x", "2026-08-20T07:00:00+00:00"
    )

    running = repository.begin_review_attempt(
        ReviewAttempt("attempt-2", "candidate-2", "b" * 64, "running", "", "")
    )
    assert running.status == "running"
    failed = repository.begin_review_attempt(
        ReviewAttempt("attempt-3", "candidate-3", "c" * 64, "running", "", "")
    )
    repository.finish_review_attempt(
        failed.id,
        "failed",
        error="Authorization: Bearer synthetic-model-error",
        error_category="transport",
    )
    completed = repository.begin_review_attempt(
        ReviewAttempt("attempt-4", "candidate-4", "d" * 64, "running", "", "")
    )
    repository.finish_review_attempt(completed.id, "completed", result_json="{}")
    repository.save_review(
        "candidate-5",
        ReviewResult(
            ReviewVerdict.EDIT,
            0.5,
            "synthetic-model-error",
            "synthetic-secret normalized text",
            None,
            None,
        ),
        AcceptanceDecision(
            actor="model-review",
            threshold=0.9,
            threshold_passed=False,
            blockers=("confidence",),
            verdict=ReviewVerdict.EDIT,
            evidence_ids=(evidence_id,),
        ),
    )
    return repository


def test_review_inbox_is_bounded_ordered_retryable_and_read_only(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "a").mkdir(parents=True)
    (workspace / "b").mkdir()
    repository = _seed_inbox(tmp_path / "state", workspace)
    service = ReviewInboxService(repository, now=lambda: NOW)
    before_audit = repository.list_audit_entries()

    cross = service.cross_project()
    project = service.project("PROJECT-A", limit=2)
    awaiting = service.awaiting(limit=1)

    assert [item.project_id for item in cross.projects] == ["PROJECT-A", "PROJECT-B"]
    assert cross.projects[0].pending_count == 5
    assert cross.projects[0].retryable_count == 2
    assert cross.projects[0].oldest_pending_age_seconds == 4 * 60 * 60
    assert cross.awaiting_unknown_count == 1
    assert cross.awaiting_ambiguous_count == 1
    assert project.total_count == 5
    assert project.returned_count == 2
    assert project.truncated is True
    assert project.retryable_count == 2
    assert [item.candidate_id for item in project.items] == [
        "candidate-1",
        "candidate-2",
    ]
    assert project.items[0].retry_command == (
        "retro review retry --candidate candidate-1"
    )
    assert project.items[1].retry_command is None
    assert awaiting.total_count == 2
    assert awaiting.returned_count == 1
    assert awaiting.truncated is True
    assert awaiting.items[0].session_id == "u"
    assert awaiting.items[0].routing_status == "unknown"
    assert awaiting.items[0].reclassify_command == (
        "retro project reclassify --session u --mapping <mapping-id>"
    )
    assert repository.list_audit_entries() == before_audit


@pytest.mark.parametrize("limit", (0, 51))
def test_review_inbox_rejects_unsafe_limits_before_repository_reads(limit):
    class UnreadableRepository:
        def list_pending_candidate_summaries(self, project_id=None):
            raise AssertionError("repository must not be read")

        def list_awaiting_session_summaries(self):
            raise AssertionError("repository must not be read")

    service = ReviewInboxService(UnreadableRepository())
    with pytest.raises(InboxLimitError):
        service.project("PROJECT-A", limit)
    with pytest.raises(InboxLimitError):
        service.awaiting(limit)


def test_cli_review_inbox_outputs_only_safe_ids_counts_and_commands(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    (workspace / "a").mkdir(parents=True)
    (workspace / "b").mkdir()
    state_home = tmp_path / "state"
    _seed_inbox(state_home, workspace)
    env = {"AGENTRETRO_HOME": str(state_home)}

    for arguments in (
        ["--json", "review", "inbox"],
        ["--json", "review", "inbox", "--project", str(workspace / "a")],
        ["--json", "review", "inbox", "--awaiting", "--limit", "1"],
    ):
        assert retro_cli.main(arguments, home=tmp_path, env=env) == 0
        payload = capsys.readouterr().out
        parsed = json.loads(payload)
        assert parsed["status"] == "ok"
        assert "synthetic-secret" not in payload
        assert "synthetic-model-error" not in payload
        assert "C:/private" not in payload
        assert "\x1b" not in payload

    assert (
        retro_cli.main(
            ["--json", "review", "inbox", "--project", "missing"],
            home=tmp_path,
            env=env,
        )
        == 2
    )
    error = json.loads(capsys.readouterr().out)
    assert error["code"] == "RETRO_UNKNOWN_PROJECT_REFERENCE"

    completed = _subprocess_retro(
        tmp_path,
        state_home,
        "--json",
        "review",
        "inbox",
        "--project",
        str(workspace / "a"),
    )
    assert completed.returncode == 0, completed.stderr
    json.loads(completed.stdout)
    assert "synthetic-secret" not in completed.stdout
    assert "synthetic-model-error" not in completed.stdout
    assert "C:/private" not in completed.stdout
    assert "\x1b" not in completed.stdout


def test_empty_brief_reports_safe_health_without_mutating_lifecycle(tmp_path, capsys):
    state_home = tmp_path / "state"
    workspace = tmp_path / "workspace"
    vault = tmp_path / "vault"
    workspace.mkdir()
    vault.mkdir()
    sentinel = vault / "user-note.md"
    sentinel.write_text("untouched", encoding="utf-8")
    repository = _repository(state_home)
    repository.save_project_mapping(
        ProjectMapping(
            "mapping-a", workspace, "", "PROJECT-A", mapping_kind="workspace"
        ),
        "tester",
    )
    evidence_id = _capture(
        repository,
        "brief",
        "PROJECT-A",
        source_path="C:/private/synthetic-secret/brief.jsonl",
    )
    _candidate(repository, "candidate-expired", evidence_id)
    expired = repository.accept_candidate(
        "candidate-expired",
        "expired task state",
        "tester",
        1.0,
        knowledge_type=KnowledgeType.TASK_STATE,
        valid_until=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    _candidate(repository, "candidate-pending", evidence_id)
    before_audit = repository.list_audit_entries()
    before_projection = repository.list_projection_events("PROJECT-A")
    before_vault = sentinel.read_bytes()

    result = BriefService(
        repository, now=lambda: NOW, recent_capture_max=3
    ).build(BriefRequest("new task", "PROJECT-A"))
    data = brief_json_data(result)

    assert result.items == ()
    assert data["eligible_knowledge_count"] == 0
    assert data["expired_task_state_count"] == 1
    assert data["pending_review_count"] == 1
    assert data["captured_session_count"] == 1
    assert data["review_inbox_command"] == (
        "retro review inbox --project PROJECT-A"
    )
    assert data["recent_capture_command"] == (
        "retro capture --recent 3 --dry-run"
    )
    current = repository.knowledge_versions(expired.id)[-1]
    assert current.status == "active"
    assert current.version == expired.version
    assert repository.list_audit_entries() == before_audit
    assert repository.list_projection_events("PROJECT-A") == before_projection
    assert sentinel.read_bytes() == before_vault
    completed = _subprocess_retro(
        tmp_path,
        state_home,
        "--json",
        "brief",
        "new task",
        "--project",
        str(workspace),
    )
    assert completed.returncode == 0, completed.stderr
    json.loads(completed.stdout)
    assert "synthetic-secret" not in completed.stdout
    assert "C:/private" not in completed.stdout
    assert "\x1b" not in completed.stdout
    serialized = json.dumps(data, ensure_ascii=False)
    assert "synthetic-secret" not in serialized
    assert "C:/private" not in serialized
    assert "\x1b" not in serialized

    with pytest.raises(BriefBudgetError) as budget_error:
        BriefService(repository, now=lambda: NOW).build(
            BriefRequest("new task", "PROJECT-A", max_tokens=80)
        )
    assert budget_error.value.required_tokens > budget_error.value.max_tokens == 80

    assert (
        retro_cli.main(
            ["--json", "brief", "new task", "--project", str(workspace)],
            home=tmp_path,
            env={
                "AGENTRETRO_HOME": str(state_home),
                "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
                "AGENTRETRO_RECENT_CAPTURE_MAX": "3",
            },
        )
        == 0
    )
    cli_text = capsys.readouterr().out
    cli_data = json.loads(cli_text)["data"]
    assert cli_data["project_id"] == "PROJECT-A"
    assert cli_data["expired_task_state_count"] == 1
    assert cli_data["pending_review_count"] == 1
    assert cli_data["recent_capture_command"] == (
        "retro capture --recent 3 --dry-run"
    )
    assert "synthetic-secret" not in cli_text
    assert "C:/private" not in cli_text
    assert "\x1b" not in cli_text
    assert repository.knowledge_versions(expired.id)[-1] == current
    assert repository.list_audit_entries() == before_audit
    assert repository.list_projection_events("PROJECT-A") == before_projection
    assert sentinel.read_bytes() == before_vault


def test_brief_health_counts_current_task_state_as_active(tmp_path):
    repository = _repository(tmp_path / "state")
    evidence_id = _capture(repository, "current", "PROJECT-A")
    _candidate(repository, "candidate-current", evidence_id)
    repository.accept_candidate(
        "candidate-current",
        "current task state",
        "tester",
        1.0,
        knowledge_type=KnowledgeType.TASK_STATE,
        valid_until=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    _candidate(repository, "candidate-boundary", evidence_id)
    repository.accept_candidate(
        "candidate-boundary",
        "boundary task state",
        "tester",
        1.0,
        knowledge_type=KnowledgeType.TASK_STATE,
        valid_until=NOW,
    )

    health = repository.brief_health_counts("PROJECT-A", NOW)

    assert health.eligible_knowledge_count == 1
    assert health.active_task_state_count == 1
    assert health.expired_task_state_count == 1
