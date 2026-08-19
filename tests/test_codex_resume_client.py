import subprocess
import unittest
from unittest.mock import Mock, patch

import _path  # noqa: F401
from ai_todo_assistant.infrastructure.connectors.codex_resume_client import CodexCliResumeClient


class TestCodexCliResumeClient(unittest.TestCase):
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which", return_value="C:\\bin\\codex.exe")
    def test_resume_thread_calls_codex_resume(self, _which, run):
        run.return_value = Mock(returncode=0, stdout="queued", stderr="")
        client = CodexCliResumeClient(
            {
                "codex_command": "codex",
                "codex_resume_timeout": 300,
                "project_root": "D:\\repo",
            }
        )

        outcome = client.resume_thread("thread-1", "继续执行")

        self.assertTrue(outcome.success)
        self.assertIn("queued", outcome.message)
        args = run.call_args.args[0]
        self.assertEqual(args, ["C:\\bin\\codex.exe", "exec", "resume", "--json", "thread-1", "-"])
        self.assertEqual(run.call_args.kwargs["input"], "继续执行")
        self.assertEqual(run.call_args.kwargs["timeout"], 300)
        self.assertIs(run.call_args.kwargs["shell"], False)

    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.os.path.isfile")
    def test_windows_batch_shim_prefers_native_codex_exe(self, isfile, which, run):
        which.return_value = "C:\\bin\\codex.cmd"
        isfile.side_effect = lambda path: path == "C:\\bin\\codex.exe"
        run.return_value = Mock(returncode=0, stdout="queued", stderr="")
        client = CodexCliResumeClient({"codex_command": "codex"})

        with patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.os.name", "nt"):
            outcome = client.resume_thread("019f74f7-f717-7c80-a871-c30331cfc1bb", "继续")

        self.assertTrue(outcome.success)
        self.assertEqual(
            run.call_args.args[0],
            ["C:\\bin\\codex.exe", "exec", "resume", "--json", "019f74f7-f717-7c80-a871-c30331cfc1bb", "-"],
        )

    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.os.path.isfile")
    def test_windows_batch_shim_uses_node_and_codex_js(self, isfile, which, run):
        batch = "C:\\bin\\codex.cmd"
        codex_js = "C:\\bin\\node_modules\\@openai\\codex\\bin\\codex.js"
        node = "C:\\runtime\\node.exe"
        which.side_effect = lambda command: batch if command == "codex" else node if command == "node" else None
        isfile.side_effect = lambda path: path in {codex_js, node}
        run.return_value = Mock(returncode=0, stdout="queued", stderr="")
        client = CodexCliResumeClient({"codex_command": "codex"})

        with patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.os.name", "nt"):
            outcome = client.resume_thread("thread_1.release:2", "继续")

        self.assertTrue(outcome.success)
        self.assertEqual(
            run.call_args.args[0],
            [node, codex_js, "exec", "resume", "--json", "thread_1.release:2", "-"],
        )

    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.os.path.isfile")
    def test_windows_batch_shim_rejects_batch_node_fallback(self, isfile, which, run):
        batch = "C:\\bin\\codex.cmd"
        codex_js = "C:\\bin\\node_modules\\@openai\\codex\\bin\\codex.js"
        which.side_effect = lambda command: batch if command == "codex" else "C:\\runtime\\node.cmd"
        isfile.side_effect = lambda path: path in {codex_js, "C:\\runtime\\node.cmd"}
        client = CodexCliResumeClient({"codex_command": "codex"})

        with patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.os.name", "nt"):
            outcome = client.resume_thread("thread-1", "继续")

        self.assertFalse(outcome.success)
        self.assertIn("command not found", outcome.message)
        run.assert_not_called()

    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.os.path.isfile", return_value=False)
    def test_windows_batch_shim_without_native_target_fails_closed(self, _isfile, which, run):
        which.side_effect = lambda command: "C:\\bin\\codex.bat" if command == "codex" else None
        client = CodexCliResumeClient({"codex_command": "codex"})

        with patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.os.name", "nt"):
            outcome = client.resume_thread("thread-1", "继续")

        self.assertFalse(outcome.success)
        self.assertIn("command not found", outcome.message)
        run.assert_not_called()

    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which")
    def test_report_thread_id_rejects_windows_batch_metacharacters(self, which, run):
        which.return_value = "C:\\bin\\codex.cmd"
        client = CodexCliResumeClient({"codex_command": "codex"})

        for metacharacter in "&|^":
            with self.subTest(metacharacter=metacharacter):
                outcome = client.resume_thread(f"thread-1{metacharacter}echo-injected", "继续")
                self.assertFalse(outcome.success)
                self.assertIn("invalid codex thread id", outcome.message)

        which.assert_not_called()
        run.assert_not_called()

    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which", return_value=None)
    def test_missing_codex_command_fails_closed(self, _which):
        client = CodexCliResumeClient({"codex_command": "missing-codex"})

        outcome = client.resume_thread("thread-1", "继续")

        self.assertFalse(outcome.success)
        self.assertIn("codex command not found", outcome.message)

    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which", return_value="codex")
    def test_non_zero_exit_fails_closed(self, _which, run):
        run.return_value = Mock(returncode=1, stdout="", stderr="not found")
        client = CodexCliResumeClient({"codex_command": "codex"})

        outcome = client.resume_thread("thread-1", "继续")

        self.assertFalse(outcome.success)
        self.assertIn("not found", outcome.message)

    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.subprocess.run")
    @patch("ai_todo_assistant.infrastructure.connectors.codex_resume_client.shutil.which", return_value="codex")
    def test_timeout_fails_closed(self, _which, run):
        run.side_effect = subprocess.TimeoutExpired(cmd="codex", timeout=5)
        client = CodexCliResumeClient({"codex_command": "codex", "codex_resume_timeout": 5})

        outcome = client.resume_thread("thread-1", "继续")

        self.assertFalse(outcome.success)
        self.assertIn("timeout", outcome.message)

    def test_disabled_config_fails_closed_without_command_lookup(self):
        client = CodexCliResumeClient({"codex_resume_enabled": False})

        outcome = client.resume_thread("thread-1", "继续")

        self.assertFalse(outcome.success)
        self.assertIn("disabled", outcome.message)


if __name__ == "__main__":
    unittest.main()
