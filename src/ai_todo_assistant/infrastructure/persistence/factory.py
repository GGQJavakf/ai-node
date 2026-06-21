"""待办仓储工厂。"""
from __future__ import annotations

import os

from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager as JsonTodoRepository
from ai_todo_assistant.infrastructure.persistence.migration import migrate_json_to_sqlite
from ai_todo_assistant.infrastructure.persistence.sqlite_todo_repository import SQLiteTodoRepository


def build_todo_repository(config: dict | None = None):
    """根据配置创建待办仓储，默认使用 SQLite。"""
    config = config or {}
    backend = (config.get("storage_backend") or "sqlite").lower()

    if backend == "json":
        return JsonTodoRepository(config.get("todo_data_file", "todos.json"))

    if backend != "sqlite":
        raise ValueError(f"不支持的存储后端: {backend}")

    sqlite_path = _resolve_path(
        config.get("sqlite_path", "data/todos.db"),
        config.get("project_root"),
    )
    repository = SQLiteTodoRepository(sqlite_path)

    if _as_bool(config.get("auto_migrate_json", True)) and repository.is_empty():
        json_path = _resolve_path(
            config.get("todo_data_file", "todos.json"),
            config.get("project_root"),
        )
        migrate_json_to_sqlite(json_path, repository)

    return repository


def _resolve_path(path: str, project_root: str | None) -> str:
    if os.path.isabs(path) or not project_root:
        return path
    return os.path.join(project_root, path)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
