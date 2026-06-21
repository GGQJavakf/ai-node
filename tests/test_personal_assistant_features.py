import os
import tempfile
import unittest
from datetime import datetime, timedelta

import _path  # noqa: F401
from ai_todo_assistant.application.agent.tool_executor import ToolExecutor
from ai_todo_assistant.infrastructure.persistence import SQLiteTodoRepository, TodoManager
from ai_todo_assistant.presentation.cli import TodoCLI


class TestPersonalAssistantCli(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteTodoRepository(os.path.join(self.temp_dir.name, "todos.db"))
        self.cli = object.__new__(TodoCLI)
        self.cli.manager = self.repository

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_without_priority_keeps_full_title(self):
        response = self.cli._handle_slash_command("/add 买菜")

        todos = self.repository.get_all()
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].title, "买菜")
        self.assertEqual(todos[0].priority, "medium")
        self.assertIn("买菜", response)

    def test_today_command_summarizes_due_overdue_and_high_priority_tasks(self):
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.repository.add("今天提交周报", end_time=f"{today} 18:00:00", priority="high")
        self.repository.add("昨天遗留评审", end_time=f"{yesterday} 18:00:00", priority="medium")

        response = self.cli._handle_slash_command("/today")

        self.assertIn("今日简报", response)
        self.assertIn("今天提交周报", response)
        self.assertIn("昨天遗留评审", response)
        self.assertIn("优先处理", response)

    def test_plan_day_orders_pending_tasks_by_priority_and_deadline(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.repository.add("低优先级整理", end_time=f"{today} 20:00:00", priority="low")
        self.repository.add("高优先级交付", end_time=f"{today} 18:00:00", priority="high")

        response = self.cli._handle_slash_command("/plan day")

        self.assertIn("今日计划", response)
        self.assertLess(response.index("高优先级交付"), response.index("低优先级整理"))

    def test_single_argument_slash_commands_use_the_first_argument(self):
        todo = self.repository.add("写周报")

        search_response = self.cli._handle_slash_command("/search 周报")
        toggle_response = self.cli._handle_slash_command(f"/toggle {todo.id}")
        delete_response = self.cli._handle_slash_command(f"/delete {todo.id}")

        self.assertIn("写周报", search_response)
        self.assertIn("已完成", toggle_response)
        self.assertIn("已删除", delete_response)
        self.assertEqual(self.repository.get_all(), [])


class TestPersistentAssistantPreferences(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "todos.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_preferences_are_persisted_across_repository_instances(self):
        first = SQLiteTodoRepository(self.db_path)
        first.remember_preference("工作时间", "工作日 09:30-18:30")

        second = SQLiteTodoRepository(self.db_path)
        preferences = second.list_preferences()

        self.assertEqual(preferences["工作时间"], "工作日 09:30-18:30")

    def test_tool_executor_can_manage_preferences(self):
        repository = SQLiteTodoRepository(self.db_path)
        executor = ToolExecutor(repository)

        remember = executor.execute(
            "remember_preference",
            {"key": "称呼", "value": "叫我老赵"},
        )
        listed = executor.execute("list_preferences", {})
        forgotten = executor.execute("forget_preference", {"key": "称呼"})

        self.assertIn("已记住", remember)
        self.assertIn("称呼", listed)
        self.assertIn("叫我老赵", listed)
        self.assertIn("已忘记", forgotten)
        self.assertEqual(repository.list_preferences(), {})

    def test_json_repository_persists_preferences_in_sidecar_file(self):
        json_path = os.path.join(self.temp_dir.name, "todos.json")
        first = TodoManager(json_path)
        first.remember_preference("输出风格", "结论先行")

        second = TodoManager(json_path)

        self.assertEqual(second.list_preferences(), {"输出风格": "结论先行"})


if __name__ == "__main__":
    unittest.main()
