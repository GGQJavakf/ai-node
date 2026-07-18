"""AgentRetro composition boundary."""

from collections.abc import Callable, Mapping
from pathlib import Path

from agent_retro.application.doctor import DoctorService
from agent_retro.application.ports import RetroRepository
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
