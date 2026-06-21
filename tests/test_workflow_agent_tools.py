import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.agent.tool_definitions import TOOL_DEFINITIONS
from ai_todo_assistant.application.agent.tool_executor import ToolExecutor
from ai_todo_assistant.application.agent.tool_validation import validate_tool_call
from ai_todo_assistant.infrastructure.persistence import SQLiteTodoRepository, SQLiteWorkflowRepository


class TestWorkflowAgentTools(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.todo_repo = SQLiteTodoRepository(os.path.join(self.temp_dir.name, "todos.db"))
        self.workflow_repo = SQLiteWorkflowRepository(os.path.join(self.temp_dir.name, "workflow.db"))
        self.executor = ToolExecutor(
            self.todo_repo,
            {"project_root": self.temp_dir.name},
            workflow_repository=self.workflow_repo,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _tool_names(self):
        return {tool["function"]["name"] for tool in TOOL_DEFINITIONS}

    def test_workflow_tool_definitions_are_exposed(self):
        names = self._tool_names()

        self.assertIn("create_work_item", names)
        self.assertIn("record_work_evidence", names)
        self.assertIn("read_codex_task_reports", names)
        self.assertIn("generate_daily_workflow_review", names)

    def test_workflow_tool_arguments_validate(self):
        name, args = validate_tool_call(
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "create_work_item",
                    "arguments": '{"title":"修复 Redmine issue","priority":"high"}',
                },
            }
        )

        self.assertEqual(name, "create_work_item")
        self.assertEqual(args["priority"], "high")

    def test_tool_executor_dispatches_workflow_tools(self):
        created = self.executor.execute(
            "create_work_item",
            {"title": "实现 workflow agent tools", "next_action": "补测试"},
        )
        work_id = created.split("ID:")[1].rstrip(")")
        evidence = self.executor.execute(
            "record_work_evidence",
            {
                "work_item_id": work_id,
                "evidence_type": "test",
                "summary": "agent workflow tests passed",
                "success": True,
            },
        )
        summary = self.executor.execute("summarize_work_evidence", {"work_item_id": work_id})
        status = self.executor.execute("list_work_status", {})

        self.assertIn("已创建工作项", created)
        self.assertIn("已记录证据", evidence)
        self.assertIn("agent workflow tests passed", summary)
        self.assertIn("workflow agent tools", status)


if __name__ == "__main__":
    unittest.main()
