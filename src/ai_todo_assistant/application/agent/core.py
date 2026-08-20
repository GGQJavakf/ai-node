"""Agent 推理循环核心。"""
import json
import logging
from datetime import datetime

from ai_todo_assistant.application.agent.tool_definitions import TOOL_DEFINITIONS
from ai_todo_assistant.application.agent.tool_executor import ToolExecutor
from ai_todo_assistant.application.memory import SessionMemory
from ai_todo_assistant.application.ports import TodoRepository
from ai_todo_assistant.application.reactor import AgentReactor, AgentRuntime, ReactorState
from ai_todo_assistant.infrastructure.llm.clients import build_llm_client

logger = logging.getLogger("AgentCore")
MAX_TOOL_ROUNDS = 6


class AgentCore:
    """
    Agent 推理循环。

    负责构建上下文、调用 LLM、执行 tool_calls，并把工具结果送回模型。
    领域规则不写在这里，避免 Agent 层和数据层互相污染。
    """

    def __init__(self, manager: TodoRepository, config: dict):
        self.manager = manager
        self.executor = ToolExecutor(manager, config)
        self.api_key = config.get("api_key", "")
        self.api_base = config.get("api_base", "https://api.openai.com/v1/chat/completions")
        self.model = config.get("model", "gpt-4o-mini")
        self.auth_mode = config.get("auth_mode", "openai_api")
        # 本机 CLI 模式通常比普通 HTTP API 慢，超时时间应尊重配置。
        self.request_timeout = int(
            config.get("request_timeout")
            or config.get("codex_request_timeout")
            or config.get("codex_timeout", 30)
        )
        # 本地参数校验失败时，只让模型重新生成工具参数，不执行任何本地工具。
        self.validation_retry_limit = int(config.get("validation_retry_limit", 3))
        self.memory = SessionMemory(max_messages=int(config.get("session_memory_limit", 20)))
        self.llm_client = build_llm_client(config)

        if not self.api_base.endswith("/chat/completions"):
            self.api_base = self.api_base.rstrip("/") + "/chat/completions"

    def is_configured(self) -> bool:
        return self.llm_client.is_configured()

    def clear_history(self):
        self.memory.clear()
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

        preferences = {}
        if hasattr(self.manager, "list_preferences"):
            preferences = self.manager.list_preferences()
        if preferences:
            preference_summary = "\n".join(f"  - {key}: {value}" for key, value in preferences.items())
        else:
            preference_summary = "  （暂无长期偏好）"

        return f"""你是一个智能、得力的 AI 待办管家助手。

【当前时间】{now.strftime("%Y年%m月%d日 %H:%M")}，{weekday_str}
【当前待办事项】
{todo_summary}
【长期偏好】
{preference_summary}

【工作原则】
1. 你有一组工具可以操作待办数据，需要时直接调用，不要询问"要我帮你...吗"。
2. 如果用户说"最近的任务"、"刚才那个"，请结合上下文推断具体是哪条。
3. 如果需要知道任务 ID 才能操作，先调用 list_todos 获取，再调用对应工具。
4. 当用户明确要求你记住长期偏好时，调用 remember_preference。
5. 你还能作为个人工作助手管理 WorkItem、Evidence、Codex 日报、Playbook/OpenSpec/Git 只读快照。
6. workflow 工具首版只读外部系统：不要声称已经写 Redmine/GitLab/MR、merge、closeout、登记工时或发布。
7. 建议动作和已执行事实必须区分；只有工具返回的结果才算已执行。
8. 用温暖，自然的语气回复，像一个贴心的生活助手。
9. 完成工具调用后，给用户清晰的操作反馈。"""

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
            return "❌ 未配置 API Key，请检查 config/settings.local.json"

        # Chat Completions 的流式 tool_calls 需要增量拼接参数；当前 Agent
        # 工具循环依赖完整 message.tool_calls，因此带工具时使用非流式请求。
        effective_stream = stream and self.llm_client.supports_stream and not TOOL_DEFINITIONS
        system_msg = {"role": "system", "content": self._build_system_prompt()}
        reactor = AgentReactor(
            model=self.model,
            tool_definitions=TOOL_DEFINITIONS,
            validation_retry_limit=self.validation_retry_limit,
        )
        runtime = AgentRuntime(
            reactor=reactor,
            llm_client=self.llm_client,
            tool_executor=self.executor,
            request_timeout=self.request_timeout,
            max_tool_rounds=MAX_TOOL_ROUNDS,
            stream_parser=self._parse_streaming_response,
        )
        final_state = runtime.run(
            ReactorState(
                system_message=system_msg,
                memory_messages=self.memory.snapshot(),
                stream=effective_stream,
            ),
            user_input,
            on_tool_call=on_tool_call,
            on_stream_chunk=on_stream_chunk,
        )
        final_text = final_state.final_response or "（无回复）"
        self.memory.add_user_message(user_input)
        if final_state.stop_reason == "final":
            self.memory.add_assistant_message(final_text)
        return final_text

