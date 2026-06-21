import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.reactor import (
    AgentReactor,
    ExecuteTools,
    LlmResponseReceived,
    ReactorState,
    RequestLlm,
    ToolExecutionCompleted,
    UserMessageReceived,
)


def tool_response(name, arguments, call_id="call_1"):
    return {
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
    }


class TestAgentReactor(unittest.TestCase):
    def setUp(self):
        self.reactor = AgentReactor(
            model="test-model",
            tool_definitions=[{"type": "function", "function": {"name": "add_todo"}}],
            validation_retry_limit=2,
        )

    def test_user_message_emits_llm_request_effect(self):
        state = ReactorState(
            system_message={"role": "system", "content": "system"},
            memory_messages=[{"role": "assistant", "content": "之前的回复"}],
            stream=False,
        )

        next_state, effects = self.reactor.step(state, UserMessageReceived("帮我添加买菜"))

        self.assertEqual(next_state.messages[-1], {"role": "user", "content": "帮我添加买菜"})
        self.assertEqual(len(effects), 1)
        self.assertIsInstance(effects[0], RequestLlm)
        self.assertEqual(effects[0].payload["model"], "test-model")
        self.assertEqual(effects[0].payload["messages"][0], {"role": "system", "content": "system"})
        self.assertEqual(effects[0].payload["messages"][-1], {"role": "user", "content": "帮我添加买菜"})
        self.assertEqual(effects[0].payload["tool_choice"], "auto")

    def test_final_llm_message_stops_without_tool_effects(self):
        state = ReactorState(messages=[{"role": "user", "content": "你好"}])
        message = {"role": "assistant", "content": "你好，我在。"}

        next_state, effects = self.reactor.step(state, LlmResponseReceived(message))

        self.assertEqual(next_state.final_response, "你好，我在。")
        self.assertEqual(next_state.stop_reason, "final")
        self.assertEqual(effects, [])

    def test_valid_tool_calls_emit_execute_tools_effect(self):
        state = ReactorState(messages=[{"role": "user", "content": "添加买菜"}])

        next_state, effects = self.reactor.step(
            state,
            LlmResponseReceived(tool_response("add_todo", '{"title":"买菜"}')),
        )

        self.assertEqual(next_state.messages[-1]["role"], "assistant")
        self.assertEqual(len(effects), 1)
        self.assertIsInstance(effects[0], ExecuteTools)
        self.assertEqual(effects[0].calls[0].name, "add_todo")
        self.assertEqual(effects[0].calls[0].args["title"], "买菜")

    def test_invalid_tool_calls_append_retry_feedback_without_execute_effect(self):
        state = ReactorState(messages=[{"role": "user", "content": "添加任务"}])

        next_state, effects = self.reactor.step(
            state,
            LlmResponseReceived(tool_response("add_todo", '{"priority":"urgent"}', call_id="bad_call")),
        )

        self.assertEqual(len(effects), 1)
        self.assertIsInstance(effects[0], RequestLlm)
        self.assertEqual(next_state.validation_failures, 1)
        self.assertEqual(next_state.messages[-2]["role"], "tool")
        self.assertEqual(next_state.messages[-2]["tool_call_id"], "bad_call")
        self.assertIn("add_todo.priority", next_state.messages[-2]["content"])
        self.assertEqual(next_state.messages[-1]["role"], "user")
        self.assertIn("工具尚未执行", next_state.messages[-1]["content"])

    def test_validation_retry_limit_stops_loop(self):
        state = ReactorState(
            messages=[{"role": "user", "content": "添加任务"}],
            validation_failures=2,
        )

        next_state, effects = self.reactor.step(
            state,
            LlmResponseReceived(tool_response("add_todo", '{"priority":"urgent"}')),
        )

        self.assertEqual(effects, [])
        self.assertEqual(next_state.stop_reason, "validation_failed")
        self.assertIn("工具参数连续校验失败", next_state.final_response)

    def test_tool_execution_results_append_tool_messages_and_request_next_llm(self):
        state = ReactorState(messages=[
            {"role": "user", "content": "添加买菜"},
            tool_response("add_todo", '{"title":"买菜"}', call_id="call_add"),
        ])

        next_state, effects = self.reactor.step(
            state,
            ToolExecutionCompleted([{
                "tool_call_id": "call_add",
                "content": "成功新增待办事项：「买菜」",
            }]),
        )

        self.assertEqual(next_state.messages[-1], {
            "role": "tool",
            "tool_call_id": "call_add",
            "content": "成功新增待办事项：「买菜」",
        })
        self.assertEqual(len(effects), 1)
        self.assertIsInstance(effects[0], RequestLlm)
        self.assertEqual(effects[0].payload["messages"][-1]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
