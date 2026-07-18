"""AgentRetro composition boundary."""

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from agent_retro.application.doctor import DoctorService
from agent_retro.application.ports import RetroRepository
from agent_retro.application.purge import PurgeService
from agent_retro.application.sync import ProjectionCoordinator, SyncService
from agent_retro.infrastructure.codex_guidance import discover_managed_instruction
from agent_retro.infrastructure.obsidian import ObsidianProjection
from agent_retro.infrastructure.settings import RetroSettings
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


def build_retro_repository(settings: RetroSettings) -> RetroRepository:
    """Build and migrate the repository isolated by AgentRetro settings."""

    repository = SQLiteRetroRepository(settings.db_path, settings.backup_dir)
    repository.migrate()
    return repository


def build_projection_coordinator(
    settings: RetroSettings, repository: RetroRepository
) -> ProjectionCoordinator:
    """Compose bounded filesystem services without performing a write."""

    vault = settings.obsidian_root
    return ProjectionCoordinator(
        repository,
        ObsidianProjection(vault, settings.backup_dir),
        SyncService(repository, vault, settings.backup_dir),
    )


def build_purge_service(
    settings: RetroSettings,
    repository: RetroRepository,
    *,
    completed_projection: Callable[[str, str, str], object] | None = None,
) -> PurgeService:
    """Compose purge from fixed AgentRetro-owned settings only."""

    return PurgeService(
        repository,
        vault_root=settings.obsidian_root,
        backup_roots={"agentretro_backup": settings.backup_dir},
        log_paths=_registered_state_files(settings.state_dir / "logs"),
        trace_paths=_registered_state_files(settings.state_dir / "traces"),
        log_root=settings.state_dir / "logs",
        trace_root=settings.state_dir / "traces",
        completed_projection=completed_projection,
    )


def _registered_state_files(root: Path) -> tuple[Path, ...]:
    if root.is_symlink():
        raise ValueError("AgentRetro state registration contains a symlink")
    if not root.exists():
        return ()
    if not root.is_dir():
        raise ValueError("AgentRetro state registration must be a directory")
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in dirnames:
            if (directory_path / name).is_symlink():
                raise ValueError("AgentRetro state registration contains a symlink")
        dirnames[:] = sorted(dirnames)
        for name in sorted(filenames):
            target = directory_path / name
            if target.is_symlink():
                raise ValueError("AgentRetro state registration contains a symlink")
            files.append(target)
    return tuple(files)


def build_doctor_service(
    settings: RetroSettings,
    codex_home: Path,
    model_config_loader: Callable[[], Mapping[str, object]],
) -> DoctorService:
    """Compose read-only diagnostics without migrating or creating state."""

    repository = SQLiteRetroRepository(settings.db_path, settings.backup_dir)
    return DoctorService(
        settings,
        repository,
        codex_home=codex_home,
        model_config_loader=model_config_loader,
        integration_discoverer=discover_managed_instruction,
    )
