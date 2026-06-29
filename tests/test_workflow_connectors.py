import json
import os
import unittest
from unittest.mock import Mock, patch

import _path  # noqa: F401
from ai_todo_assistant.infrastructure.connectors import (
    CommandResult,
    CommandRunner,
    GitConnector,
    OpenSpecConnector,
    PlaybookConnector,
)


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, args, cwd=""):
        self.calls.append((args, cwd))
        return self.results.pop(0)


class TestWorkflowConnectors(unittest.TestCase):
    def test_git_connector_parses_branch_dirty_status_and_diff_stat(self):
        connector = GitConnector(FakeRunner([
            CommandResult(["git"], "repo", 0, stdout="main\n"),
            CommandResult(["git"], "repo", 0, stdout=" M file.py\n"),
            CommandResult(["git"], "repo", 0, stdout=" file.py | 2 +-\n"),
        ]))

        snapshot = connector.snapshot("repo")

        self.assertTrue(snapshot.success)
        self.assertEqual(snapshot.facts["branch"], "main")
        self.assertTrue(snapshot.facts["dirty"])
        self.assertIn("file.py", snapshot.facts["diff_stat"])

    def test_openspec_connector_parses_list_status_and_apply_instructions(self):
        connector = OpenSpecConnector(FakeRunner([
            CommandResult(["openspec"], "repo", 0, stdout=json.dumps({"changes": [{"name": "change-a"}]})),
            CommandResult(["openspec"], "repo", 0, stdout=json.dumps({"changeName": "change-a", "schemaName": "spec-driven"})),
            CommandResult(["openspec"], "repo", 0, stdout=json.dumps({"state": "ready", "tasks": []})),
        ]))

        listed = connector.list_changes("repo")
        status = connector.status("repo", "change-a")
        instructions = connector.apply_instructions("repo", "change-a")

        self.assertEqual(listed.facts["changes"][0]["name"], "change-a")
        self.assertEqual(status.facts["changeName"], "change-a")
        self.assertEqual(instructions.facts["state"], "ready")

    def test_playbook_connector_parses_redmine_workspace_and_closeout(self):
        connector = PlaybookConnector(FakeRunner([
            CommandResult(["playbook"], "repo", 0, stdout=json.dumps({"id": 232211, "subject": "敏感日志"})),
            CommandResult(["playbook"], "repo", 0, stdout=json.dumps({"tasks": [{"id": "t1"}]})),
            CommandResult(["playbook"], "repo", 0, stdout=json.dumps({"gaps": [{"name": "mr"}]})),
        ]))

        redmine = connector.redmine_issue("repo", "232211")
        workspace = connector.workspace_status("repo")
        closeout = connector.closeout_gaps("repo")

        self.assertIn("232211", redmine.summary)
        self.assertEqual(workspace.facts["tasks"][0]["id"], "t1")
        self.assertEqual(closeout.facts["gaps"][0]["name"], "mr")

    def test_missing_command_and_invalid_json_degrade_to_unavailable_snapshot(self):
        missing = GitConnector(FakeRunner([
            CommandResult(["git"], "repo", 127, stderr="not found", missing=True),
        ])).snapshot("repo")
        invalid_json = OpenSpecConnector(FakeRunner([
            CommandResult(["openspec"], "repo", 0, stdout="not json"),
        ])).list_changes("repo")

        self.assertFalse(missing.success)
        self.assertIn("missing", missing.error)
        self.assertFalse(invalid_json.success)
        self.assertIn("invalid JSON", invalid_json.error)

    def test_command_runner_uses_utf8_replace_decoding(self):
        completed = Mock(returncode=0, stdout="中文输出", stderr="")

        with patch("subprocess.run", return_value=completed) as run:
            result = CommandRunner().run(["tool"], cwd="repo")

        self.assertEqual(result.stdout, "中文输出")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_command_runner_resolves_path_shims_without_changing_reported_args(self):
        completed = Mock(returncode=0, stdout="{}", stderr="")

        with (
            patch("shutil.which", return_value="C:/tools/openspec.cmd") as which,
            patch("subprocess.run", return_value=completed) as run,
        ):
            result = CommandRunner().run(["openspec", "list", "--json"], cwd="repo")

        self.assertEqual(result.args, ["openspec", "list", "--json"])
        which.assert_called_once_with("openspec", path=os.environ.get("PATH", ""))
        self.assertEqual(run.call_args.args[0], ["C:/tools/openspec.cmd", "list", "--json"])


if __name__ == "__main__":
    unittest.main()
