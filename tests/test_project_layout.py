"""
项目目录结构测试。

用于约束开源项目风格：源码统一放入 src 包，根目录只保留项目元数据、
文档、配置、数据和目录，不再散落旧业务模块。
"""
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


class TestProjectLayout(unittest.TestCase):
    def test_source_package_uses_src_layout(self):
        import ai_todo_assistant
        from ai_todo_assistant.domain.models import Todo
        from ai_todo_assistant.application.agent import AgentCore, ToolExecutor
        from ai_todo_assistant.infrastructure.persistence import TodoManager

        self.assertTrue((SRC / "ai_todo_assistant").is_dir())
        self.assertEqual(Todo("结构测试").title, "结构测试")
        self.assertTrue(callable(AgentCore))
        self.assertTrue(callable(ToolExecutor))
        self.assertTrue(callable(TodoManager))
        self.assertTrue(ai_todo_assistant.__name__)

    def test_legacy_root_modules_are_not_left_at_project_root(self):
        legacy_modules = [
            "agent_core.py",
            "agent_tools.py",
            "ai_agent.py",
            "calendar_view.py",
            "demo.py",
            "llm_client.py",
            "todo.py",
            "todo_cli.py",
            "todo_gui.py",
            "todo_manager.py",
        ]

        leftovers = [name for name in legacy_modules if (ROOT / name).exists()]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
