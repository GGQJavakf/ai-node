import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.agent.tool_definitions import TOOL_DEFINITIONS


class TestToolDefinitions(unittest.TestCase):
    def _parameters_for(self, tool_name):
        for tool in TOOL_DEFINITIONS:
            function = tool.get("function", {})
            if function.get("name") == tool_name:
                return function["parameters"]
        self.fail(f"未找到工具定义: {tool_name}")

    def test_add_todo_schema_exposes_pydantic_field_constraints(self):
        parameters = self._parameters_for("add_todo")

        self.assertEqual(parameters["additionalProperties"], False)
        self.assertIn("title", parameters["required"])
        self.assertEqual(parameters["properties"]["title"]["minLength"], 1)
        self.assertEqual(
            parameters["properties"]["priority"]["enum"],
            ["high", "medium", "low"],
        )

    def test_delete_todos_schema_requires_non_empty_ids(self):
        parameters = self._parameters_for("delete_todos")

        self.assertIn("ids", parameters["required"])
        self.assertEqual(parameters["properties"]["ids"]["minItems"], 1)


if __name__ == "__main__":
    unittest.main()
