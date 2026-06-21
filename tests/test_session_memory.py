import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.memory import SessionMemory


class TestSessionMemory(unittest.TestCase):
    def test_adds_user_and_assistant_messages(self):
        memory = SessionMemory(max_messages=4)

        memory.add_user_message("你好")
        memory.add_assistant_message("你好，有什么可以帮你？")

        self.assertEqual(memory.snapshot(), [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么可以帮你？"},
        ])

    def test_keeps_latest_messages_when_limit_exceeded(self):
        memory = SessionMemory(max_messages=3)

        memory.add_user_message("第一条")
        memory.add_assistant_message("第二条")
        memory.add_user_message("第三条")
        memory.add_assistant_message("第四条")

        self.assertEqual(memory.snapshot(), [
            {"role": "assistant", "content": "第二条"},
            {"role": "user", "content": "第三条"},
            {"role": "assistant", "content": "第四条"},
        ])

    def test_build_messages_prepends_system_message(self):
        memory = SessionMemory(max_messages=2)
        system_message = {"role": "system", "content": "系统提示"}

        memory.add_user_message("用户消息")

        self.assertEqual(memory.build_messages(system_message), [
            system_message,
            {"role": "user", "content": "用户消息"},
        ])

    def test_clear_removes_messages(self):
        memory = SessionMemory(max_messages=2)
        memory.add_user_message("用户消息")

        memory.clear()

        self.assertEqual(memory.snapshot(), [])

    def test_snapshot_returns_copy(self):
        memory = SessionMemory(max_messages=2)
        memory.add_user_message("用户消息")

        snapshot = memory.snapshot()
        snapshot.append({"role": "assistant", "content": "外部修改"})

        self.assertEqual(memory.snapshot(), [{"role": "user", "content": "用户消息"}])

    def test_rejects_non_positive_limit(self):
        with self.assertRaises(ValueError):
            SessionMemory(max_messages=0)


if __name__ == "__main__":
    unittest.main()
