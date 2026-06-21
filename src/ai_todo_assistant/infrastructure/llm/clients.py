"""LLM 客户端适配层。"""
import atexit
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.request


DEFAULT_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
CODEX_RESPONSE_SCHEMA = {
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
        self.retry_limit = int(config.get("api_retry_limit", 2))
        self.retry_backoff = float(config.get("api_retry_backoff", 1.0))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def request(self, payload: dict, stream: bool = False, timeout: int = 30):
        req = urllib.request.Request(
            self.api_base,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")

        resp = self._urlopen_with_retry(req, timeout=timeout)
        if stream:
            return resp
        return json.loads(resp.read().decode("utf-8"))

    def _urlopen_with_retry(self, req, timeout: int):
        retryable_status = {429, 500, 502, 503, 504}
        for attempt in range(self.retry_limit + 1):
            try:
                return urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as exc:
                if exc.code not in retryable_status or attempt >= self.retry_limit:
                    raise
                time.sleep(self.retry_backoff * (attempt + 1))
            except urllib.error.URLError:
                if attempt >= self.retry_limit:
                    raise
                time.sleep(self.retry_backoff * (attempt + 1))


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
        self.retry_limit = int(config.get("codex_retry_limit", 1))
        self.request_timeout = int(config.get("codex_request_timeout", self.timeout))
        self.ignore_user_config = _as_bool(config.get("codex_ignore_user_config", True))
        self.ignore_rules = _as_bool(config.get("codex_ignore_rules", True))

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
            if self.ignore_user_config:
                args.append("--ignore-user-config")
            if self.ignore_rules:
                args.append("--ignore-rules")
            if self.model:
                args.extend(["--model", self.model])
            if self.cwd:
                args.extend(["--cd", self.cwd])
            try:
                effective_timeout = int(timeout or self.request_timeout or self.timeout)
                last_error: Exception | None = None

                for attempt in range(self.retry_limit + 1):
                    use_stdin = len(prompt) > 4000 or attempt > 0
                    run_args = self._build_prompt_command(args, prompt, use_stdin=use_stdin)
                    try:
                        proc = subprocess.run(
                            run_args,
                            input=prompt if use_stdin else None,
                            text=True,
                            capture_output=True,
                            timeout=effective_timeout,
                            encoding="utf-8",
                            errors="replace",
                        )
                    except subprocess.TimeoutExpired as exc:
                        last_error = exc
                        if attempt >= self.retry_limit:
                            raise RuntimeError(
                                f"Codex CLI 调用超时（{effective_timeout}s）。已重试 {self.retry_limit} 次，建议增大 AI_CODEX_TIMEOUT/AI_CODEX_REQUEST_TIMEOUT，或改用网络可达更稳定的网络环境。"
                            ) from exc
                        continue
                    except OSError as exc:
                        raise RuntimeError(f"Codex CLI 启动失败: {exc}") from exc

                    if proc.returncode != 0:
                        detail = (proc.stderr or proc.stdout or "").strip()
                        if attempt < self.retry_limit and len(detail) == 0:
                            continue
                        raise RuntimeError(f"Codex CLI 调用失败: {detail}")

                    return self._to_chat_completion(proc.stdout)

                if last_error is not None:
                    raise last_error
            except OSError as exc:
                raise RuntimeError(f"Codex CLI 启动失败: {exc}") from exc
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

    def _build_prompt_command(
        self, base_args: list[str], prompt: str, use_stdin: bool = False
    ) -> list[str]:
        run_args = base_args[:]
        if use_stdin:
            run_args.append("-")
            return run_args
        run_args.append(prompt)
        return run_args

    def _base_command(self) -> list[str]:
        resolved = shutil.which(self.command) or self.command
        if os.name == "nt" and resolved.lower().endswith(".cmd"):
            base_dir = os.path.dirname(resolved)
            codex_js = os.path.join(base_dir, "node_modules", "@openai", "codex", "bin", "codex.js")
            if os.path.exists(codex_js):
                bundled_node = os.path.join(base_dir, "node.exe")
                node = bundled_node if os.path.exists(bundled_node) else shutil.which("node") or "node"
                return [node, codex_js]
        return [resolved]

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
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(CODEX_RESPONSE_SCHEMA, f, ensure_ascii=False)
            return f.name

    def _extract_json_text(self, stdout: str) -> str:
        text = stdout.strip()
        for line in reversed(text.splitlines()):
            candidate = line.strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                return candidate
        return text


class CodexAppServerClient:
    """优先通过 Codex app-server 复用本机登录态，失败时回退到 codex exec。"""

    supports_stream = False

    def __init__(self, config: dict):
        self.exec_client = CodexCliClient(config)
        self.command = self.exec_client.command
        self.model = self.exec_client.model
        self.cwd = self.exec_client.cwd
        self.timeout = int(config.get("codex_app_server_timeout", config.get("codex_request_timeout", 240)))
        self.start_timeout = int(config.get("codex_app_server_start_timeout", 45))
        self.use_app_server = _as_bool(config.get("codex_use_app_server", True))
        self.fallback_to_exec = _as_bool(config.get("codex_app_server_fallback_to_exec", True))
        project_root = config.get("project_root") or self.cwd
        default_home = os.path.join(project_root, "data", "codex_home")
        configured_home = config.get("codex_home")
        self.managed_codex_home = not configured_home or configured_home == "data/codex_home"
        if configured_home and not os.path.isabs(configured_home):
            configured_home = os.path.join(project_root, configured_home)
        self.codex_home = os.path.abspath(configured_home or default_home)
        self.source_codex_home = os.path.abspath(
            config.get("codex_source_home")
            or os.environ.get("CODEX_HOME")
            or os.path.join(os.path.expanduser("~"), ".codex")
        )
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._messages: queue.Queue[dict] = queue.Queue()
        self._request_id = 0
        self._thread_id: str | None = None
        self._lock = threading.Lock()
        self._startup_error: str | None = None
        atexit.register(self.close)

    def is_configured(self) -> bool:
        return self.exec_client.is_configured()

    def request(self, payload: dict, stream: bool = False, timeout: int | None = None):
        if not self.use_app_server:
            return self.exec_client.request(payload, stream=stream, timeout=timeout)
        try:
            return self._request_app_server(payload, int(timeout or self.timeout))
        except Exception as exc:
            if not self.fallback_to_exec:
                raise
            self.close()
            try:
                return self.exec_client.request(payload, stream=stream, timeout=timeout)
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Codex app-server 调用失败: {exc}; fallback codex exec 也失败: {fallback_exc}"
                ) from fallback_exc

    def close(self):
        proc = self._proc
        self._proc = None
        self._thread_id = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def _request_app_server(self, payload: dict, timeout: int):
        with self._lock:
            self._ensure_started()
            if not self._thread_id:
                self._start_thread()
            turn_id = self._start_turn(payload)
            text = self._wait_turn_completed(turn_id, timeout)
            return self.exec_client._to_chat_completion(text)

    def _ensure_started(self):
        if self._proc and self._proc.poll() is None:
            return
        self._prepare_isolated_codex_home()
        env = os.environ.copy()
        env["CODEX_HOME"] = self.codex_home
        env.pop("OPENAI_API_KEY", None)
        env.pop("CODEX_API_KEY", None)
        args = self.exec_client._base_command() + ["app-server", "--listen", "stdio://"]
        try:
            self._proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                cwd=self.cwd,
            )
        except OSError as exc:
            raise RuntimeError(f"Codex app-server 启动失败: {exc}") from exc
        self._messages = queue.Queue()
        self._startup_error = None
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        request_id = self._send("initialize", {
            "clientInfo": {"name": "ai-todo-assistant", "version": "0"},
            "capabilities": {
                "optOutNotificationMethods": [
                    "item/agentMessage/delta",
                    "mcpServer/startupStatus/updated",
                ]
            },
        })
        self._wait_response(request_id, self.start_timeout)

    def _prepare_isolated_codex_home(self):
        os.makedirs(self.codex_home, exist_ok=True)
        if self.managed_codex_home:
            self._reset_managed_codex_home()
        for filename in ("auth.json",):
            src = os.path.join(self.source_codex_home, filename)
            dst = os.path.join(self.codex_home, filename)
            if os.path.exists(src):
                shutil.copy2(src, dst)
        src_accounts = os.path.join(self.source_codex_home, "accounts")
        dst_accounts = os.path.join(self.codex_home, "accounts")
        if os.path.isdir(src_accounts):
            shutil.copytree(src_accounts, dst_accounts, dirs_exist_ok=True)
        if not os.path.exists(os.path.join(self.codex_home, "auth.json")) and not os.path.isdir(dst_accounts):
            raise RuntimeError(
                f"未找到 Codex 登录文件，请先运行 codex login。检查路径: {self.source_codex_home}"
            )

    def _reset_managed_codex_home(self):
        source = os.path.abspath(self.source_codex_home)
        target = os.path.abspath(self.codex_home)
        if os.path.normcase(source) == os.path.normcase(target):
            return
        for name in os.listdir(target):
            if name in {"auth.json", "accounts"}:
                continue
            path = os.path.join(target, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _start_thread(self):
        request_id = self._send("thread/start", {
            "cwd": self.cwd,
            "model": self.model,
            "ephemeral": True,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "baseInstructions": "你是待办事项应用的结构化 JSON 后端。",
            "developerInstructions": "只作为待办事项 Agent 的结构化 JSON 后端，不要调用任何 Codex 原生工具。",
            "config": {
                "features": {"plugins": False},
                "mcp_servers": {},
            },
        })
        response = self._wait_response(request_id, self.start_timeout)
        result = response.get("result") or {}
        self._thread_id = (result.get("thread") or {}).get("id") or result.get("threadId")
        if not self._thread_id:
            raise RuntimeError(f"Codex app-server 未返回 thread id: {response}")

    def _start_turn(self, payload: dict) -> str:
        assert self._thread_id is not None
        prompt = self.exec_client._build_prompt(payload)
        request_id = self._send("turn/start", {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": prompt}],
            "model": self.model,
            "cwd": self.cwd,
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
            "outputSchema": CODEX_RESPONSE_SCHEMA,
        })
        response = self._wait_response(request_id, self.start_timeout)
        turn = (response.get("result") or {}).get("turn") or {}
        turn_id = turn.get("id")
        if not turn_id:
            raise RuntimeError(f"Codex app-server 未返回 turn id: {response}")
        return turn_id

    def _wait_turn_completed(self, turn_id: str, timeout: int) -> str:
        deadline = time.time() + timeout
        last_error = None
        final_text = ""
        while time.time() < deadline:
            self._check_process()
            try:
                message = self._messages.get(timeout=1)
            except queue.Empty:
                continue
            method = message.get("method")
            params = message.get("params") or {}
            if params.get("turnId") not in (None, turn_id):
                continue
            if method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage":
                    final_text = item.get("text") or final_text
            elif method == "error":
                error = params.get("error") or {}
                last_error = error.get("message") or str(error)
                if not params.get("willRetry", False):
                    raise RuntimeError(f"Codex app-server 返回错误: {last_error}")
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if turn.get("status") == "failed":
                    error = turn.get("error") or {}
                    raise RuntimeError(f"Codex app-server turn 失败: {error.get('message') or error}")
                if final_text:
                    return final_text
                raise RuntimeError("Codex app-server turn 已完成，但未收到 assistant JSON 内容")
        detail = f"，最后错误: {last_error}" if last_error else ""
        raise RuntimeError(f"Codex app-server 调用超时（{timeout}s）{detail}")

    def _send(self, method: str, params: dict | None = None) -> int:
        self._check_process()
        assert self._proc is not None and self._proc.stdin is not None
        self._request_id += 1
        message = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        return self._request_id

    def _wait_response(self, request_id: int, timeout: int) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_process()
            try:
                message = self._messages.get(timeout=1)
            except queue.Empty:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"Codex app-server 请求失败: {message['error']}")
            return message
        raise RuntimeError(f"Codex app-server 请求 {request_id} 超时（{timeout}s）")

    def _check_process(self):
        if not self._proc:
            return
        code = self._proc.poll()
        if code is not None:
            detail = f": {self._startup_error}" if self._startup_error else ""
            raise RuntimeError(f"Codex app-server 已退出，exit={code}{detail}")

    def _read_stdout(self):
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            try:
                self._messages.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _read_stderr(self):
        assert self._proc is not None and self._proc.stderr is not None
        for line in self._proc.stderr:
            if line.strip():
                self._startup_error = line.strip()


def build_llm_client(config: dict):
    auth_mode = (config.get("auth_mode") or "openai_api").lower()
    if auth_mode == "codex_cli":
        return CodexAppServerClient(config)
    return OpenAICompatibleClient(config)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


