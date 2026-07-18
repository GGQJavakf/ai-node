"""AgentRetro composition boundary."""

from agent_retro.application.ports import RetroRepository
from agent_retro.application.sync import ProjectionCoordinator, SyncService
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
