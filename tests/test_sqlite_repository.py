import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

import _path  # noqa: F401
from ai_todo_assistant.infrastructure.persistence import (
    JsonTodoRepository,
    SQLiteTodoRepository,
    build_todo_repository,
)


class TestSQLiteTodoRepository(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "todos.db")
        self.repository = SQLiteTodoRepository(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_reload_todo(self):
        created = self.repository.add("SQLite任务", "描述", end_time="2026-12-31", priority="high")

        reloaded = SQLiteTodoRepository(self.db_path)
        todos = reloaded.get_all()

        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].id, created.id)
        self.assertEqual(todos[0].title, "SQLite任务")
        self.assertEqual(todos[0].priority, "high")

    def test_update_delete_and_toggle_todo(self):
        todo = self.repository.add("原标题", "原描述")

        updated = self.repository.update(todo.id, title="新标题", description="新描述")
        self.assertEqual(updated.title, "新标题")
        self.assertEqual(updated.description, "新描述")

        toggled = self.repository.toggle_completed(todo.id)
        self.assertTrue(toggled.completed)

        self.assertTrue(self.repository.delete(todo.id))
        self.assertIsNone(self.repository.get_by_id(todo.id))

    def test_search_statistics_and_clear_completed(self):
        finished = self.repository.add("写SQLite测试", priority="high")
        self.repository.add("整理文档")
        self.repository.toggle_completed(finished.id)

        self.assertEqual(len(self.repository.search("sqlite")), 1)

        stats = self.repository.get_statistics()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["pending"], 1)

        self.assertEqual(self.repository.clear_completed(), 1)
        self.assertEqual(len(self.repository.get_all()), 1)

    def test_date_queries_match_existing_repository_contract(self):
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        self.repository.add("今天任务", end_time=today)
        self.repository.add("明天任务", end_time=tomorrow)

        self.assertEqual(len(self.repository.get_by_date(today)), 1)
        self.assertTrue(self.repository.get_today())
        self.assertTrue(self.repository.get_this_week())
        self.assertTrue(self.repository.get_this_month())
        self.assertIn(today, self.repository.get_by_month(datetime.now().year, datetime.now().month))


class TestRepositoryFactory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_factory_uses_sqlite_by_default(self):
        repo = build_todo_repository({
            "project_root": self.temp_dir.name,
            "sqlite_path": os.path.join(self.temp_dir.name, "data", "todos.db"),
        })

        self.assertIsInstance(repo, SQLiteTodoRepository)

    def test_factory_can_use_json_backend(self):
        repo = build_todo_repository({
            "storage_backend": "json",
            "todo_data_file": os.path.join(self.temp_dir.name, "todos.json"),
        })

        self.assertIsInstance(repo, JsonTodoRepository)

    def test_factory_migrates_json_into_empty_sqlite_database(self):
        json_path = os.path.join(self.temp_dir.name, "todos.json")
        db_path = os.path.join(self.temp_dir.name, "data", "todos.db")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([
                {
                    "id": "todo-1",
                    "title": "迁移任务",
                    "description": "来自JSON",
                    "end_time": "2026-12-31",
                    "priority": "high",
                    "completed": False,
                    "created_at": "2026-01-01 00:00:00",
                }
            ], f, ensure_ascii=False)

        repo = build_todo_repository({
            "project_root": self.temp_dir.name,
            "sqlite_path": db_path,
            "todo_data_file": json_path,
            "auto_migrate_json": True,
        })

        todos = repo.get_all()
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].id, "todo-1")
        self.assertTrue(os.path.exists(json_path))


if __name__ == "__main__":
    unittest.main()
