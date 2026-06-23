import unittest
from io import StringIO
from unittest.mock import patch

import _path  # noqa: F401
from ai_todo_assistant.application.workflow.sync_watch import (
    SyncWatchRunner,
    format_sync_watch_report,
)
from ai_todo_assistant.infrastructure.config.settings import load_settings
from ai_todo_assistant.presentation.cli import _parse_sync_options
from ai_todo_assistant.presentation.cli import TodoCLI
from rich.console import Console


class TestSyncWatch(unittest.TestCase):
    def test_runner_reports_each_trigger_and_sleeps_between_runs(self):
        sync_paths = []
        slept = []
        moments = iter(["2026-06-23 10:00:00", "2026-06-23 10:05:00"])

        runner = SyncWatchRunner(
            sync_once=lambda path: sync_paths.append(path) or f"sync {path}",
            recommend_next=lambda: "Recommendation: 继续处理 Codex 阻塞项",
            now=lambda: next(moments),
            sleep=lambda seconds: slept.append(seconds),
        )

        results = list(runner.run(interval_seconds=300, path="D:/repo", max_runs=2))

        self.assertEqual(sync_paths, ["D:/repo", "D:/repo"])
        self.assertEqual(slept, [300])
        self.assertEqual(results[0].run_number, 1)
        self.assertEqual(results[1].triggered_at, "2026-06-23 10:05:00")

        report = format_sync_watch_report(results[0])
        self.assertIn("Sync watch trigger #1", report)
        self.assertIn("2026-06-23 10:00:00", report)
        self.assertIn("sync D:/repo", report)
        self.assertIn("继续处理 Codex 阻塞项", report)

    def test_parse_sync_watch_options(self):
        options = _parse_sync_options("watch", "300 D:/repo")

        self.assertTrue(options["watch"])
        self.assertEqual(options["interval_seconds"], 300)
        self.assertEqual(options["path"], "D:/repo")

    def test_parse_sync_watch_resume_options(self):
        options = _parse_sync_options("watch", "--resume --once 300 D:/repo")

        self.assertTrue(options["watch"])
        self.assertTrue(options["resume"])
        self.assertTrue(options["once"])
        self.assertEqual(options["interval_seconds"], 300)
        self.assertEqual(options["path"], "D:/repo")

    def test_sync_watch_rejects_dry_run_or_status_combinations_before_syncing(self):
        cli = object.__new__(TodoCLI)
        cli.config = {"sync_watch_interval_seconds": 1800}
        cli.console = Console(file=StringIO(), force_terminal=False)
        cli._run_sync_once = lambda path: (_ for _ in ()).throw(AssertionError("must not sync"))
        cli._handle_continue_command = lambda: "next"

        dry_run = cli._handle_slash_command("/sync watch --dry-run")
        status = cli._handle_slash_command("/sync status watch")

        self.assertIn("不能与 --dry-run 或 status 组合", dry_run)
        self.assertIn("不能与 --dry-run 或 status 组合", status)

    def test_sync_watch_once_prints_report_once_and_returns_status(self):
        cli = object.__new__(TodoCLI)
        buffer = StringIO()
        cli.config = {"sync_watch_interval_seconds": 1800}
        cli.console = Console(file=buffer, force_terminal=False)
        cli._run_sync_once = lambda path: "sync ok"
        cli._handle_continue_command = lambda: "next action"

        response = cli._handle_slash_command("/sync watch --once")
        printed = buffer.getvalue()

        self.assertEqual(printed.count("Sync watch trigger #1"), 1)
        self.assertNotIn("Sync watch trigger #1", response)
        self.assertIn("已完成 1 轮", response)

    def test_sync_watch_resume_includes_resume_result(self):
        cli = object.__new__(TodoCLI)
        buffer = StringIO()
        cli.config = {"sync_watch_interval_seconds": 1800}
        cli.console = Console(file=buffer, force_terminal=False)
        cli._run_sync_once = lambda path: "sync ok"
        cli._handle_continue_command = lambda: "next action"
        cli._handle_codex_resume_command = lambda args: "resume ok"

        response = cli._handle_slash_command("/sync watch --resume --once")
        printed = buffer.getvalue()

        self.assertIn("resume ok", printed)
        self.assertIn("已完成 1 轮", response)

    def test_invalid_sync_watch_interval_env_falls_back_to_default(self):
        with patch.dict("os.environ", {"AI_SYNC_WATCH_INTERVAL_SECONDS": "abc"}):
            config = load_settings(project_root=".")

        self.assertEqual(config["sync_watch_interval_seconds"], 1800)

    def test_non_positive_sync_watch_interval_env_falls_back_to_default(self):
        with patch.dict("os.environ", {"AI_SYNC_WATCH_INTERVAL_SECONDS": "0"}):
            config = load_settings(project_root=".")

        self.assertEqual(config["sync_watch_interval_seconds"], 1800)


if __name__ == "__main__":
    unittest.main()
