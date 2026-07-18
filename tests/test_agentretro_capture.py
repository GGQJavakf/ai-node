from __future__ import annotations

import json
import inspect
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

import _path  # noqa: F401
from agent_retro.application.capture import CaptureService, SourceIntegrityError
from agent_retro.application.ports import RetroRepository
from agent_retro.infrastructure.codex_sessions import (
    CodexSessionSource,
    IncompleteSessionError,
    SessionDiscoveryTimeout,
    SessionFormatError,
    SessionNotFoundError,
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


def _ignore_review(session_id, project_id, evidence):
    return None


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


@pytest.mark.parametrize("session_id", ["session-resumed", "session-aborted"])
def test_nonterminal_real_lifecycle_is_rejected(fixtures_dir, session_id):
    source = CodexSessionSource(fixtures_dir)

    with pytest.raises(IncompleteSessionError, match=session_id):
        source.load(session_id)


def test_versionless_real_lifecycle_record_is_supported(fixtures_dir):
    first_record = json.loads(
        (fixtures_dir / "unknown-event.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert "version" not in first_record

    session = CodexSessionSource(fixtures_dir).load("session-unknown")

    assert session.completed is True


def test_session_without_a_terminal_complete_is_incomplete(tmp_path):
    session_path = tmp_path / "no-terminal.jsonl"
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "session-no-terminal",
                            "cwd": "C:/synthetic/project",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "synthetic evidence",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(IncompleteSessionError, match="session-no-terminal"):
        CodexSessionSource(tmp_path).load("session-no-terminal")


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
    sessions = tmp_path / "sessions"
    first_directory = sessions / "2026" / "07" / "20"
    second_directory = sessions / "2026" / "07" / "19"
    third_directory = sessions / "2026" / "07" / "18"
    first = _copy_fixture(fixtures_dir, first_directory, "active")
    second = _copy_fixture(fixtures_dir, second_directory, "unknown-event")
    third = _copy_fixture(fixtures_dir, third_directory, "completed")
    os.utime(first, (30, 30))
    os.utime(second, (20, 20))
    os.utime(third, (10, 10))
    os.utime(first_directory, (30, 30))
    os.utime(second_directory, (20, 20))
    os.utime(third_directory, (10, 10))
    source = CodexSessionSource(sessions, max_candidates=2)

    session = source.latest_completed()

    assert session.source_session_id == "session-unknown"
    assert source.last_discovery.inspected_count <= 2
    assert any("session-active" in item for item in source.last_discovery.diagnostics)
    assert any("候选数量上限" in item for item in source.last_discovery.diagnostics)


def test_candidate_budget_stops_discovery_and_stat_work_in_a_large_tree(
    fixtures_dir, tmp_path, monkeypatch
):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    template = (fixtures_dir / "active.jsonl").read_text(encoding="utf-8")
    for index in range(20):
        (sessions / f"candidate-{index:02d}.jsonl").write_text(
            template.replace("session-active", f"session-{index:02d}"),
            encoding="utf-8",
        )
    real_scandir = os.scandir
    real_stat = Path.stat
    jsonl_scans = 0
    jsonl_stats = 0

    def bounded_stat(path, *args, **kwargs):
        nonlocal jsonl_stats
        if path.suffix == ".jsonl":
            jsonl_stats += 1
            if jsonl_stats > 2:
                raise AssertionError("candidate count did not stop stat work")
        return real_stat(path, *args, **kwargs)

    class BoundedScan:
        def __init__(self, path):
            self.inner = real_scandir(path)

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal jsonl_scans
            item = next(self.inner)
            if item.name.lower().endswith(".jsonl"):
                jsonl_scans += 1
                if jsonl_scans > 2:
                    raise AssertionError(
                        "candidate count did not stop JSONL discovery"
                    )
            return item

    monkeypatch.setattr(os, "scandir", BoundedScan)
    monkeypatch.setattr(Path, "stat", bounded_stat)

    source = CodexSessionSource(sessions, max_candidates=2)
    with pytest.raises(SessionNotFoundError):
        source.latest_completed()

    assert jsonl_scans == 2
    assert jsonl_stats == 2
    assert source.last_discovery.inspected_count == 2
    assert any(
        "候选数量上限" in item
        for item in source.last_discovery.diagnostics
    )


def test_deadline_interrupts_directory_enumeration(
    fixtures_dir, tmp_path, monkeypatch
):
    sessions = tmp_path / "sessions"
    _copy_fixture(fixtures_dir, sessions, "active")
    _copy_fixture(fixtures_dir, sessions, "completed")
    real_scandir = os.scandir

    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

    clock = Clock()

    class DeadlineScan:
        def __init__(self, path):
            self.inner = real_scandir(path)
            self.count = 0

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def __iter__(self):
            return self

        def __next__(self):
            self.count += 1
            if self.count > 1:
                raise AssertionError("enumeration continued after the deadline")
            item = next(self.inner)
            clock.now = 11.0
            return item

    monkeypatch.setattr(os, "scandir", DeadlineScan)
    source = CodexSessionSource(
        sessions, discovery_timeout_seconds=10.0, monotonic=clock
    )

    with pytest.raises(SessionDiscoveryTimeout):
        source.latest_completed()


def test_deadline_is_checked_after_the_last_non_session_entry(
    tmp_path, monkeypatch
):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "not-a-session.txt").write_text("synthetic", encoding="utf-8")
    real_scandir = os.scandir

    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

    clock = Clock()

    class LastEntryScan:
        def __init__(self, path):
            self.inner = real_scandir(path)

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def __iter__(self):
            return self

        def __next__(self):
            item = next(self.inner)
            clock.now = 11.0
            return item

    monkeypatch.setattr(os, "scandir", LastEntryScan)
    source = CodexSessionSource(
        sessions, discovery_timeout_seconds=10.0, monotonic=clock
    )

    with pytest.raises(SessionDiscoveryTimeout):
        source.latest_completed()


def test_explicit_load_uses_the_same_candidate_budget(fixtures_dir, tmp_path):
    sessions = tmp_path / "sessions"
    unrelated = _copy_fixture(fixtures_dir, sessions, "active")
    target = _copy_fixture(fixtures_dir, sessions, "completed")
    os.utime(unrelated, (20, 20))
    os.utime(target, (10, 10))
    source = CodexSessionSource(sessions, max_candidates=1)

    with pytest.raises(SessionNotFoundError, match="session-completed"):
        source.load("session-completed")

    assert source.last_discovery.inspected_count == 1


def test_oversized_explicit_session_is_never_opened(
    fixtures_dir, monkeypatch
):
    source = CodexSessionSource(fixtures_dir, max_session_bytes=8)
    opens = 0

    def forbidden_open(*args, **kwargs):
        nonlocal opens
        opens += 1
        raise AssertionError("oversized session was opened")

    monkeypatch.setattr(Path, "open", forbidden_open)

    with pytest.raises(SessionSizeLimitError, match="8"):
        source.load("session-completed")

    assert opens == 0


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
    mapping = ProjectMappingService(
        repo, vault_root=vault, review_stored_evidence=_ignore_review
    ).map(
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
    service = ProjectMappingService(
        repo, vault_root=vault, review_stored_evidence=_ignore_review
    )

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
    service = ProjectMappingService(
        repo, vault_root=vault, review_stored_evidence=_ignore_review
    )

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
    service = ProjectMappingService(
        repo, vault_root=vault, review_stored_evidence=_ignore_review
    )

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


def test_source_identity_lookup_is_a_mandatory_capture_port():
    assert callable(
        getattr(RetroRepository, "find_session_by_source_id", None)
    )
    assert "getattr" not in inspect.getsource(CaptureService._capture)


def test_reclassify_is_a_typed_repository_operation():
    assert callable(getattr(RetroRepository, "reclassify_session", None))
    source = inspect.getsource(ProjectMappingService.reclassify)
    assert "connection.execute" not in source
    assert "_append_audit_record" not in source


def test_project_mapping_service_requires_review_callback(tmp_path):
    repo = _repository(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(TypeError):
        ProjectMappingService(repo, vault_root=vault)
    with pytest.raises(TypeError):
        ProjectMappingService(
            repo, vault_root=vault, review_stored_evidence=None
        )


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


def test_reclassify_reviews_stored_redacted_evidence_before_repository_update(
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

    def review_stored(session_id, project_id, evidence):
        current = repo.find_session_by_source_id(session_id)
        assert current is not None
        reviewed.append((session_id, project_id, evidence, current.project_id))

    mapping_service = ProjectMappingService(
        repo,
        vault_root=vault,
        review_stored_evidence=review_stored,
    )
    mapping = mapping_service.map(root, "Projects/Example")
    completed_path = codex_home / "completed.jsonl"
    completed_path.unlink()

    mapping_service.reclassify("session-completed", mapping.id, actor="tester")

    assert len(reviewed) == 1
    assert reviewed[0][0:2] == ("session-completed", "Projects/Example")
    assert reviewed[0][2]
    assert reviewed[0][3].startswith("awaiting:")
    assert all(
        ("TOKEN" + "_FOR_REDACTION_TEST") not in item.excerpt
        for item in reviewed[0][2]
    )
    persisted = repo.find_session_by_source_id("session-completed")
    assert persisted is not None
    assert persisted.project_id == "Projects/Example"


def test_reclassify_callback_failure_leaves_session_awaiting(
    fixtures_dir, tmp_path
):
    codex_home = tmp_path / "codex"
    _copy_fixture(fixtures_dir, codex_home, "completed")
    repo = _repository(tmp_path)
    CaptureService(
        CodexSessionSource(codex_home), repo, Redactor(), ProjectResolver([])
    ).capture_session("session-completed")
    root = _git_repository(tmp_path / "project", "git@example.invalid:Owner/Repo.git")
    vault = tmp_path / "vault"
    vault.mkdir()

    def fail_review(session_id, project_id, evidence):
        raise RuntimeError("review unavailable")

    service = ProjectMappingService(
        repo, vault_root=vault, review_stored_evidence=fail_review
    )
    mapping = service.map(root, "Projects/Example")

    with pytest.raises(RuntimeError, match="review unavailable"):
        service.reclassify("session-completed", mapping.id, actor="tester")

    persisted = repo.find_session_by_source_id("session-completed")
    assert persisted is not None
    assert persisted.project_id.startswith("awaiting:")
    connection = sqlite3.connect(repo.db_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE action = 'session_reclassified'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 0


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
    with pytest.raises(SystemExit):
        parser.parse_args(["project", "reclassify", "session-1", "mapping-1"])


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
