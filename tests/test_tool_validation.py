import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.agent.tool_validation import (
    ToolValidationError,
    validate_tool_call,
)


class TestToolValidation(unittest.TestCase):
    def _tool_call(self, name, arguments):
        return {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        }

    def test_accepts_valid_add_todo_arguments(self):
        name, args = validate_tool_call(
            self._tool_call("add_todo", '{"title":"明天要开GPT会员","priority":"high"}')
        )

        self.assertEqual(name, "add_todo")
        self.assertEqual(args["title"], "明天要开GPT会员")
        self.assertEqual(args["priority"], "high")

    def test_rejects_unknown_tool_name(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("create_payment", "{}"))

        self.assertIn("未知工具", str(ctx.exception))

    def test_rejects_malformed_arguments_json(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("add_todo", '{"title":'))

        self.assertIn("不是合法 JSON", str(ctx.exception))

    def test_rejects_missing_required_argument(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("add_todo", "{}"))

        self.assertIn("缺少必填参数", str(ctx.exception))

    def test_rejects_invalid_enum(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("add_todo", '{"title":"买菜","priority":"urgent"}'))

        self.assertIn("不在允许范围", str(ctx.exception))

    def test_rejects_unknown_argument(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("add_todo", '{"title":"买菜","shell":"rm"}'))

        self.assertIn("未知参数", str(ctx.exception))

    def test_rejects_blank_title(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("add_todo", '{"title":"   "}'))

        self.assertIn("title", str(ctx.exception))

    def test_rejects_blank_id(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("toggle_todo", '{"id":"   "}'))

        self.assertIn("id", str(ctx.exception))

    def test_rejects_empty_delete_ids(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("delete_todos", '{"ids":[]}'))

        self.assertIn("ids", str(ctx.exception))

    def test_rejects_array_items_with_wrong_type(self):
        with self.assertRaises(ToolValidationError) as ctx:
            validate_tool_call(self._tool_call("delete_todos", '{"ids":["1",2]}'))

        self.assertIn("ids[1]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
