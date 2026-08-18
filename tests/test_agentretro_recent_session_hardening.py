from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

import _path  # noqa: F401
from agent_retro.application.capture import CaptureService
from agent_retro.application.review import ReviewService
from agent_retro.domain.models import (
    Candidate,
    CandidateStatus,
    Evidence,
    KnowledgeType,
    ProjectMapping,
    ReviewResult,
    ReviewVerdict,
    SourceLocator,
)
from agent_retro.infrastructure.codex_sessions import (
    CodexSessionSource,
    SessionFormatError,
)
from agent_retro.infrastructure.llm_review import StructuredModelResponseError
from agent_retro.infrastructure.project_mapping import (
    ProjectMappingService,
    ProjectResolver,
)
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


def _repository(tmp_path: Path) -> SQLiteRetroRepository:
    repository = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
    return repository


def _ignore_review(_session_id, _project_id, _evidence):
    return None


def _session_path(codex_home: Path, leaf_id: str) -> Path:
    path = (
        codex_home
        / "sessions"
        / "2026"
        / "08"
        / "18"
        / f"rollout-2026-08-18T12-00-00-{leaf_id}.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_session(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )


def _meta(
    identity: str,
    cwd: Path,
    *,
    family: str = "00000000-0000-0000-0000-000000000099",
    parent: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": identity,
        "session_id": family,
        "cwd": str(cwd),
        "thread_source": "subagent",
    }
    if parent:
        payload["forked_from_id"] = parent
        payload["parent_thread_id"] = parent
    return {"type": "session_meta", "payload": payload}


def _user(message: str) -> dict[str, object]:
    return {
        "type": "event_msg",
        "payload": {"type": "user_message", "message": message},
    }


def _complete() -> dict[str, object]:
    return {"type": "turn_complete", "payload": {"type": "turn_complete"}}


def test_non_git_workspace_mapping_routes_contained_session(tmp_path):
    repository = _repository(tmp_path)
    workspace = tmp_path / "kcsp"
    nested = workspace / "work" / "base-repo" / "front"
    nested.mkdir(parents=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    service = ProjectMappingService(
        repository, vault_root=vault, review_stored_evidence=_ignore_review
    )

    mapping = service.map_workspace(workspace, "KCSP", actor="tester")
    result = ProjectResolver(service.list()).resolve(
        nested, "", source_path=nested
    )

    assert mapping.mapping_kind == "workspace"
    assert mapping.remote_identity == ""
    assert result.status == "resolved"
    assert result.project_id == "KCSP"
    assert repository.list_audit_entries(
        action="project_mapping_saved", entity_id=mapping.id
    )
    assert service.list() == [mapping]
    service.remove(mapping.id, actor="tester")
    assert service.list() == []
    assert repository.list_audit_entries(
        action="project_mapping_deactivated", entity_id=mapping.id
    )


def test_workspace_mapping_rejects_missing_file_and_symlink_roots(tmp_path):
    repository = _repository(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    service = ProjectMappingService(
        repository, vault_root=vault, review_stored_evidence=_ignore_review
    )
    ordinary_file = tmp_path / "not-a-directory"
    ordinary_file.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError):
        service.map_workspace(tmp_path / "missing", "KCSP")
    with pytest.raises(ValueError):
        service.map_workspace(ordinary_file, "KCSP")

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "workspace-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pass
    else:
        with pytest.raises(ValueError):
            service.map_workspace(link, "KCSP")
    assert service.list() == []


def test_workspace_routing_prefers_longest_root_and_stops_on_git_disagreement(
    tmp_path,
):
    workspace = (tmp_path / "kcsp").resolve()
    nested = (workspace / "work").resolve()
    repo_root = (nested / "front").resolve()
    repo_root.mkdir(parents=True)
    compatible = ProjectResolver(
        [
            ProjectMapping(
                "workspace-parent", workspace, "", "KCSP", mapping_kind="workspace"
            ),
            ProjectMapping(
                "workspace-nested", nested, "", "KCSP", mapping_kind="workspace"
            ),
        ]
    ).resolve(repo_root, "", source_path=repo_root)
    conflicting = ProjectResolver(
        [
            ProjectMapping(
                "workspace", workspace, "", "KCSP", mapping_kind="workspace"
            ),
            ProjectMapping(
                "git", repo_root, "example.invalid/front", "OTHER"
            ),
        ]
    ).resolve(repo_root, "example.invalid/front", source_path=repo_root)

    assert compatible.status == "resolved"
    assert compatible.mapping_id == "workspace-nested"
    assert conflicting.status == "ambiguous"


def test_valid_nested_session_metadata_chain_uses_leaf_identity(tmp_path):
    child = "00000000-0000-0000-0000-000000000001"
    parent = "00000000-0000-0000-0000-000000000002"
    path = _session_path(tmp_path, child)
    _write_session(
        path,
        [
            _meta(child, tmp_path, parent=parent),
            _meta(parent, tmp_path),
            _user("verified nested session"),
            _complete(),
        ],
    )

    source = CodexSessionSource(tmp_path)
    session = source.load(child)

    assert session.source_session_id == child
    assert session.project_id == str(tmp_path)
    assert [item.kind for item in session.events] == ["user"]
    assert source.last_discovery.warnings == ()


@pytest.mark.parametrize("variant", ["unrelated", "post_event", "family_conflict"])
def test_invalid_repeated_session_metadata_remains_fail_closed(tmp_path, variant):
    child = "00000000-0000-0000-0000-000000000011"
    parent = "00000000-0000-0000-0000-000000000012"
    second = _meta(parent, tmp_path)
    first = _meta(child, tmp_path, parent=parent)
    records = [first, second, _complete()]
    if variant == "unrelated":
        first = _meta(child, tmp_path, parent="00000000-0000-0000-0000-000000000013")
        records = [first, second, _complete()]
    elif variant == "post_event":
        records = [first, _user("event before parent metadata"), second, _complete()]
    elif variant == "family_conflict":
        second = _meta(
            parent,
            tmp_path,
            family="00000000-0000-0000-0000-000000000777",
        )
        records = [first, second, _complete()]
    path = _session_path(tmp_path, child)
    _write_session(path, records)

    with pytest.raises(SessionFormatError):
        CodexSessionSource(tmp_path).load(child)


def test_optional_event_warnings_are_aggregated_by_type(tmp_path):
    leaf = "00000000-0000-0000-0000-000000000021"
    path = _session_path(tmp_path, leaf)
    optional = [
        {"type": "event_msg", "payload": {"type": "reasoning"}},
        {"type": "event_msg", "payload": {"type": "reasoning"}},
        {"type": "event_msg", "payload": {"type": "token_count"}},
    ]
    _write_session(path, [_meta(leaf, tmp_path), *optional, _user("kept"), _complete()])
    source = CodexSessionSource(tmp_path)

    session = source.load(leaf)

    assert [item.kind for item in session.events] == ["user"]
    assert len(source.last_discovery.warnings) == 1
    assert "reasoning=2" in source.last_discovery.warnings[0]
    assert "token_count=1" in source.last_discovery.warnings[0]


def test_duplicate_evidence_is_canonical_with_all_source_locators(tmp_path):
    leaf = "00000000-0000-0000-0000-000000000031"
    path = _session_path(tmp_path / "codex", leaf)
    _write_session(
        path,
        [
            _meta(leaf, tmp_path),
            _user("token=FIRST_SECRET"),
            _user("token=SECOND_SECRET"),
            _complete(),
        ],
    )
    repository = _repository(tmp_path)
    service = CaptureService(
        CodexSessionSource(tmp_path / "codex"),
        repository,
        Redactor(),
        ProjectResolver([]),
    )

    first = service.capture_session(leaf)
    second = service.capture_session(leaf)
    evidence = repository.list_evidence(first.session_id)

    assert first.captured is True
    assert second.reused is True
    assert len(evidence) == 1
    assert len(evidence[0].all_locators) == 2
    assert len({item.event_id for item in evidence[0].all_locators}) == 2
    assert evidence[0].excerpt == "token=[REDACTED]"


def test_equal_content_with_different_kinds_remains_distinct_evidence(tmp_path):
    leaf = "00000000-0000-0000-0000-000000000032"
    path = _session_path(tmp_path / "codex", leaf)
    _write_session(
        path,
        [
            _meta(leaf, tmp_path),
            _user("same evidence"),
            {
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "same evidence"},
            },
            _complete(),
        ],
    )
    repository = _repository(tmp_path)
    CaptureService(
        CodexSessionSource(tmp_path / "codex"),
        repository,
        Redactor(),
        ProjectResolver([]),
    ).capture_session(leaf)

    evidence = repository.list_evidence(leaf)
    assert [item.kind for item in evidence] == ["user", "assistant"]


class _UnusedExtractor:
    def extract(self, _payload, *, timeout):
        raise AssertionError(f"unexpected extraction with timeout {timeout}")


class _FlakyStructuredReviewer:
    def __init__(self) -> None:
        self.calls = 0

    def review(self, _payload, *, timeout):
        self.calls += 1
        if self.calls == 1:
            raise StructuredModelResponseError("synthetic invalid response")
        return ReviewResult(
            verdict=ReviewVerdict.ACCEPT,
            confidence=0.95,
            reason="grounded",
            normalized_text="The verified task is complete.",
            duplicate_of=None,
            conflict_with=None,
        )


class _NonRetryableReviewer:
    def __init__(self) -> None:
        self.calls = 0

    def review(self, _payload, *, timeout):
        self.calls += 1
        raise ValueError("synthetic configuration failure")


def _review_repository(tmp_path: Path) -> tuple[SQLiteRetroRepository, Candidate]:
    repository = _repository(tmp_path)
    locator = SourceLocator("source-session", "event-1", "synthetic.jsonl", "hash-1")
    evidence = Evidence("evidence-1", "session-1", "user", locator, "verified")
    from agent_retro.domain.models import NormalizedSession

    session = NormalizedSession(
        "session-1",
        "source-session",
        Path("synthetic.jsonl"),
        "source-hash",
        "project-1",
        True,
        datetime(2026, 8, 18, tzinfo=timezone.utc),
        (),
    )
    candidate = Candidate(
        "candidate-1",
        KnowledgeType.TASK_STATE,
        "project-1",
        "project",
        "The verified task is complete.",
        (evidence.id,),
        CandidateStatus.PENDING_REVIEW,
        0.95,
    )
    repository.save_capture(session, [evidence])
    repository.save_candidates([candidate])
    return repository, candidate


def test_structured_review_failure_gets_one_fresh_observable_retry(tmp_path):
    repository, candidate = _review_repository(tmp_path)
    reviewer = _FlakyStructuredReviewer()
    service = ReviewService(
        repository,
        _UnusedExtractor(),
        reviewer,
        model_timeout_seconds=30,
        redact=lambda value: value,
    )

    result = service.retry_candidate(candidate.id)
    attempts = repository.review_attempts_for_candidate(candidate.id)

    assert result is not None
    assert reviewer.calls == 2
    assert [item.status for item in attempts] == ["failed", "completed"]
    assert attempts[0].error_category == "MODEL_REVIEW_RESPONSE_INVALID"
    assert all(item.duration_ms >= 0 for item in attempts)
    assert repository.knowledge_for_candidate(candidate.id) is not None


def test_non_retryable_review_failure_is_not_automatically_repeated(tmp_path):
    repository, candidate = _review_repository(tmp_path)
    reviewer = _NonRetryableReviewer()
    service = ReviewService(
        repository,
        _UnusedExtractor(),
        reviewer,
        model_timeout_seconds=30,
        redact=lambda value: value,
    )

    assert service.retry_candidate(candidate.id) is None
    attempts = repository.review_attempts_for_candidate(candidate.id)

    assert reviewer.calls == 1
    assert len(attempts) == 1
    assert attempts[0].status == "failed"
    assert attempts[0].error_category == "MODEL_REVIEW_FAILED"
    assert repository.knowledge_for_candidate(candidate.id) is None


def test_schema_v3_migration_is_backup_first_and_backfills_existing_rows(tmp_path):
    repository = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate(target_version=2)
    now = "2026-08-18T00:00:00+00:00"
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "session-1",
                "source-1",
                "source.jsonl",
                "hash",
                "KCSP",
                "completed",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evidence-1",
                "session-1",
                "user",
                "source-1",
                "event-1",
                "source.jsonl",
                "content-hash",
                "verified",
            ),
        )
        connection.execute(
            "INSERT INTO project_mappings VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("mapping-1", str(tmp_path), "", "KCSP", 1, now, now),
        )
        connection.execute(
            "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "candidate-1",
                "session-1",
                "TASK_STATE",
                "KCSP",
                "project",
                "verified",
                "pending_review",
                0.9,
                "{}",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO review_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attempt-1",
                "candidate-1",
                "input-hash",
                1,
                "failed",
                "",
                "MODEL_REVIEW_FAILED",
                now,
            ),
        )

    repository.migrate()

    assert repository.schema_version() == 3
    assert len(list((tmp_path / "backups").glob("migration-2-to-3-*.db"))) == 1
    evidence = repository.list_evidence("source-1")
    assert len(evidence) == 1
    assert evidence[0].all_locators == (evidence[0].locator,)
    assert repository.list_project_mappings()[0].mapping_kind == "git"
    attempt = repository.review_attempts_for_candidate("candidate-1")[0]
    assert attempt.duration_ms == 0
    assert attempt.error_category == ""
    with repository.transaction() as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(review_attempts)")
        }
    assert {"duration_ms", "error_category"} <= columns
