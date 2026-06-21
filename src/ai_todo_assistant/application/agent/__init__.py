"""Agent 应用层。"""

from ai_todo_assistant.application.agent.tool_definitions import TOOL_DEFINITIONS
from ai_todo_assistant.application.agent.tool_executor import ToolExecutor

__all__ = ["AgentCore", "ToolExecutor", "TOOL_DEFINITIONS"]


def __getattr__(name):
    if name == "AgentCore":
        from ai_todo_assistant.application.agent.core import AgentCore

        return AgentCore
    raise AttributeError(name)

