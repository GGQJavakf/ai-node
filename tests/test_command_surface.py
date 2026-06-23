import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.infrastructure.persistence import SQLiteWorkflowRepository
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager
from ai_todo_assistant.presentation.cli import CommandCompleter, TodoCLI


class TestAssistantCommandSurface(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workflow_path = os.path.join(self.temp_dir.name, "workflow.db")
        self.report_dir = os.path.join(self.temp_dir.name, "reports")
        os.makedirs(self.report_dir, exist_ok=True)
        self.cli = object.__new__(TodoCLI)
        self.cli.workflow_repository = SQLiteWorkflowRepository(self.workflow_path)
        self.cli.config = {
            "project_root": self.temp_dir.name,
            "codex_task_report_dir": self.report_dir,
            "storage_backend": "sqlite",
            "sqlite_path": self.workflow_path,
        }
        self.cli.manager = TodoManager(os.path.join(self.temp_dir.name, "todos.json"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_next_is_preferred_alias_for_continue(self):
        self.assertEqual(
            self.cli._handle_slash_command("/next"),
            self.cli._handle_slash_command("/continue"),
        )

    def test_bare_review_is_preferred_alias_for_review_day(self):
        self.assertEqual(
            self.cli._handle_slash_command("/review"),
            self.cli._handle_slash_command("/review day"),
        )

    def test_help_shows_primary_commands_before_advanced_groups(self):
        help_text = self.cli._handle_slash_command("/help")

        primary_index = help_text.index("日常主命令")
        category_index = help_text.index("分类帮助")
        self.assertLess(primary_index, category_index)
        for line in [
            "/list    统一任务视图",
            "/sync    同步最新工作上下文",
            "/next    推荐下一步",
            "/review  生成今日复盘",
            "/help    查看帮助",
        ]:
            self.assertGreater(help_text.index(line), primary_index)
            self.assertLess(help_text.index(line), category_index)
        for legacy_or_detail in ["[bold]", "[/bold]", "today|week", "/continue", "/review day"]:
            self.assertNotIn(legacy_or_detail, help_text[:category_index])

    def test_help_groups_advanced_commands_and_keeps_compatibility_aliases(self):
        work_help = self.cli._handle_slash_command("/help work")

        for text in ["/work status", "/work evidence add", "/codex tasks", "/sync watch", "/next", "/review"]:
            self.assertIn(text, work_help)
        self.assertIn("/continue", work_help)
        self.assertIn("/review day", work_help)
        self.assertIn("兼容", work_help)

    def test_categorized_help_topics_show_focused_commands(self):
        todo_help = self.cli._handle_slash_command("/help todo")
        prefs_help = self.cli._handle_slash_command("/help prefs")
        system_help = self.cli._handle_slash_command("/help system")

        self.assertIn("/add [high|medium|low] <标题>", todo_help)
        self.assertIn("/list [all|today|week|month|pending|completed|overdue|upcoming|high|medium|low]", todo_help)
        self.assertIn("/update <ID> [title|end_time|priority] <值>", todo_help)
        self.assertNotIn("/work evidence", todo_help)
        self.assertIn("/preferences", prefs_help)
        self.assertIn("/remember <偏好名> <偏好内容>", prefs_help)
        self.assertIn("/history", system_help)
        self.assertIn("/exit 或 /quit", system_help)

    def test_command_completion_contains_preferred_and_compatible_commands(self):
        commands = CommandCompleter().commands

        for command in [
            "/list",
            "/list all",
            "/sync",
            "/sync watch",
            "/next",
            "/review",
            "/continue",
            "/review day",
            "/help todo",
            "/help work",
            "/help prefs",
            "/help system",
        ]:
            self.assertIn(command, commands)

    def test_startup_panel_shows_primary_commands_before_advanced_groups(self):
        startup_text = self.cli._startup_panel_text()

        primary_index = startup_text.index("日常主命令")
        category_index = startup_text.index("分类帮助")
        self.assertLess(primary_index, category_index)
        for line in [
            "/list    统一任务视图",
            "/sync    同步最新工作上下文",
            "/next    推荐下一步",
            "/review  生成今日复盘",
            "/help    查看帮助",
        ]:
            self.assertGreater(startup_text.index(line), primary_index)
            self.assertLess(startup_text.index(line), category_index)
        self.assertIn("/help work", startup_text)
        self.assertNotIn("[bold]", startup_text)
        self.assertNotIn("/continue", startup_text[:category_index])
        self.assertNotIn("/review day", startup_text[:category_index])


if __name__ == "__main__":
    unittest.main()
