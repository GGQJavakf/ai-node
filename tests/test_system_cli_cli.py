import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.infrastructure.connectors import CommandResult
from ai_todo_assistant.infrastructure.persistence import SQLiteWorkflowRepository
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager
from ai_todo_assistant.application.workflow import WorkItemService
from ai_todo_assistant.domain.workflow import EvidenceType
from ai_todo_assistant.presentation.cli import CommandCompleter, TodoCLI


class FakeRunner:
    def __init__(self, result):
        self.result = result

    def run(self, args, cwd=""):
        return self.result


class TestSystemCliCommand(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workflow_path = os.path.join(self.temp_dir.name, "workflow.db")
        self.cli = object.__new__(TodoCLI)
        self.cli.workflow_repository = SQLiteWorkflowRepository(self.workflow_path)
        self.cli.config = {
            "project_root": self.temp_dir.name,
            "storage_backend": "sqlite",
            "sqlite_path": self.workflow_path,
        }
        self.cli.manager = TodoManager(os.path.join(self.temp_dir.name, "todos.json"))
        self.cli.system_cli_runner = FakeRunner(CommandResult(["git"], self.temp_dir.name, 0, stdout=" M docs/a.md\n"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_system_list_shows_catalog(self):
        response = self.cli._handle_slash_command("/system list")

        self.assertIn("git.status", response)
        self.assertIn("git.branch", response)
        self.assertIn("openspec.list", response)
        self.assertIn("openspec.validate", response)
        self.assertIn("playbook.workspace_status", response)

    def test_system_policy_shows_allowed_roots(self):
        response = self.cli._handle_slash_command("/system policy")

        self.assertIn("read_only", response)
        self.assertIn(self.temp_dir.name, response)

    def test_system_run_executes_catalog_command(self):
        response = self.cli._handle_slash_command("/system run git.status")

        self.assertIn("[system_cli] git.status succeeded", response)
        self.assertIn(" M docs/a.md", response)

    def test_system_run_can_record_compact_evidence(self):
        item = WorkItemService(self.cli.workflow_repository).create_manual("验证系统 CLI 证据")

        response = self.cli._handle_slash_command(f"/system run git.status --evidence {item.id}")
        evidence = self.cli.workflow_repository.list_evidence(item.id)

        self.assertIn("[system_cli] git.status succeeded", response)
        self.assertIn("Evidence recorded", response)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].evidence_type, EvidenceType.COMMAND.value)
        self.assertEqual(evidence[0].source, "system-cli")
        self.assertEqual(evidence[0].command, "git status --short")
        self.assertEqual(evidence[0].output_excerpt, " M docs/a.md")
        self.assertTrue(evidence[0].success)

    def test_system_run_reuses_duplicate_evidence(self):
        item = WorkItemService(self.cli.workflow_repository).create_manual("避免重复证据")

        first = self.cli._handle_slash_command(f"/system run git.status --evidence {item.id}")
        second = self.cli._handle_slash_command(f"/system run git.status --evidence {item.id}")
        evidence = self.cli.workflow_repository.list_evidence(item.id)

        self.assertIn("Evidence recorded", first)
        self.assertIn("Evidence reused", second)
        self.assertEqual(len(evidence), 1)

    def test_system_run_rejects_unknown_command(self):
        response = self.cli._handle_slash_command("/system run git.push")

        self.assertIn("policy: denied", response)
        self.assertIn("unknown command", response)

    def test_system_run_rejects_outside_cwd(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)

        response = self.cli._handle_slash_command(f"/system run git.status --cwd {outside.name}")

        self.assertIn("policy: denied", response)
        self.assertIn("outside allowed roots", response)

    def test_help_system_includes_system_cli_without_primary_surface(self):
        help_text = self.cli._handle_slash_command("/help")
        system_help = self.cli._handle_slash_command("/help system")

        primary_section = help_text[: help_text.index("分类帮助")]
        self.assertNotIn("/system", primary_section)
        self.assertIn("/system list", system_help)
        self.assertIn("/system run <key>", system_help)
        self.assertIn("/system policy", system_help)

    def test_completion_includes_system_commands(self):
        commands = CommandCompleter().commands

        self.assertIn("/system list", commands)
        self.assertIn("/system run", commands)
        self.assertIn("/system policy", commands)


if __name__ == "__main__":
    unittest.main()
