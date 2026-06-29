import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.system_cli import SystemCliService
from ai_todo_assistant.infrastructure.connectors import CommandResult


class FakeRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, args, cwd=""):
        self.calls.append((args, cwd))
        return self.result


class TestSystemCliService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_lists_read_only_catalog_commands(self):
        service = SystemCliService(config={"project_root": self.project_root})

        commands = service.list_commands()

        self.assertIn("git.branch", commands)
        self.assertIn("git.status", commands)
        self.assertIn("git.diff_stat", commands)
        self.assertIn("openspec.list", commands)
        self.assertEqual(commands["git.status"].risk_level, "read_only")
        self.assertEqual(commands["openspec.list"].risk_level, "read_only")

    def test_runs_openspec_list_with_fixed_argv(self):
        runner = FakeRunner(CommandResult(["openspec"], self.project_root, 0, stdout='{"changes":[]}\n'))
        service = SystemCliService(config={"project_root": self.project_root}, runner=runner)

        record = service.run("openspec.list", cwd=self.project_root)

        self.assertTrue(record.success)
        self.assertEqual(runner.calls, [(["openspec", "list", "--json"], self.project_root)])
        self.assertIn('"changes":[]', record.stdout_excerpt)

    def test_rejects_unknown_command_without_running_process(self):
        runner = FakeRunner(CommandResult(["never"], self.project_root, 0))
        service = SystemCliService(config={"project_root": self.project_root}, runner=runner)

        record = service.run("git.push", cwd=self.project_root)

        self.assertFalse(record.success)
        self.assertEqual(record.policy_decision, "denied")
        self.assertIn("unknown command", record.policy_reason)
        self.assertEqual(runner.calls, [])

    def test_rejects_cwd_outside_allowed_roots(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        runner = FakeRunner(CommandResult(["never"], outside.name, 0))
        service = SystemCliService(config={"project_root": self.project_root}, runner=runner)

        record = service.run("git.status", cwd=outside.name)

        self.assertFalse(record.success)
        self.assertEqual(record.policy_decision, "denied")
        self.assertIn("outside allowed roots", record.policy_reason)
        self.assertEqual(runner.calls, [])

    def test_returns_missing_command_record(self):
        runner = FakeRunner(CommandResult(["git"], self.project_root, 127, stderr="not found", missing=True))
        service = SystemCliService(config={"project_root": self.project_root}, runner=runner)

        record = service.run("git.status", cwd=self.project_root)

        self.assertFalse(record.success)
        self.assertTrue(record.missing)
        self.assertEqual(record.returncode, 127)
        self.assertIn("not found", record.stderr_excerpt)

    def test_redacts_secret_values_before_returning_excerpts(self):
        stdout = (
            "Authorization: Bearer sk-secret\n"
            "password=123456\n"
            "token=abc\n"
            '{"api_key":"json-secret"}\n'
            "Cookie: session=raw-cookie\n"
            "ok\n"
        )
        runner = FakeRunner(CommandResult(["git"], self.project_root, 0, stdout=stdout))
        service = SystemCliService(config={"project_root": self.project_root}, runner=runner)

        record = service.run("git.status", cwd=self.project_root)

        self.assertNotIn("sk-secret", record.stdout_excerpt)
        self.assertNotIn("123456", record.stdout_excerpt)
        self.assertNotIn("abc", record.stdout_excerpt)
        self.assertNotIn("json-secret", record.stdout_excerpt)
        self.assertNotIn("raw-cookie", record.stdout_excerpt)
        self.assertIn("[REDACTED]", record.stdout_excerpt)

    def test_truncates_long_output_with_marker(self):
        runner = FakeRunner(CommandResult(["git"], self.project_root, 0, stdout="x" * 5000))
        service = SystemCliService(
            config={
                "project_root": self.project_root,
                "system_cli_stdout_limit": 20,
                "system_cli_stderr_limit": 20,
            },
            runner=runner,
        )

        record = service.run("git.status", cwd=self.project_root)

        self.assertTrue(record.output_truncated)
        self.assertIn("[truncated", record.stdout_excerpt)
        self.assertLess(len(record.stdout_excerpt), 80)

    def test_format_tool_result_uses_compact_summary(self):
        runner = FakeRunner(CommandResult(["git"], self.project_root, 0, stdout=" M docs/a.md\n"))
        service = SystemCliService(config={"project_root": self.project_root}, runner=runner)

        text = service.format_for_tool(service.run("git.status", cwd=self.project_root))

        self.assertIn("[system_cli] git.status succeeded", text)
        self.assertIn("exit_code: 0", text)
        self.assertIn(" M docs/a.md", text)


if __name__ == "__main__":
    unittest.main()
