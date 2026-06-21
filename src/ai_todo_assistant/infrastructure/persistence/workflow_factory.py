"""Workflow repository factory."""
from __future__ import annotations

import os

from ai_todo_assistant.infrastructure.persistence.workflow_json_repository import JsonWorkflowRepository
from ai_todo_assistant.infrastructure.persistence.workflow_sqlite_repository import SQLiteWorkflowRepository


def build_workflow_repository(config: dict | None = None):
    config = config or {}
    backend = (config.get("storage_backend") or "sqlite").lower()
    if backend == "json":
        path = _resolve_path(
            config.get("workflow_data_file", "data/workflow.json"),
            config.get("project_root"),
        )
        return JsonWorkflowRepository(path)
    if backend != "sqlite":
        raise ValueError(f"不支持的存储后端: {backend}")
    path = _resolve_path(config.get("sqlite_path", "data/todos.db"), config.get("project_root"))
    return SQLiteWorkflowRepository(path)


def _resolve_path(path: str, project_root: str | None) -> str:
    if os.path.isabs(path) or not project_root:
        return path
    return os.path.join(project_root, path)
