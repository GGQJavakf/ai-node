import json
import urllib.error
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

import _path  # noqa: F401
from ai_todo_assistant.infrastructure.llm.clients import (
    CodexAppServerClient,
    CodexCliClient,
    OpenAICompatibleClient,
    build_llm_client,
)


class TestLLMClientFactory(unittest.TestCase):
    def test_builds_openai_compatible_client_by_default(self):
        client = build_llm_client({
            "api_key": "test-key",
            "api_base": "https://example.test/v1",
            "model": "test-model",
        })

        self.assertIsInstance(client, OpenAICompatibleClient)
        self.assertTrue(client.is_configured())
        self.assertEqual(client.api_base, "https://example.test/v1/chat/completions")

    def test_builds_codex_cli_client_without_api_key(self):
        client = build_llm_client({
            "auth_mode": "codex_cli",
            "model": "gpt-5.5",
            "codex_command": "codex",
        })

        self.assertIsInstance(client, CodexAppServerClient)
        self.assertEqual(client.model, "gpt-5.5")


class TestCodexAppServerClient(unittest.TestCase):
    @patch("ai_todo_assistant.infrastructure.llm.clients.shutil.which", return_value="C:\\bin\\codex.exe")
    def test_is_configured_uses_codex_command_presence(self, _which):
        client = CodexAppServerClient({"codex_command": "codex"})

        self.assertTrue(client.is_configured())

    @patch("ai_todo_assistant.infrastructure.llm.clients.CodexCliClient.request")
    def test_can_disable_app_server_and_use_exec_client(self, request):
        request.return_value = {"choices": [{"message": {"content": "ok"}}]}
        client = CodexAppServerClient({
            "codex_command": "codex",
            "codex_use_app_server": False,
        })

        response = client.request({"messages": []})

        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        request.assert_called_once()


class TestOpenAICompatibleClient(unittest.TestCase):
    def _http_error(self, code):
        return urllib.error.HTTPError(
            url="https://example.test/v1/chat/completions",
            code=code,
            msg="error",
            hdrs={},
            fp=BytesIO(b'{"error":"failed"}'),
        )

    @patch("ai_todo_assistant.infrastructure.llm.clients.time.sleep")
    @patch("ai_todo_assistant.infrastructure.llm.clients.urllib.request.urlopen")
    def test_retries_retryable_http_errors(self, urlopen, sleep):
        client = OpenAICompatibleClient({
            "api_key": "test",
            "api_base": "https://example.test/v1",
            "api_retry_limit": 2,
            "api_retry_backoff": 0,
        })
        success = Mock()
        success.read.return_value = json.dumps({
            "choices": [{"message": {"content": "ok"}}],
        }).encode("utf-8")
        urlopen.side_effect = [self._http_error(500), success]

        response = client.request({"messages": []})

        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    @patch("ai_todo_assistant.infrastructure.llm.clients.urllib.request.urlopen")
    def test_does_not_retry_non_retryable_http_errors(self, urlopen):
        client = OpenAICompatibleClient({
            "api_key": "test",
            "api_base": "https://example.test/v1",
            "api_retry_limit": 2,
            "api_retry_backoff": 0,
        })
        urlopen.side_effect = self._http_error(401)

        with self.assertRaises(urllib.error.HTTPError):
            client.request({"messages": []})

        self.assertEqual(urlopen.call_count, 1)


class TestCodexCliClient(unittest.TestCase):
    @patch("ai_todo_assistant.infrastructure.llm.clients.shutil.which", return_value="C:\\bin\\codex.exe")
    def test_is_configured_uses_codex_command_presence(self, _which):
        client = CodexCliClient({"codex_command": "codex"})

        self.assertTrue(client.is_configured())

    @patch("ai_todo_assistant.infrastructure.llm.clients.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.llm.clients.shutil.which", return_value="C:\\bin\\codex.exe")
    def test_request_converts_final_text_to_chat_completion_shape(self, _which, run):
        run.return_value = Mock(returncode=0, stdout='{"content":"好的，已记录。"}', stderr="")
        client = CodexCliClient({"codex_command": "codex", "model": "gpt-5.5"})

        response = client.request({
            "messages": [{"role": "user", "content": "提醒我明天买菜"}],
            "tools": [],
        })

        self.assertEqual(response["choices"][0]["message"]["content"], "好的，已记录。")
        command = run.call_args.args[0]
        self.assertIn("codex", command[0].lower())
        self.assertIn("exec", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--output-schema", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)

    @patch("ai_todo_assistant.infrastructure.llm.clients.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.llm.clients.shutil.which", return_value="C:\\bin\\codex.exe")
    def test_request_reads_last_json_line_when_stdout_has_logs(self, _which, run):
        run.return_value = Mock(
            returncode=0,
            stdout='SUCCESS: cleanup log\n{"content":"Codex调用成功。","tool_calls":[]}',
            stderr="",
        )
        client = CodexCliClient({"codex_command": "codex", "model": "gpt-5.5"})

        response = client.request({"messages": [], "tools": []})

        self.assertEqual(response["choices"][0]["message"]["content"], "Codex调用成功。")

    @patch("ai_todo_assistant.infrastructure.llm.clients.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.llm.clients.shutil.which", return_value="C:\\bin\\codex.exe")
    def test_request_converts_tool_call_to_chat_completion_shape(self, _which, run):
        run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({
                "tool_calls": [{
                    "id": "call_1",
                    "name": "add_todo",
                    "arguments": {"title": "买菜"}
                }]
            }),
            stderr="",
        )
        client = CodexCliClient({"codex_command": "codex", "model": "gpt-5.5"})

        response = client.request({
            "messages": [{"role": "user", "content": "提醒我买菜"}],
            "tools": [{"type": "function", "function": {"name": "add_todo"}}],
        })

        message = response["choices"][0]["message"]
        self.assertIsNone(message["content"])
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "add_todo")
        self.assertEqual(
            json.loads(message["tool_calls"][0]["function"]["arguments"]),
            {"title": "买菜"},
        )

    @patch("ai_todo_assistant.infrastructure.llm.clients.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.llm.clients.shutil.which", return_value="C:\\bin\\codex.exe")
    def test_request_accepts_codex_schema_arguments_json(self, _which, run):
        run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({
                "content": None,
                "tool_calls": [{
                    "name": "add_todo",
                    "arguments_json": "{\"title\":\"买菜\"}"
                }]
            }),
            stderr="",
        )
        client = CodexCliClient({"codex_command": "codex", "model": "gpt-5.5"})

        response = client.request({
            "messages": [{"role": "user", "content": "提醒我买菜"}],
            "tools": [{"type": "function", "function": {"name": "add_todo"}}],
        })

        arguments = response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        self.assertEqual(json.loads(arguments), {"title": "买菜"})

    @patch("ai_todo_assistant.infrastructure.llm.clients.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.llm.clients.shutil.which", return_value="C:\\bin\\codex.exe")
    def test_request_raises_clear_error_when_codex_fails(self, _which, run):
        run.return_value = Mock(returncode=1, stdout="", stderr="not logged in")
        client = CodexCliClient({"codex_command": "codex"})

        with self.assertRaises(RuntimeError) as ctx:
            client.request({"messages": []})

        self.assertIn("not logged in", str(ctx.exception))

    @patch("ai_todo_assistant.infrastructure.llm.clients.shutil.which", return_value="C:\\bin\\codex.cmd")
    def test_base_command_uses_resolved_codex_directly(self, _which):
        client = CodexCliClient({"codex_command": "codex"})

        self.assertEqual(client._base_command(), ["C:\\bin\\codex.cmd"])


if __name__ == "__main__":
    unittest.main()
