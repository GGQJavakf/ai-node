import os
import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.agent import AgentCore
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager


class FakeLLMClient:
    supports_stream = False

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def is_configured(self):
        return True

    def request(self, payload, stream=False, timeout=30):
        self.calls += 1
        if not self.responses:
            raise AssertionError("FakeLLMClient 没有剩余响应")
        return self.responses.pop(0)


def tool_response(name, arguments, call_id="call_1"):
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": arguments,
                    },
                }],
            },
        }],
    }


def text_response(content):
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": content,
            },
        }],
    }


class TestAgentCoreValidationRetry(unittest.TestCase):
    def setUp(self):
        self.test_file = "test_agent_core_validation_todos.json"
        self.manager = TodoManager(self.test_file)

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_retries_when_tool_arguments_fail_local_validation(self):
        agent = AgentCore(self.manager, {
            "auth_mode": "openai_api",
            "api_key": "test",
            "validation_retry_limit": 3,
        })
        fake_client = FakeLLMClient([
            tool_response("add_todo", '{"priority":"urgent"}'),
            tool_response("add_todo", '{"title":"明天要开GPT会员","priority":"high"}'),
            text_response("已创建。"),
        ])
        agent.llm_client = fake_client

        result = agent.chat("创建一条待办：明天要开GPT会员")

        self.assertEqual(result, "已创建。")
        self.assertEqual(fake_client.calls, 3)
        todos = self.manager.get_all()
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].title, "明天要开GPT会员")

    def test_stops_after_configured_validation_retry_limit(self):
        agent = AgentCore(self.manager, {
            "auth_mode": "openai_api",
            "api_key": "test",
            "validation_retry_limit": 1,
        })
        fake_client = FakeLLMClient([
            tool_response("add_todo", "{}"),
            tool_response("add_todo", '{"priority":"urgent"}'),
            text_response("不应该到这里"),
        ])
        agent.llm_client = fake_client

        result = agent.chat("创建一条待办")

        self.assertIn("工具参数连续校验失败", result)
        self.assertEqual(fake_client.calls, 2)
        self.assertEqual(self.manager.get_all(), [])


if __name__ == "__main__":
    unittest.main()
