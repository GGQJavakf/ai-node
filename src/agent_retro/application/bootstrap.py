"""AgentRetro composition boundary."""

from agent_retro.application.ports import RetroRepository
from agent_retro.infrastructure.settings import RetroSettings
from agent_retro.infrastructure.sqlite_repository import SQLiteRetroRepository


def build_retro_repository(settings: RetroSettings) -> RetroRepository:
    """Build and migrate the repository isolated by AgentRetro settings."""

    repository = SQLiteRetroRepository(settings.db_path, settings.backup_dir)
    repository.migrate()
    return repository
