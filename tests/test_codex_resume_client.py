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
