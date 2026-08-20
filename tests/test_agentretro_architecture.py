from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

from agent_retro.application.merge import MergeService
from agent_retro.application.purge import PurgeService
from agent_retro.application.sync import ProjectionCoordinator, SyncService
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository
from agent_retro.presentation import cli


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "agentretro_complexity_targets.txt"
EXPECTED_INTERNAL_MODULES = {
    "agent_retro.application._merge_operations",
    "agent_retro.application._purge_operations",
    "agent_retro.application._sync_operations",
    "agent_retro.infrastructure._sqlite_migration",
    "agent_retro.infrastructure._sqlite_purge",
    "agent_retro.presentation._command_dispatch",
}
EXPECTED_COMPLETE_BOUNDARY_MODULES = {
    "agent_retro.application.brief",
    "agent_retro.application.merge_planner",
    "agent_retro.infrastructure.codex_guidance",
    "agent_retro.infrastructure.codex_sessions",
    "agent_retro.infrastructure.redaction",
    "agent_retro.presentation.review_commands",
}


def test_agentretro_public_refactor_entry_points_stay_compatible() -> None:
    assert tuple(inspect.signature(cli.main).parameters) == ("argv", "home", "env")
    assert tuple(inspect.signature(cli._run_command).parameters) == (
        "args",
        "home",
        "env",
    )
    assert tuple(inspect.signature(SQLiteRetroRepository).parameters) == (
        "db_path",
        "backup_dir",
    )
    assert tuple(inspect.signature(SyncService).parameters) == (
        "repository",
        "vault_root",
        "backup_root",
        "replace",
    )
    assert tuple(inspect.signature(ProjectionCoordinator).parameters) == (
        "repository",
        "projection",
        "sync",
    )
    assert tuple(inspect.signature(MergeService).parameters) == (
        "repository",
        "vault_root",
        "backup_root",
        "sync",
    )
    assert tuple(inspect.signature(PurgeService).parameters) == (
        "repository",
        "vault_root",
        "backup_roots",
        "log_paths",
        "trace_paths",
        "log_root",
        "trace_root",
        "replace",
        "completed_projection",
    )


def test_complexity_manifest_covers_every_refactor_internal_module() -> None:
    values = {
        line.strip()
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    modules = {
        value.removeprefix("src/").removesuffix(".py").replace("/", ".")
        for value in values
    }
    assert EXPECTED_INTERNAL_MODULES <= modules
    assert EXPECTED_COMPLETE_BOUNDARY_MODULES <= modules
    for module in sorted(EXPECTED_INTERNAL_MODULES):
        assert importlib.import_module(module) is not None

    imported_internal_modules: set[str] = set()
    for value in values:
        tree = ast.parse((ROOT / value).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("agent_retro."):
                    imported_internal_modules.add(node.module)
            elif isinstance(node, ast.Import):
                imported_internal_modules.update(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("agent_retro.")
                )
    imported_internal_modules = {
        module
        for module in imported_internal_modules
        if module.rsplit(".", 1)[-1].startswith("_")
    }
    assert imported_internal_modules <= modules
