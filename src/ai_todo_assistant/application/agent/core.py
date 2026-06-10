"""Agent 推理循环核心。"""
import json
import logging
import traceback
import urllib.error
from datetime import datetime

from ai_todo_assistant.application.agent.tool_definitions import TOOL_DEFINITIONS
from ai_todo_assistant.application.agent.tool_executor import ToolExecutor
from ai_todo_assistant.application.agent.tool_validation import ToolValidationError, validate_tool_calls
from ai_todo_assistant.infrastructure.llm.clients import build_llm_client
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager

logger = logging.getLogger("AgentCore")
MAX_TOOL_ROUNDS = 6


class AgentCore:
    """
    Agent 推理循环。

    负责构建上下文、调用 LLM、执行 tool_calls，并把工具结果送回模型。
    领域规则不写在这里，避免 Agent 层和数据层互相污染。
    """

    def __init__(self, manager: TodoManager, config: dict):
        self.manager = manager
        self.executor = ToolExecutor(manager)
        self.api_key = config.get("api_key", "")
        self.api_base = config.get("api_base", "https://api.openai.com/v1/chat/completions")
        self.model = config.get("model", "gpt-4o-mini")
        self.auth_mode = config.get("auth_mode", "openai_api")
        # Codex CLI 模式通常比普通 HTTP API 慢，超时时间应尊重配置。
        self.request_timeout = int(config.get("request_timeout") or config.get("codex_timeout", 30))
        # 本地参数校验失败时，只让模型重新生成工具参数，不执行任何本地工具。
        self.validation_retry_limit = int(config.get("validation_retry_limit", 3))
        self.llm_client = build_llm_client(config)

        if not self.api_base.endswith("/chat/completions"):
            self.api_base = self.api_base.rstrip("/") + "/chat/completions"

        self._history: list[dict] = []

    def is_configured(self) -> bool:
        return self.llm_client.is_configured()

    def clear_history(self):
        self._history.clear()
        logger.info("对话历史已清除")

    def _build_system_prompt(self) -> str:
        now = datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday_str = weekdays[now.weekday()]

        todos = self.manager.get_all()
        if todos:
            todo_summary = "\n".join(
                f"  - [{('✓' if t.completed else '○')}] {t.title}"
                f"{(' | 截止:' + t.end_time) if t.end_time else ''}"
                f" (ID:{t.id})"
                for t in todos
            )
        else:
            todo_summary = "  （暂无待办事项）"

        return f"""你是一个智能、得力的 AI 待办管家助手。

【当前时间】{now.strftime("%Y年%m月%d日 %H:%M")}，{weekday_str}
【当前待办事项】
{todo_summary}

【工作原则】
1. 你有一组工具可以操作待办数据，需要时直接调用，不要询问"要我帮你...吗"。
2. 如果用户说"最近的任务"、"刚才那个"，请结合上下文推断具体是哪条。
3. 如果需要知道任务 ID 才能操作，先调用 list_todos 获取，再调用对应工具。
4. 用温暖，自然的语气回复，像一个贴心的生活助手。
5. 完成工具调用后，给用户清晰的操作反馈。"""

    def _call_llm(self, messages: list[dict], stream: bool = False) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "temperature": 0.3,
            "stream": stream,
        }
        return self.llm_client.request(payload, stream=stream, timeout=self.request_timeout)

    def _parse_streaming_response(self, resp, on_stream_chunk=None):
        full_content = ""
        try:
            for line in resp:
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                            if on_stream_chunk:
                                on_stream_chunk(content)
                    except json.JSONDecodeError:
                        continue
                elif line.startswith("{"):
                    try:
                        data = json.loads(line)
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if content:
                            full_content += content
                            if on_stream_chunk:
                                on_stream_chunk(content)
                    except json.JSONDecodeError:
                        continue
        finally:
            resp.close()
        return full_content

    def chat(self, user_input: str, on_tool_call=None, stream: bool = False, on_stream_chunk=None) -> str:
        if not self.is_configured():
            if self.auth_mode == "codex_cli":
                return "❌ 未找到 Codex CLI，请先安装并运行 `codex login` 完成登录"
            return "❌ 未配置 API Key，请检查 config/settings.json"

        effective_stream = stream and self.llm_client.supports_stream
        self._history.append({"role": "user", "content": user_input})

        system_msg = {"role": "system", "content": self._build_system_prompt()}
        messages = [system_msg] + self._history[-20:]
        validation_failures = 0

        for round_num in range(MAX_TOOL_ROUNDS):
            logger.info(f"[Loop 第 {round_num + 1} 轮] 发送请求，messages 数: {len(messages)}")
            try:
                resp = self._call_llm(messages, stream=effective_stream)
            except urllib.error.HTTPError as e:
                err = e.read().decode("utf-8", errors="replace") if e else ""
                logger.error(f"HTTP 错误 {e.code}: {err}")
                return f"❌ API 请求失败 (HTTP {e.code}): {e.reason}\n{err}"
            except urllib.error.URLError as e:
                logger.error(f"网络错误: {e.reason}")
                return f"❌ 无法连接到 AI 服务: {e.reason}"
            except Exception as e:
                logger.error(f"未知错误: {traceback.format_exc()}")
                return f"❌ 请求异常: {e}"

            if effective_stream:
                try:
                    return self._parse_streaming_response(resp, on_stream_chunk)
                except Exception as e:
                    logger.error(f"流式响应解析失败: {e}")
                    return self.chat(user_input, on_tool_call, stream=False)

            assistant_message = resp["choices"][0]["message"]
            tool_calls = assistant_message.get("tool_calls")

            if not tool_calls:
                final_text = assistant_message.get("content", "（无回复）")
                self._history.append({"role": "assistant", "content": final_text})
                logger.info(f"[Loop 结束] 第 {round_num + 1} 轮，无工具调用，返回文本")
                return final_text

            try:
                validated_calls = validate_tool_calls(tool_calls)
            except ToolValidationError as e:
                validation_failures += 1
                logger.warning(f"工具参数本地校验失败 ({validation_failures}): {e}")
                if validation_failures > self.validation_retry_limit:
                    return (
                        f"❌ AI 工具参数连续校验失败 {validation_failures} 次，"
                        f"已停止执行以避免错误操作。\n最后一次错误: {e}"
                    )

                # 把失败原因明确反馈给模型，要求它只修正 tool_calls 参数后重试。
                messages.append(assistant_message)
                messages.append({
                    "role": "user",
                    "content": (
                        "你刚才返回的工具调用参数未通过本地校验，工具尚未执行。\n"
                        f"校验错误: {e}\n"
                        "请重新返回合法的 tool_calls；不要解释，不要输出普通文本。"
                    ),
                })
                continue

            messages.append(assistant_message)
            validation_failures = 0
            for validated in validated_calls:
                tool_call_id = validated.call_id
                tool_name = validated.name
                tool_args = validated.args
                logger.info(f"  → 工具调用: {tool_name}({tool_args})")
                if on_tool_call:
                    on_tool_call(tool_name, tool_args)

                tool_result = self.executor.execute(tool_name, tool_args)
                logger.info(f"  ← 工具结果: {tool_result[:100]}...")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_result,
                })

        logger.warning(f"超出最大工具调用轮数 ({MAX_TOOL_ROUNDS})")
        return "抱歉，处理您的请求花费的步骤过多，请换个说法再试一次。"

