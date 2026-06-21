"""持久化迁移工具。"""
from __future__ import annotations

import json
import os

from ai_todo_assistant.domain.models import Todo
from ai_todo_assistant.infrastructure.persistence.sqlite_todo_repository import SQLiteTodoRepository


def migrate_json_to_sqlite(json_path: str, sqlite_repository: SQLiteTodoRepository) -> int:
    """
    从历史 todos.json 迁移到 SQLite。

    迁移只追加不存在的 ID，不删除原 JSON 文件，避免误丢本地数据。
    """
    if not os.path.exists(json_path):
        return 0

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        migrated = 0
        for item in data:
            todo = Todo.from_dict(item)
            if sqlite_repository.add_existing(todo):
                migrated += 1
        return migrated
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"警告: JSON 数据迁移失败，已跳过: {e}")
        return 0
