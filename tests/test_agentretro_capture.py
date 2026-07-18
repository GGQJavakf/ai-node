from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

import _path  # noqa: F401
from agent_retro.application.capture import CaptureService, SourceIntegrityError
from agent_retro.infrastructure.codex_sessions import (
    CodexSessionSource,
    IncompleteSessionError,
    SessionDiscoveryTimeout,
    SessionFormatError,
    SessionSizeLimitError,
    effective_codex_home,
)
from agent_retro.infrastructure.project_mapping import (
    ProjectMappingConflictError,
    ProjectMappingService,
    ProjectResolver,
    UnsafeProjectPathError,
    normalize_git_remote,
)
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation.cli import build_parser, main


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "agentretro"


def _repository(tmp_path: Path) -> SQLiteRetroRepository:
    repository = SQLiteRetroRepository(tmp_path / "retro.db", tmp_path / "backups")
    repository.migrate()
    return repository


def _git_repository(path: Path, remote: str) -> Path:
    path.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "remote", "add", "origin", remote],
        check=True,
        capture_output=True,
        text=True,
    )
    return path.resolve()


def _copy_fixture(fixtures_dir: Path, target: Path, name: str) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    destination = target / f"{name}.jsonl"
    destination.write_bytes((fixtures_dir / f"{name}.jsonl").read_bytes())
    return destination


def test_completed_session_is_normalized(fixtures_dir):
    source = CodexSessionSource(fixtures_dir)

    session = source.load("session-completed")

    assert session.source_session_id == "session-completed"
    assert session.completed is True
    assert [event.kind for event in session.events] == [
        "user",
        "assistant",
        "command",
    ]
    assert len({event.id for event in session.events}) == 3
    assert all(event.locator.source_path.endswith("completed.jsonl") for event in session.events)


def test_active_session_is_rejected(fixtures_dir):
    source = CodexSessionSource(fixtures_dir)

    with pytest.raises(IncompleteSessionError):
        source.load("session-active")


def test_malformed_session_fails_closed(fixtures_dir):
    source = CodexSessionSource(fixtures_dir)

    with pytest.raises(SessionFormatError, match="session ID"):
        source.load("malformed")


def test_unknown_optional_event_is_diagnosed_and_never_normalized(fixtures_dir):
    source = CodexSessionSource(fixtures_dir)

    session = source.load("session-unknown")

    assert [event.kind for event in session.events] == ["user"]
    assert any("future_optional_event" in warning for warning in source.last_discovery.warnings)


def test_discovery_stops_at_configured_count(fixtures_dir, tmp_path):
    first = _copy_fixture(fixtures_dir, tmp_path / "sessions", "active")
    second = _copy_fixture(fixtures_dir, tmp_path / "sessions", "unknown-event")
    third = _copy_fixture(fixtures_dir, tmp_path / "sessions", "completed")
    os.utime(first, (30, 30))
    os.utime(second, (20, 20))
    os.utime(third, (10, 10))
    source = CodexSessionSource(tmp_path / "sessions", max_candidates=2)

    session = source.latest_completed()

    assert session.source_session_id == "session-unknown"
    assert source.last_discovery.inspected_count <= 2
    assert any("session-active" in item for item in source.last_discovery.diagnostics)


def test_oversized_session_is_rejected_before_parse(fixtures_dir):
    source = CodexSessionSource(fixtures_dir, max_session_bytes=8)

    with pytest.raises(SessionSizeLimitError, match="8"):
        source.load("session-completed")


def test_discovery_timeout_has_an_explicit_diagnostic(fixtures_dir, tmp_path):
    _copy_fixture(fixtures_dir, tmp_path / "sessions", "completed")
    readings = iter((0.0, 11.0))
    source = CodexSessionSource(
        tmp_path / "sessions",
        discovery_timeout_seconds=10.0,
        monotonic=lambda: next(readings),
    )

    with pytest.raises(SessionDiscoveryTimeout, match="配置时限"):
        source.latest_completed()

    assert source.last_discovery.inspected_count == 0
    assert source.last_discovery.diagnostics == ("会话发现超过配置时限",)


def test_effective_codex_home_prefers_explicit_environment(tmp_path):
    configured = tmp_path / "configured-codex"

    assert effective_codex_home(
        home=tmp_path / "user", env={"CODEX_HOME": str(configured)}
    ) == configured.resolve()
    assert effective_codex_home(home=tmp_path / "user", env={}) == (
        tmp_path / "user" / ".codex"
    ).resolve()


def test_redactor_covers_headers_fields_pem_and_connection_strings():
    redactor = Redactor()
    sensitive = "TOKEN" + "_FOR_REDACTION_TEST"
    raw = "\n".join(
        [
            f"Authorization: Bearer {sensitive}",
            f"api_key={sensitive}",
            json.dumps({"password": sensitive}),
            "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----",
            f"postgresql://user:{sensitive}@db.example.invalid/app",
        ]
    )

    redacted = redactor.redact(raw)

    assert sensitive not in redacted
    assert redacted.count("[REDACTED]") >= 5
    assert "api_key=" in redacted
    assert '"password":' in redacted
    assert redactor.redact(redacted) == redacted
    assert redactor.contains_sensitive_value(raw) is True
    assert redactor.contains_sensitive_value(redacted) is False


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://user:password@example.invalid/Owner/Repo.git", "example.invalid/Owner/Repo"),
        ("git@example.invalid:Owner/Repo.git", "example.invalid/Owner/Repo"),
        ("ssh://git@example.invalid/Owner/Repo.git", "example.invalid/Owner/Repo"),
    ],
)
def test_git_remote_normalization_removes_transport_credentials_and_dot_git(
    remote, expected
):
    assert normalize_git_remote(remote) == expected


def test_project_resolver_uses_root_then_unique_remote(tmp_path):
    repo = _repository(tmp_path)
    first_root = _git_repository(
        tmp_path / "first", "git@example.invalid:Owner/Repo.git"
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    mapping = ProjectMappingService(repo, vault_root=vault).map(
        first_root, "Projects/First"
    )
    resolver = ProjectResolver(repo.list_project_mappings())

    exact = resolver.resolve(first_root, "example.invalid/Owner/Repo")
    clone = resolver.resolve(tmp_path / "other-clone", "example.invalid/Owner/Repo")
    unknown = resolver.resolve(tmp_path / "other", "example.invalid/Other/Repo")

    assert exact.status == "resolved"
    assert exact.mapping_id == mapping.id
    assert clone.mapping_id == mapping.id
    assert unknown.status == "unknown"


def test_project_mapping_lifecycle_is_sqlite_backed_and_sanitized(tmp_path):
    repo = _repository(tmp_path)
    root = _git_repository(
        tmp_path / "project", "https://user:password@example.invalid/Owner/Repo.git"
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    service = ProjectMappingService(repo, vault_root=vault)

    mapping = service.map(root, "Projects/Example", actor="tester")

    assert service.list() == [mapping]
    assert mapping.remote_identity == "example.invalid/Owner/Repo"
    assert "password" not in repr(service.list())
    service.remove(mapping.id, actor="tester")
    assert service.list() == []
    assert repo.list_project_mappings(active_only=False)[0].active is False


def test_project_mapping_rejects_vault_escape_and_incompatible_collision(tmp_path):
    repo = _repository(tmp_path)
    root = _git_repository(tmp_path / "project", "git@example.invalid:Owner/Repo.git")
    vault = tmp_path / "vault"
    vault.mkdir()
    service = ProjectMappingService(repo, vault_root=vault)

    with pytest.raises(UnsafeProjectPathError):
        service.map(root, "../escape")

    service.map(root, "Projects/One")
    with pytest.raises(ProjectMappingConflictError):
        service.map(root, "Projects/Two")


def test_compatible_remote_mapping_is_reused_for_another_clone(tmp_path):
    repo = _repository(tmp_path)
    first = _git_repository(tmp_path / "first", "git@example.invalid:Owner/Repo.git")
    second = _git_repository(tmp_path / "second", "https://example.invalid/Owner/Repo.git")
    vault = tmp_path / "vault"
    vault.mkdir()
    service = ProjectMappingService(repo, vault_root=vault)

    existing = service.map(first, "Projects/One")

    assert service.map(second, "Projects/One") == existing
    assert service.list() == [existing]


def test_capture_is_redacted_transactional_idempotent_and_integrity_checked(
    fixtures_dir, tmp_path
):
    codex_home = tmp_path / "codex"
    completed = _copy_fixture(fixtures_dir, codex_home, "completed")
    repo = _repository(tmp_path)
    service = CaptureService(
        CodexSessionSource(codex_home), repo, Redactor(), ProjectResolver([])
    )

    first = service.capture_session("session-completed")
    second = service.capture_session("session-completed")

    assert first.captured is True and first.reused is False
    assert second.captured is False and second.reused is True
    assert first.project_status == "unknown"
    db_bytes = repo.db_path.read_bytes()
    assert ("TOKEN" + "_FOR_REDACTION_TEST").encode() not in db_bytes
    assert b"[REDACTED]" in db_bytes

    completed.write_bytes((fixtures_dir / "changed-hash.jsonl").read_bytes())

    with pytest.raises(SourceIntegrityError, match="session-completed"):
        service.capture_session("session-completed")


def test_parser_failure_creates_no_partial_capture(fixtures_dir, tmp_path):
    codex_home = tmp_path / "codex"
    _copy_fixture(fixtures_dir, codex_home, "malformed")
    repo = _repository(tmp_path)
    service = CaptureService(
        CodexSessionSource(codex_home), repo, Redactor(), ProjectResolver([])
    )

    with pytest.raises(SessionFormatError):
        service.capture_session("malformed")

    connection = sqlite3.connect(repo.db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    finally:
        connection.close()


def test_reclassify_uses_stored_redacted_evidence_without_reparsing(
    fixtures_dir, tmp_path
):
    codex_home = tmp_path / "codex"
    _copy_fixture(fixtures_dir, codex_home, "completed")
    source = CodexSessionSource(codex_home)
    repo = _repository(tmp_path)
    CaptureService(source, repo, Redactor(), ProjectResolver([])).capture_session(
        "session-completed"
    )
    root = _git_repository(tmp_path / "project", "git@example.invalid:Owner/Repo.git")
    vault = tmp_path / "vault"
    vault.mkdir()
    reviewed = []
    mapping_service = ProjectMappingService(
        repo,
        vault_root=vault,
        review_stored_evidence=lambda session_id, project_id, evidence: reviewed.append(
            (session_id, project_id, evidence)
        ),
    )
    mapping = mapping_service.map(root, "Projects/Example")
    completed_path = codex_home / "completed.jsonl"
    completed_path.unlink()

    mapping_service.reclassify("session-completed", mapping.id, actor="tester")

    assert len(reviewed) == 1
    assert reviewed[0][0:2] == ("session-completed", "Projects/Example")
    assert reviewed[0][2]
    assert all(("TOKEN" + "_FOR_REDACTION_TEST") not in item.excerpt for item in reviewed[0][2])


def test_cli_requires_exactly_one_capture_selector_and_has_project_commands():
    parser = build_parser()

    assert parser.parse_args(["capture", "--last"]).capture_last is True
    assert parser.parse_args(
        ["capture", "--session", "session-completed"]
    ).session_id == "session-completed"
    with pytest.raises(SystemExit):
        parser.parse_args(["capture"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["capture", "--last", "--session", "session-completed"]
        )
    assert parser.parse_args(
        ["project", "map", "--root", ".", "--vault-project", "Projects/Test"]
    ).project_command == "map"
    assert parser.parse_args(["project", "list"]).project_command == "list"
    assert parser.parse_args(
        ["project", "remove", "mapping-1"]
    ).project_command == "remove"
    assert parser.parse_args(
        ["project", "reclassify", "session-1", "mapping-1"]
    ).project_command == "reclassify"


def test_cli_capture_last_then_named_session_uses_only_injected_paths(
    fixtures_dir, tmp_path, capsys
):
    codex_home = tmp_path / "codex-home"
    _copy_fixture(fixtures_dir, codex_home, "completed")
    state_home = tmp_path / "state"
    env = {
        "CODEX_HOME": str(codex_home),
        "AGENTRETRO_HOME": str(state_home),
    }

    assert main(["--json", "capture", "--last"], home=tmp_path, env=env) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["data"]["captured"] is True
    assert first["data"]["session_id"] == "session-completed"

    assert main(
        ["--json", "capture", "--session", "session-completed"],
        home=tmp_path,
        env=env,
    ) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["data"]["reused"] is True
    assert (state_home / "retro.db").is_file()
