from __future__ import annotations

from pathlib import Path

import pytest

from _path import ROOT  # noqa: F401
from test_agentretro_e2e import SECRET, run_e2e_flow, sqlite_absolute_paths


def test_unique_secret_is_absent_from_every_tmp_artifact_while_proofs_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifacts = run_e2e_flow(tmp_path, monkeypatch, capsys)
    secret = SECRET.encode("utf-8")
    files = sorted(path for path in artifacts.root.rglob("*") if path.is_file())

    assert artifacts.db_path in files
    assert artifacts.trace_path in files
    assert artifacts.log_path in files
    assert artifacts.backup_root.is_dir()
    assert any(path.is_relative_to(artifacts.backup_root) for path in files)
    assert artifacts.vault.is_dir()
    assert not any(path.suffix == ".jsonl" for path in files)

    retained = b"\n".join(path.read_bytes() for path in files)
    for path in files:
        assert secret not in path.read_bytes(), f"secret leaked to {path}"
    assert b"[REDACTED]" in retained
    assert artifacts.source_hash.encode("ascii") in retained
    assert all(value.encode("ascii") in retained for value in artifacts.content_hashes)

    recorded_paths = sqlite_absolute_paths(artifacts.db_path)
    assert recorded_paths
    for path in recorded_paths:
        assert path.resolve().is_relative_to(artifacts.root), path
