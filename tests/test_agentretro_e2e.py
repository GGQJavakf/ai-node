from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.review import ReviewService
from agent_retro.domain.models import (
    CandidateStatus,
    KnowledgeType,
    ProjectMapping,
    ReviewResult,
    ReviewVerdict,
)
from agent_retro.infrastructure.llm_review import ExtractedCandidate
from agent_retro.infrastructure.obsidian import parse_aggregate_entries
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation import cli as retro_cli


SECRET = "TOKEN_FOR_REDACTION_TEST"
SESSION_ID = "task8-e2e-session"
PROJECT_ID = "Task8Project"
RULE_TEXT = "Always run the focused regression before release."
LESSON_TEXT = "Keep failure, correction, and verification evidence separate."
TASK_TEXT = "Finish the bounded Task8 verification."


@dataclass(frozen=True)
class E2EArtifacts:
    root: Path
    state: Path
    codex_home: Path
    vault: Path
    db_path: Path
    backup_root: Path
    trace_path: Path
    log_path: Path
    source_hash: str
    content_hashes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    brief_payload: dict[str, object]


class _DeterministicExtractor:
    def __init__(self, evidence_ids: tuple[str, ...], trace: list[str]) -> None:
        self.evidence_ids = evidence_ids
        self.trace = trace

    def extract(self, input_json: str, *, timeout: int):
        self.trace.append(input_json)
        rule, failure, correction, verification, _redacted_secret = self.evidence_ids
        return (
            ExtractedCandidate(
                knowledge_type="RULE",
                proposed_text=RULE_TEXT,
                evidence_ids=[rule],
                confidence=0.99,
            ),
            ExtractedCandidate(
                knowledge_type="LESSON",
                proposed_text=LESSON_TEXT,
                evidence_ids=[failure, correction, verification],
                confidence=0.99,
            ),
            ExtractedCandidate(
                knowledge_type="TASK_STATE",
                proposed_text=TASK_TEXT,
                evidence_ids=[rule],
                confidence=0.99,
            ),
        )


class _DeterministicReviewer:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    def review(self, input_json: str, *, timeout: int) -> ReviewResult:
        self.trace.append(input_json)
        candidate = json.loads(input_json)["candidate"]
        return ReviewResult(
            verdict=ReviewVerdict.ACCEPT,
            confidence=0.99,
            reason="Grounded in the selected evidence.",
            normalized_text=candidate["proposed_text"],
            duplicate_of=None,
            conflict_with=None,
        )


def _event(kind: str, index: int, text: str) -> dict[str, object]:
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
    raise ValueError(kind)


def _write_completed_session(codex_home: Path, project_root: Path) -> Path:
    path = (
        codex_home
        / "sessions"
        / "2026"
        / "07"
        / "18"
        / "rollout-2026-07-18T08-00-00-88888888-8888-8888-8888-888888888888.jsonl"
    )
    path.parent.mkdir(parents=True)
    records: list[dict[str, object]] = [
        {
            "version": 1,
            "type": "session_meta",
            "timestamp": "2026-07-18T08:00:00Z",
            "payload": {"id": SESSION_ID, "cwd": str(project_root)},
        },
        _event("user", 1, "Requirement: always run the focused regression."),
        _event("user", 2, "Failure: the regression failed with an assertion error."),
        _event("assistant", 3, "Correction: fixed the typed boundary."),
        _event("command", 4, "Verification: focused tests passed with exit code 0."),
        _event("assistant", 5, f"token={SECRET}"),
        {
            "version": 1,
            "type": "event_msg",
            "timestamp": "2026-07-18T08:00:09Z",
            "payload": {"type": "task_complete", "id": "complete-1"},
        },
    ]
    path.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )
    return path


def run_e2e_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> E2EArtifacts:
    root = tmp_path.resolve()
    state = root / "state"
    codex_home = root / "codex-home"
    vault = root / "vault"
    project_root = root / "project"
    backup_root = state / "backups"
    db_path = state / "retro.db"
    trace_path = state / "traces" / "model-review.json"
    log_path = state / "logs" / "task8-e2e.log"
    vault.mkdir()
    project_root.mkdir()
    source = _write_completed_session(codex_home, project_root)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    environment = {
        "AGENTRETRO_HOME": str(state),
        "AGENTRETRO_DB_PATH": str(db_path),
        "AGENTRETRO_BACKUP_DIR": str(backup_root),
        "AGENTRETRO_OBSIDIAN_ROOT": str(vault),
        "CODEX_HOME": str(codex_home),
    }

    repository = SQLiteRetroRepository(db_path, backup_root)
    repository.migrate()
    repository.save_project_mapping(
        ProjectMapping(
            id="task8-mapping",
            git_root=project_root,
            remote_identity="",
            obsidian_project=PROJECT_ID,
        ),
        "test",
    )
    monkeypatch.setattr(
        "agent_retro.application.capture.resolve_git_identity",
        lambda path: (Path(path).resolve(), ""),
    )

    assert (
        retro_cli.main(
            ["--json", "capture", "--session", SESSION_ID],
            home=root / "home",
            env=environment,
        )
        == 0
    )
    capture_output = capsys.readouterr().out
    captured = repository.find_session_by_source_id(SESSION_ID)
    assert captured is not None and captured.project_id == PROJECT_ID
    evidence = repository.list_evidence(captured.id)
    evidence_ids = tuple(item.id for item in evidence)
    assert len(evidence_ids) == 5
    managed_root = vault / "项目" / PROJECT_ID / "AgentRetro"
    managed_root.mkdir(parents=True)
    baselines: dict[str, bytes] = {}
    baseline_hashes: dict[str, str] = {}
    for name in ("规则.md", "经验.md", "任务状态.md"):
        target = managed_root / name
        target.write_text("# safe pre-sync baseline\n", encoding="utf-8")
        baselines[name] = target.read_bytes()
        baseline_hashes[name] = hashlib.sha256(baselines[name]).hexdigest()

    trace: list[str] = []

    def build_deterministic_review(settings, current_repository):
        return ReviewService(
            current_repository,
            _DeterministicExtractor(evidence_ids, trace),
            _DeterministicReviewer(trace),
            model_timeout_seconds=9,
            redact=Redactor().redact,
        )

    monkeypatch.setattr(retro_cli, "_build_review_service", build_deterministic_review)
    assert (
        retro_cli.main(
            ["--json", "review", "run", "--session", SESSION_ID],
            home=root / "home",
            env=environment,
        )
        == 0
    )
    review_output = capsys.readouterr().out
    review_payload = json.loads(review_output)
    projections = review_payload["data"]["projections"]
    assert len(projections) == 1
    projection = projections[0]
    assert projection["status"] == "synced"
    assert projection["warning"] == ""
    assert projection["reason"] == ""

    accepted = repository.list_candidates(CandidateStatus.AUTO_ACCEPTED)
    assert len(accepted) == 3
    knowledge = {
        item.knowledge_type: repository.knowledge_for_candidate(item.id)
        for item in accepted
    }
    expected = {
        "规则.md": (KnowledgeType.RULE, RULE_TEXT, (evidence_ids[0],)),
        "经验.md": (
            KnowledgeType.LESSON,
            LESSON_TEXT,
            evidence_ids[1:4],
        ),
        "任务状态.md": (KnowledgeType.TASK_STATE, TASK_TEXT, (evidence_ids[0],)),
    }
    for name, (kind, text, expected_evidence) in expected.items():
        target = managed_root / name
        after = target.read_bytes()
        item = knowledge[kind]
        assert item is not None
        assert after != baselines[name]
        assert hashlib.sha256(after).hexdigest() != baseline_hashes[name]
        assert parse_aggregate_entries(after) == {item.id: text}
        decoded = after.decode("utf-8")
        assert decoded.count(f"### {item.id}") == 1
        assert decoded.count(f"- ID: {item.id}") == 1
        assert tuple(sorted(item.evidence_ids)) == tuple(sorted(expected_evidence))
        for evidence_id in expected_evidence:
            assert evidence_id in decoded

    canonical_targets = {managed_root / name for name in expected}
    aggregate_states = {
        state.path: state
        for state in repository.list_managed_file_states(PROJECT_ID)
        if state.path in canonical_targets
    }
    assert len(aggregate_states) == 3
    assert set(aggregate_states) == canonical_targets
    for target, state in aggregate_states.items():
        after = target.read_bytes()
        after_hash = hashlib.sha256(after).hexdigest()
        snapshot = repository.get_managed_file_snapshot(target)
        assert snapshot is not None
        assert state.project_id == PROJECT_ID
        assert state.managed_hash == after_hash
        assert state.full_hash == after_hash
        assert snapshot.snapshot_kind == "full"
        assert snapshot.owned_bytes == after
        assert snapshot.managed_hash == state.managed_hash
        assert snapshot.full_hash == state.full_hash
        assert snapshot.event_id == projection["event_id"]

    assert (
        retro_cli.main(
            [
                "--json",
                "brief",
                "focused Task8 regression",
                "--project",
                PROJECT_ID,
            ],
            home=root / "home",
            env=environment,
        )
        == 0
    )
    brief_output = capsys.readouterr().out
    brief_payload = json.loads(brief_output)

    trace_path.parent.mkdir(parents=True)
    trace_path.write_text(
        json.dumps(trace, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    log_path.parent.mkdir(parents=True)
    log_path.write_text(capture_output + review_output + brief_output, encoding="utf-8")
    source.unlink()

    return E2EArtifacts(
        root=root,
        state=state,
        codex_home=codex_home,
        vault=vault,
        db_path=db_path,
        backup_root=backup_root,
        trace_path=trace_path,
        log_path=log_path,
        source_hash=source_hash,
        content_hashes=tuple(item.locator.content_hash for item in evidence),
        evidence_ids=evidence_ids,
        brief_payload=brief_payload,
    )


def test_tmp_only_capture_review_accept_sync_and_brief_product_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts = run_e2e_flow(tmp_path, monkeypatch, capsys)
    items = artifacts.brief_payload["data"]["items"]
    by_text = {item["text"]: item for item in items}

    assert {RULE_TEXT, LESSON_TEXT, TASK_TEXT} <= set(by_text)
    assert by_text[RULE_TEXT]["evidence_refs"] == [artifacts.evidence_ids[0]]
    assert artifacts.source_hash.encode("ascii") in artifacts.db_path.read_bytes()
    assert b"[REDACTED]" in artifacts.db_path.read_bytes()
    assert all(
        path.resolve().is_relative_to(artifacts.root)
        for path in artifacts.vault.rglob("*")
    )
    assert not {
        "todos.db",
        "todos.json",
        "workflow.db",
        "workflow.json",
    }.intersection(path.name for path in artifacts.root.rglob("*"))


def sqlite_absolute_paths(db_path: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    with sqlite3.connect(db_path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ]
        for table in tables:
            columns = [
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table}")')
                if str(row[2]).upper() in {"TEXT", ""}
            ]
            if not columns:
                continue
            quoted = ", ".join(f'"{column}"' for column in columns)
            for row in connection.execute(f'SELECT {quoted} FROM "{table}"'):
                for value in row:
                    paths.extend(_absolute_paths_in(value))
    return tuple(paths)


def _absolute_paths_in(value: object) -> tuple[Path, ...]:
    if not isinstance(value, str) or not value:
        return ()
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        decoded = value
    strings = _nested_strings(decoded)
    return tuple(path for text in strings if (path := Path(text)).is_absolute())


def _nested_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(text for item in value.values() for text in _nested_strings(item))
    if isinstance(value, list):
        return tuple(text for item in value for text in _nested_strings(item))
    return ()
