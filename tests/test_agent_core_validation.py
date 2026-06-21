import os
import unittest
from datetime import datetime

import _path  # noqa: F401
from ai_todo_assistant.application.agent import AgentCore
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager


class FakeLLMClient:
    supports_stream = False

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.stream_flags = []
        self.payloads = []

    def is_configured(self):
        return True

    def request(self, payload, stream=False, timeout=30):
        self.calls += 1
        self.stream_flags.append(stream)
        self.payloads.append(payload)
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

    def test_validation_retry_payload_includes_tool_output_for_failed_call(self):
        agent = AgentCore(self.manager, {
            "auth_mode": "openai_api",
            "api_key": "test",
            "validation_retry_limit": 3,
        })
        fake_client = FakeLLMClient([
            tool_response("add_todo", '{"title":"920 需求评审修改","priority":"urgent"}', call_id="call_bad"),
            text_response("已重新生成。"),
        ])
        agent.llm_client = fake_client

        result = agent.chat("创建一条待办：920 需求评审修改")

        self.assertEqual(result, "已重新生成。")
        retry_messages = fake_client.payloads[1]["messages"]
        self.assertIn(
            {
                "role": "tool",
                "tool_call_id": "call_bad",
                "content": "[参数错误] add_todo.priority 的值不在允许范围: 'high', 'medium' or 'low'",
            },
            retry_messages,
        )

    def test_add_todo_defaults_omitted_start_time_to_current_time(self):
        agent = AgentCore(self.manager, {
            "auth_mode": "openai_api",
            "api_key": "test",
            "validation_retry_limit": 3,
        })
        fake_client = FakeLLMClient([
            tool_response("add_todo", '{"title":"920 需求评审修改"}'),
            text_response("已创建。"),
        ])
        agent.llm_client = fake_client

        result = agent.chat("新增代办，下周前完成920 需求评审修改")

        self.assertEqual(result, "已创建。")
        todos = self.manager.get_all()
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].title, "920 需求评审修改")
        self.assertTrue(todos[0].start_time.startswith(datetime.now().strftime("%Y-%m-%d ")))

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

    def test_validation_failure_keeps_user_message_in_session_memory(self):
        agent = AgentCore(self.manager, {
            "auth_mode": "openai_api",
            "api_key": "test",
            "validation_retry_limit": 0,
        })
        fake_client = FakeLLMClient([
            tool_response("add_todo", "{}"),
            text_response("新的回复"),
        ])
        agent.llm_client = fake_client

        agent.chat("创建一条缺参数的待办")
        agent.chat("继续")

        second_messages = fake_client.payloads[1]["messages"]
        self.assertIn({"role": "user", "content": "创建一条缺参数的待办"}, second_messages)
        self.assertEqual(second_messages[-1], {"role": "user", "content": "继续"})

    def test_stream_request_falls_back_to_non_streaming_when_tools_are_enabled(self):
        agent = AgentCore(self.manager, {
            "auth_mode": "openai_api",
            "api_key": "test",
            "validation_retry_limit": 3,
        })
        fake_client = FakeLLMClient([
            tool_response("add_todo", '{"title":"为agent添加记忆"}'),
            text_response("已创建。"),
        ])
        fake_client.supports_stream = True
        agent.llm_client = fake_client

        result = agent.chat("今天添加任务为agent添加记忆", stream=True)

        self.assertEqual(result, "已创建。")
        self.assertEqual(fake_client.stream_flags, [False, False])
        todos = self.manager.get_all()
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].title, "为agent添加记忆")

    def test_agent_core_uses_session_memory_for_next_request(self):
        agent = AgentCore(self.manager, {
            "auth_mode": "openai_api",
            "api_key": "test",
            "session_memory_limit": 4,
        })
        fake_client = FakeLLMClient([
            text_response("第一次回复"),
            text_response("第二次回复"),
        ])
        agent.llm_client = fake_client

        first = agent.chat("第一次问题")
        second = agent.chat("第二次问题")

        self.assertEqual(first, "第一次回复")
        self.assertEqual(second, "第二次回复")
        second_messages = fake_client.payloads[1]["messages"]
        self.assertEqual(
            second_messages[-3:],
            [
                {"role": "user", "content": "第一次问题"},
                {"role": "assistant", "content": "第一次回复"},
                {"role": "user", "content": "第二次问题"},
            ],
        )

    def test_clear_history_clears_session_memory(self):
        agent = AgentCore(self.manager, {
            "auth_mode": "openai_api",
            "api_key": "test",
        })
        fake_client = FakeLLMClient([
            text_response("第一次回复"),
            text_response("第二次回复"),
        ])
        agent.llm_client = fake_client

        agent.chat("第一次问题")
        agent.clear_history()
        agent.chat("第二次问题")

        second_messages = fake_client.payloads[1]["messages"]
        self.assertEqual(second_messages[-1], {"role": "user", "content": "第二次问题"})
        self.assertNotIn({"role": "assistant", "content": "第一次回复"}, second_messages)


if __name__ == "__main__":
    unittest.main()
