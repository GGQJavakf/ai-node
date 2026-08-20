from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import _path  # noqa: F401
from agent_retro.infrastructure import project_mapping as project_mapping_module
from agent_retro.application.capture import (
    CapturePlanChangedError,
    CaptureService,
    RecentCapturePlanItem,
    RecentCaptureBoundsError,
    _recent_capture_plan_id,
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
from agent_retro.infrastructure.codex_sessions import (
    CodexSessionSource,
    SessionFormatError,
)
from agent_retro.infrastructure.llm_review import StructuredModelResponseError
from agent_retro.infrastructure.project_mapping import (
    ProjectMappingService,
    ProjectReferenceResolver,
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


def _normalized_session(identity: str, workspace: Path, source_hash: str) -> NormalizedSession:
    return NormalizedSession(
        id=f"session-{identity}",
        source_session_id=identity,
        source_path=workspace / f"{identity}.jsonl",
        source_hash=source_hash,
        project_id=str(workspace),
        completed=True,
        completed_at=datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc),
        events=(),
    )


class _RecentSource:
    def __init__(self, sessions):
        self.sessions = tuple(sessions)
        self.last_discovery = SimpleNamespace(warnings=())
        self.calls = 0

    def recent_completed(self, count):
        self.calls += 1
        return self.sessions[:count]


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


def test_project_reference_resolves_canonical_remote_and_longest_workspace(tmp_path):
    workspace = (tmp_path / "workspace").resolve()
    nested = (workspace / "nested").resolve()
    target = (nested / "project").resolve()
    target.mkdir(parents=True)
    mappings = [
        ProjectMapping(
            "workspace-parent", workspace, "", "PARENT", mapping_kind="workspace"
        ),
        ProjectMapping(
            "workspace-nearest", nested, "", "NESTED", mapping_kind="workspace"
        ),
        ProjectMapping(
            "git-npki",
            tmp_path / "stored-root",
            "github.com/example/npki",
            "NPKI",
        ),
    ]
    resolver = ProjectReferenceResolver(mappings, resolve_git=lambda path_value: None)

    assert resolver.resolve("NPKI").project_id == "NPKI"
    assert resolver.resolve("https://user:secret@github.com/example/npki.git").project_id == (
        "NPKI"
    )
    path_resolution = resolver.resolve(str(target))
    assert path_resolution.project_id == "NESTED"
    assert path_resolution.mapping_id == "workspace-nearest"


def test_project_reference_uses_worktree_remote_without_exposing_credentials(tmp_path):
    worktree = (tmp_path / "worktree").resolve()
    worktree.mkdir()
    mapping = ProjectMapping(
        "git-mapping",
        (tmp_path / "stored-root").resolve(),
        "github.com/example/repository",
        "PROJECT",
    )
    resolver = ProjectReferenceResolver(
        [mapping],
        resolve_git=lambda path_value: (
            worktree,
            "https://user:synthetic-secret@github.com/example/repository.git",
        ),
    )

    result = resolver.resolve(str(worktree))

    assert result.status == "resolved"
    assert result.project_id == "PROJECT"
    assert "synthetic-secret" not in result.diagnostic


def test_project_reference_fails_closed_when_git_remote_probe_times_out(
    tmp_path, monkeypatch
):
    worktree = (tmp_path / "worktree").resolve()
    worktree.mkdir()
    calls = 0

    def probe(arguments, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(stdout=str(worktree), returncode=0)
        raise subprocess.TimeoutExpired(arguments, timeout=10)

    monkeypatch.setattr(project_mapping_module.subprocess, "run", probe)
    resolver = ProjectReferenceResolver(
        [
            ProjectMapping(
                "git-mapping",
                (tmp_path / "stored-root").resolve(),
                "example.invalid/repository",
                "PROJECT",
            )
        ]
    )

    result = resolver.resolve(str(worktree))

    assert result.status == "unknown"
    assert result.reason == "unknown_project_reference"
    assert calls == 2


def test_project_reference_fails_closed_for_unknown_equal_root_and_identity_conflict(
    tmp_path,
):
    target = (tmp_path / "workspace" / "project").resolve()
    target.mkdir(parents=True)
    shared_root = target.parent
    mappings = [
        ProjectMapping("workspace-a", shared_root, "", "A", mapping_kind="workspace"),
        ProjectMapping("workspace-b", shared_root, "", "B", mapping_kind="workspace"),
        ProjectMapping(
            "git-b", (tmp_path / "stored").resolve(), "example.invalid/repo", "B"
        ),
    ]
    ambiguous = ProjectReferenceResolver(
        mappings, resolve_git=lambda path_value: None
    ).resolve(str(target))
    conflict = ProjectReferenceResolver(
        [
            ProjectMapping(
                "workspace-a", shared_root, "", "A", mapping_kind="workspace"
            ),
            mappings[-1],
        ],
        resolve_git=lambda path_value: (target, "example.invalid/repo"),
    ).resolve(str(target))
    unknown = ProjectReferenceResolver(
        [], resolve_git=lambda path_value: None
    ).resolve("missing-project")

    assert ambiguous.status == "ambiguous"
    assert ambiguous.reason == "multiple_mapping_matches"
    assert ambiguous.mapping_ids == ("workspace-a", "workspace-b")
    assert conflict.status == "ambiguous"
    assert conflict.reason == "mapping_identity_conflict"
    assert conflict.mapping_ids == ("git-b", "workspace-a")
    assert unknown.status == "unknown"


def test_recent_capture_bounds_fail_before_discovery(tmp_path):
    repository = _repository(tmp_path)
    before_audits = repository.list_audit_entries()
    source = _RecentSource([])
    service = CaptureService(source, repository, Redactor(), ProjectResolver([]))

    with pytest.raises(RecentCaptureBoundsError):
        service.preview_recent(0, 20)
    with pytest.raises(RecentCaptureBoundsError):
        service.preview_recent(21, 20)

    assert source.calls == 0
    assert repository.list_audit_entries() == before_audits


def test_recent_capture_plan_binds_mapping_identity_before_first_write(tmp_path):
    repository = _repository(tmp_path)
    before_audits = repository.list_audit_entries()
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    source = _RecentSource([_normalized_session("source-1", workspace, "a" * 64)])
    service = CaptureService(
        source,
        repository,
        Redactor(),
        ProjectResolver(
            [
                ProjectMapping(
                    "mapping-a", workspace, "", "PROJECT", mapping_kind="workspace"
                )
            ]
        ),
    )
    plan = service.preview_recent(1, 20)
    assert plan.items[0].mapping_id == "mapping-a"
    assert plan.items[0].reuse_status == "new"
    service.project_resolver = ProjectResolver(
        [
            ProjectMapping(
                "mapping-b", workspace, "", "PROJECT", mapping_kind="workspace"
            )
        ]
    )

    with pytest.raises(CapturePlanChangedError):
        service.apply_recent(1, 20, plan.plan_id)

    assert repository.find_session_by_source_id("source-1") is None
    assert repository.list_audit_entries() == before_audits


def test_recent_capture_plan_id_binds_every_ordered_identity_field():
    first = RecentCapturePlanItem(
        session_id="source-1",
        source_hash="a" * 64,
        resolution_status="resolved",
        canonical_project_id="PROJECT",
        mapping_id="mapping-1",
        reuse_status="new",
    )
    second = replace(first, session_id="source-2", source_hash="b" * 64)
    baseline = _recent_capture_plan_id(1, 2, 20, (first, second))
    variants = [
        _recent_capture_plan_id(2, 2, 20, (first, second)),
        _recent_capture_plan_id(1, 1, 20, (first, second)),
        _recent_capture_plan_id(1, 2, 21, (first, second)),
        _recent_capture_plan_id(1, 2, 20, (second, first)),
    ]
    for field, value in (
        ("session_id", "source-changed"),
        ("source_hash", "c" * 64),
        ("resolution_status", "ambiguous"),
        ("canonical_project_id", "OTHER"),
        ("mapping_id", "mapping-2"),
        ("reuse_status", "reused"),
    ):
        variants.append(
            _recent_capture_plan_id(1, 2, 20, (replace(first, **{field: value}), second))
        )

    assert len(set(variants)) == len(variants)
    assert baseline not in variants


def test_recent_capture_partial_failure_stops_and_new_plan_reuses_commits(tmp_path):
    base_repository = _repository(tmp_path)
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    sessions = [
        _normalized_session("source-1", workspace, "a" * 64),
        _normalized_session("source-2", workspace, "b" * 64),
        _normalized_session("source-3", workspace, "c" * 64),
    ]

    class FailingRepository:
        fail = True

        def __getattr__(self, name):
            return getattr(base_repository, name)

        def save_capture(self, session, evidence):
            if self.fail and session.source_session_id == "source-2":
                raise OSError("synthetic failure")
            return base_repository.save_capture(session, evidence)

    repository = FailingRepository()
    service = CaptureService(
        _RecentSource(sessions),
        repository,
        Redactor(),
        ProjectResolver(
            [
                ProjectMapping(
                    "mapping", workspace, "", "PROJECT", mapping_kind="workspace"
                )
            ]
        ),
    )
    first_plan = service.preview_recent(3, 20)
    partial = service.apply_recent(3, 20, first_plan.plan_id)

    assert [item.session_id for item in partial.captured] == ["source-1"]
    assert [item.session_id for item in partial.failed] == ["source-2"]
    assert [(item.session_id, item.reason) for item in partial.skipped] == [
        ("source-3", "batch_stopped")
    ]
    assert base_repository.find_session_by_source_id("source-1") is not None
    assert base_repository.find_session_by_source_id("source-2") is None
    with pytest.raises(CapturePlanChangedError):
        service.apply_recent(3, 20, first_plan.plan_id)

    repository.fail = False
    retry_plan = service.preview_recent(3, 20)
    assert [item.reuse_status for item in retry_plan.items] == [
        "reused",
        "new",
        "new",
    ]
    completed = service.apply_recent(3, 20, retry_plan.plan_id)
    assert [item.session_id for item in completed.reused] == ["source-1"]
    assert [item.session_id for item in completed.captured] == [
        "source-2",
        "source-3",
    ]
    assert completed.failed == ()
    assert completed.skipped == ()


def test_recent_completed_is_newest_first_unique_and_skips_invalid_or_active(tmp_path):
    codex_home = tmp_path / "codex"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first_id = "00000000-0000-0000-0000-000000000071"
    second_id = "00000000-0000-0000-0000-000000000072"
    active_id = "00000000-0000-0000-0000-000000000073"
    session_directory = codex_home / "sessions" / "2026" / "08" / "18"
    session_directory.mkdir(parents=True)
    invalid_id = "00000000-0000-0000-0000-000000000074"
    paths = [
        session_directory / f"rollout-2026-08-18T12-00-00-{first_id}.jsonl",
        session_directory / f"rollout-2026-08-18T12-01-00-{first_id}.jsonl",
        session_directory / f"rollout-2026-08-18T12-02-00-{second_id}.jsonl",
        session_directory / f"rollout-2026-08-18T12-03-00-{active_id}.jsonl",
        session_directory / f"rollout-2026-08-18T12-04-00-{invalid_id}.jsonl",
    ]
    _write_session(paths[0], [_meta(first_id, workspace), _complete()])
    _write_session(paths[1], [_meta(first_id, workspace), _complete()])
    _write_session(paths[2], [_meta(second_id, workspace), _complete()])
    _write_session(paths[3], [_meta(active_id, workspace), _user("still active")])
    paths[4].write_text("not-json\n", encoding="utf-8")
    sessions = CodexSessionSource(codex_home).recent_completed(3)

    assert [item.source_session_id for item in sessions] == [second_id, first_id]
    assert len({item.source_session_id for item in sessions}) == 2


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
