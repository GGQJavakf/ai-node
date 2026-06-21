"""Effect runner for the assistant Reactor."""
from __future__ import annotations

import logging
import traceback
import urllib.error
from typing import Callable

from ai_todo_assistant.application.reactor.core import AgentReactor
from ai_todo_assistant.application.reactor.effects import ExecuteTools, RequestLlm
from ai_todo_assistant.application.reactor.events import (
    LlmResponseReceived,
    ToolExecutionCompleted,
    UserMessageReceived,
)
from ai_todo_assistant.application.reactor.state import ReactorState

logger = logging.getLogger("AgentRuntime")


class AgentRuntime:
    """Runs Reactor effects against injected side-effect handlers."""

    def __init__(
        self,
        reactor: AgentReactor,
        llm_client,
        tool_executor,
        request_timeout: int,
        max_tool_rounds: int,
        stream_parser: Callable | None = None,
    ):
        self.reactor = reactor
        self.llm_client = llm_client
        self.tool_executor = tool_executor
        self.request_timeout = request_timeout
        self.max_tool_rounds = max_tool_rounds
        self.stream_parser = stream_parser

    def run(
        self,
        state: ReactorState,
        user_input: str,
        on_tool_call=None,
        on_stream_chunk=None,
    ) -> ReactorState:
        state, effects = self.reactor.step(state, UserMessageReceived(user_input))
        llm_requests = 0

        while effects:
            effect = effects.pop(0)

            if isinstance(effect, RequestLlm):
                if llm_requests >= self.max_tool_rounds:
                    return self._max_round_state(state)
                llm_requests += 1
                logger.info(f"[Loop 第 {llm_requests} 轮] 发送请求，messages 数: {len(effect.payload['messages'])}")
                try:
                    resp = self.llm_client.request(
                        effect.payload,
                        stream=effect.stream,
                        timeout=self.request_timeout,
                    )
                except urllib.error.HTTPError as exc:
                    return self._http_error_state(state, exc)
                except urllib.error.URLError as exc:
                    return self._url_error_state(state, exc)
                except Exception as exc:
                    logger.error(f"未知错误: {traceback.format_exc()}")
                    return self._error_state(state, f"❌ 请求异常: {exc}", "request_error")

                if effect.stream:
                    try:
                        text = self.stream_parser(resp, on_stream_chunk) if self.stream_parser else ""
                    except Exception as exc:
                        logger.error(f"流式响应解析失败: {exc}")
                        return self._error_state(state, f"❌ 请求异常: {exc}", "stream_error")
                    return self._final_state(state, text)

                assistant_message = resp["choices"][0]["message"]
                state, effects = self.reactor.step(state, LlmResponseReceived(assistant_message))
                continue

            if isinstance(effect, ExecuteTools):
                results = []
                for validated in effect.calls:
                    logger.info(f"  → 工具调用: {validated.name}({validated.args})")
                    if on_tool_call:
                        on_tool_call(validated.name, validated.args)
                    tool_result = self.tool_executor.execute(validated.name, validated.args)
                    logger.info(f"  ← 工具结果: {tool_result[:100]}...")
                    results.append({
                        "tool_call_id": validated.call_id,
                        "content": tool_result,
                    })
                state, effects = self.reactor.step(state, ToolExecutionCompleted(results))
                continue

            raise TypeError(f"Unsupported reactor effect: {type(effect).__name__}")

        return state

    def _max_round_state(self, state: ReactorState) -> ReactorState:
        logger.warning(f"超出最大工具调用轮数 ({self.max_tool_rounds})")
        return self._final_state(
            state,
            "抱歉，处理您的请求花费的步骤过多，请换个说法再试一次。",
            "max_tool_rounds",
        )

    def _http_error_state(self, state: ReactorState, exc: urllib.error.HTTPError) -> ReactorState:
        err = exc.read().decode("utf-8", errors="replace") if exc else ""
        logger.error(f"HTTP 错误 {exc.code}: {err}")
        return self._final_state(
            state,
            f"❌ API 请求失败 (HTTP {exc.code}): {exc.reason}\n{err}",
            "http_error",
        )

    def _url_error_state(self, state: ReactorState, exc: urllib.error.URLError) -> ReactorState:
        logger.error(f"网络错误: {exc.reason}")
        return self._final_state(state, f"❌ 无法连接到 AI 服务: {exc.reason}", "network_error")

    def _error_state(self, state: ReactorState, response: str, reason: str) -> ReactorState:
        return self._final_state(state, response, reason)

    def _final_state(self, state: ReactorState, response: str, reason: str = "final") -> ReactorState:
        from dataclasses import replace

        return replace(state, final_response=response, stop_reason=reason)
