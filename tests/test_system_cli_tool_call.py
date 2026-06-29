import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.agent.tool_executor import ToolExecutor
from ai_todo_assistant.application.agent.tool_validation import ToolValidationError, validate_tool_call
from ai_todo_assistant.application.workflow import WorkItemService
from ai_todo_assistant.domain.workflow import EvidenceType
from ai_todo_assistant.infrastructure.connectors import CommandResult
from ai_todo_assistant.infrastructure.persistence import SQLiteWorkflowRepository
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager


class FakeRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, args, cwd=""):
        self.calls.append((args, cwd))
        return self.result


class TestSystemCliToolCall(unittest.TestCase):
    def _tool_call(self, arguments):
        return {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "run_system_cli",
                "arguments": arguments,
            },
        }

    def test_validates_run_system_cli_arguments(self):
        name, args = validate_tool_call(self._tool_call('{"command_key":"git.status"}'))

        self.assertEqual(name, "run_system_cli")
        self.assertEqual(args["command_key"], "git.status")

    def test_rejects_blank_command_key(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call('{"command_key":"   "}'))

        self.assertIn("command_key", str(ctx.exception))

    def test_rejects_record_evidence_without_work_item_id(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call('{"command_key":"git.status","record_evidence":true}'))

        self.assertIn("work_item_id", str(ctx.exception))

    def test_tool_executor_returns_system_cli_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TodoManager(os.path.join(temp_dir, "todos.json"))
            executor = ToolExecutor(
                manager,
                config={"project_root": temp_dir},
                system_cli_runner=FakeRunner(CommandResult(["git"], temp_dir, 0, stdout=" M file.py\n")),
            )

            result = executor.execute("run_system_cli", {"command_key": "git.status"})

        self.assertIn("[system_cli] git.status succeeded", result)
        self.assertIn(" M file.py", result)

    def test_tool_executor_runs_openspec_validate_catalog_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = FakeRunner(CommandResult(["openspec"], temp_dir, 0, stdout='{"summary":{"totals":{"passed":1}}}\n'))
            manager = TodoManager(os.path.join(temp_dir, "todos.json"))
            executor = ToolExecutor(
                manager,
                config={"project_root": temp_dir},
                system_cli_runner=runner,
            )

            result = executor.execute("run_system_cli", {"command_key": "openspec.validate"})

        self.assertIn("[system_cli] openspec.validate succeeded", result)
        self.assertEqual(
            runner.calls,
            [(["openspec", "validate", "--all", "--strict", "--json", "--no-interactive"], temp_dir)],
        )

    def test_tool_executor_records_system_cli_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TodoManager(os.path.join(temp_dir, "todos.json"))
            workflow_repository = SQLiteWorkflowRepository(os.path.join(temp_dir, "workflow.db"))
            item = WorkItemService(workflow_repository).create_manual("记录系统 CLI 证据")
            executor = ToolExecutor(
                manager,
                config={"project_root": temp_dir},
                workflow_repository=workflow_repository,
                system_cli_runner=FakeRunner(CommandResult(["git"], temp_dir, 0, stdout=" M file.py\n")),
            )

            result = executor.execute(
                "run_system_cli",
                {
                    "command_key": "git.status",
                    "record_evidence": True,
                    "work_item_id": item.id,
                },
            )
            evidence = workflow_repository.list_evidence(item.id)

        self.assertIn("[system_cli] git.status succeeded", result)
        self.assertIn("Evidence recorded", result)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].evidence_type, EvidenceType.COMMAND.value)
        self.assertEqual(evidence[0].source, "system-cli")
        self.assertEqual(evidence[0].command, "git status --short")
        self.assertEqual(evidence[0].output_excerpt, " M file.py")


if __name__ == "__main__":
    unittest.main()
