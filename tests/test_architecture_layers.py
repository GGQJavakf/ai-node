"""
DDD 分层结构回归测试。

这些测试不关心 UI 细节，只锁定长期维护需要的模块边界：
领域对象、应用服务、基础设施适配器和兼容入口都应该可以稳定导入。
"""
import os
import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.todo_service import TodoApplicationService
from ai_todo_assistant.domain.models import Todo
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager
from ai_todo_assistant.infrastructure.llm.clients import (
    CodexCliClient,
    OpenAICompatibleClient,
    build_llm_client,
)
from ai_todo_assistant.application.agent.tool_executor import ToolExecutor


class TestArchitectureLayers(unittest.TestCase):
    def setUp(self):
        self.test_file = "test_architecture_todos.json"
        self.manager = TodoManager(self.test_file)

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_domain_and_infrastructure_imports_are_available(self):
        todo = Todo("分层测试", due_date="2026-12-31")
        self.assertEqual(todo.title, "分层测试")
        self.assertEqual(todo.due_date, "2026-12-31")
        self.assertIsInstance(self.manager, TodoManager)

    def test_application_service_wraps_todo_use_cases(self):
        service = TodoApplicationService(self.manager)

        created = service.create_todo("写 README", priority="high")
        service.mark_completed(created.id)

        stats = service.get_statistics()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["completed"], 1)

    def test_agent_and_llm_adapters_are_importable(self):
        executor = ToolExecutor(self.manager)
        self.assertIn("当前待办统计", executor.execute("get_statistics", {}))

        openai_client = build_llm_client({
            "auth_mode": "openai_api",
            "api_key": "test",
            "api_base": "https://example.test/v1",
        })
        codex_client = build_llm_client({"auth_mode": "codex_cli"})

        self.assertIsInstance(openai_client, OpenAICompatibleClient)
        self.assertIsInstance(codex_client, CodexCliClient)

    def test_agent_core_uses_configured_request_timeout(self):
        from ai_todo_assistant.application.agent import AgentCore

        agent = AgentCore(self.manager, {
            "auth_mode": "codex_cli",
            "codex_timeout": 120,
        })

        self.assertEqual(agent.request_timeout, 120)


if __name__ == "__main__":
    unittest.main()
