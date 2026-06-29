import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.agent.tool_executor import ToolExecutor
from ai_todo_assistant.application.agent.tool_validation import ToolValidationError, validate_tool_call
from ai_todo_assistant.infrastructure.connectors import CommandResult
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager


class FakeRunner:
    def __init__(self, result):
        self.result = result

    def run(self, args, cwd=""):
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


if __name__ == "__main__":
    unittest.main()
