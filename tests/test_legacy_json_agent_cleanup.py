from __future__ import annotations

import logging

import pytest

from _path import ROOT  # noqa: F401
from ai_todo_assistant.application.agent import legacy_json_agent


class _Manager:
    @staticmethod
    def get_all():
        return []


class _Client:
    def __init__(self, content: str) -> None:
        self.content = content

    @staticmethod
    def is_configured() -> bool:
        return True

    def request(self, data, *, timeout):
        assert data["messages"][-1]["content"] == "你好"
        assert timeout == 30
        return {"choices": [{"message": {"content": self.content}}]}


@pytest.mark.parametrize(
    "wrapped",
    [
        '```json\n{"action":"chat","params":{},"response":"正常"}\n```',
        '```\n{"action":"chat","params":{},"response":"正常"}\n```',
    ],
)
def test_legacy_json_agent_keeps_markdown_fence_compatibility(wrapped: str) -> None:
    agent = object.__new__(legacy_json_agent.AITodoAgent)
    agent.manager = _Manager()
    agent.api_base = "https://example.invalid"
    agent.model = "test-model"
    agent.auth_mode = "api_key"
    agent.request_timeout = 30
    agent.llm_client = _Client(wrapped)

    assert agent.process_command("你好") == "正常"


def test_legacy_log_level_keeps_error_default_when_config_read_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(legacy_json_agent.os.path, "exists", lambda path: True)

    def fail_open(*args, **kwargs):
        raise OSError("injected unreadable config")

    monkeypatch.setattr("builtins.open", fail_open)

    assert legacy_json_agent._get_log_level() == logging.ERROR
