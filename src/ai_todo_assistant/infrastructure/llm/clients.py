"""LLM 客户端适配层。"""
import json
import os
import shutil
import subprocess
import tempfile
import uuid
import urllib.request


DEFAULT_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


def _chat_completions_url(api_base: str) -> str:
    if api_base.endswith("/chat/completions"):
        return api_base
    return api_base.rstrip("/") + "/chat/completions"


class OpenAICompatibleClient:
    """OpenAI 兼容 Chat Completions HTTP 客户端。"""

    supports_stream = True

    def __init__(self, config: dict):
        self.api_key = config.get("api_key", "")
        self.api_base = _chat_completions_url(config.get("api_base", DEFAULT_CHAT_COMPLETIONS_URL))
        self.model = config.get("model", "gpt-4o-mini")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def request(self, payload: dict, stream: bool = False, timeout: int = 30):
        req = urllib.request.Request(
            self.api_base,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")

        resp = urllib.request.urlopen(req, timeout=timeout)
        if stream:
            return resp
        return json.loads(resp.read().decode("utf-8"))


class CodexCliClient:
    """通过本机已登录的 Codex CLI 调用 ChatGPT/Codex 身份。"""

    supports_stream = False

    def __init__(self, config: dict):
        self.command = config.get("codex_command", "codex")
        self.model = config.get("model", "gpt-5.5")
        self.cwd = config.get("codex_cwd") or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
        )
        self.timeout = int(config.get("codex_timeout", 120))

    def is_configured(self) -> bool:
        return bool(shutil.which(self.command))

    def request(self, payload: dict, stream: bool = False, timeout: int | None = None):
        schema_path = self._write_response_schema()
        try:
            prompt = self._build_prompt(payload)
            args = self._base_command() + [
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "--output-schema",
                schema_path,
            ]
            if self.model:
                args.extend(["--model", self.model])
            if self.cwd:
                args.extend(["--cd", self.cwd])
            args.append("-")

            try:
                proc = subprocess.run(
                    args,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=timeout or self.timeout,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                raise RuntimeError(f"Codex CLI 启动失败: {exc}") from exc
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                raise RuntimeError(f"Codex CLI 调用失败: {detail}")

            return self._to_chat_completion(proc.stdout)
        finally:
            try:
                os.remove(schema_path)
            except OSError:
                pass

    def _build_prompt(self, payload: dict) -> str:
        return (
            "你是待办事项 Agent 的 LLM 后端。请根据 messages 和 tools 决定下一步。\n"
            "必须只返回符合 JSON Schema 的 JSON：\n"
            "- 如果需要调用工具，返回 content=null，并在 tool_calls 中给出 name 和 arguments_json。\n"
            "- arguments_json 必须是一个 JSON object 的字符串，例如 \"{\\\"title\\\":\\\"买菜\\\"}\"。\n"
            "- 如果不需要调用工具，返回 content 字符串，tool_calls 为空数组。\n"
            "- 不要输出 markdown、解释、代码块或额外字段。\n\n"
            f"messages:\n{json.dumps(payload.get('messages', []), ensure_ascii=False)}\n\n"
            f"tools:\n{json.dumps(payload.get('tools', []), ensure_ascii=False)}\n"
        )

    def _base_command(self) -> list[str]:
        if os.name == "nt":
            return ["cmd", "/c", self.command]
        return [self.command]

    def _to_chat_completion(self, stdout: str) -> dict:
        text = self._extract_json_text(stdout)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Codex CLI 返回非 JSON 内容: {text}") from exc

        tool_calls = []
        for tool_call in data.get("tool_calls") or []:
            call_id = tool_call.get("id") or f"call_{uuid.uuid4().hex[:12]}"
            arguments = tool_call.get("arguments")
            if arguments is None:
                arguments = tool_call.get("arguments_json") or "{}"
            # Codex Output Schema 只能保证 arguments_json 是字符串，不能保证其内容是合法参数。
            # 保留原始字符串交给 AgentCore 的本地校验处理，校验失败时可触发重试。
            if isinstance(arguments, str):
                argument_text = arguments
            else:
                argument_text = json.dumps(arguments, ensure_ascii=False)
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": argument_text,
                },
            })

        content = data.get("content")
        if not tool_calls and content is None:
            content = "（无回复）"

        message = {
            "role": "assistant",
            "content": content,
        }
        finish_reason = "stop"
        if tool_calls:
            message["tool_calls"] = tool_calls
            finish_reason = "tool_calls"

        return {
            "choices": [{
                "message": message,
                "finish_reason": finish_reason,
            }]
        }

    def _write_response_schema(self) -> str:
        schema = {
            "type": "object",
            "properties": {
                "content": {"type": ["string", "null"]},
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "arguments_json": {"type": "string"},
                        },
                        "required": ["name", "arguments_json"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["content", "tool_calls"],
            "additionalProperties": False,
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False)
            return f.name

    def _extract_json_text(self, stdout: str) -> str:
        text = stdout.strip()
        for line in reversed(text.splitlines()):
            candidate = line.strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                return candidate
        return text


def build_llm_client(config: dict):
    auth_mode = (config.get("auth_mode") or "openai_api").lower()
    if auth_mode == "codex_cli":
        return CodexCliClient(config)
    return OpenAICompatibleClient(config)


