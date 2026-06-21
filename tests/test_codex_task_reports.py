import json
import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.workflow import CodexTaskReportService
from ai_todo_assistant.presentation.cli import TodoCLI


class TestCodexTaskReports(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_latest_report_loads_unfinished_tasks(self):
        report_path = os.path.join(self.temp_dir.name, "2026-06-19.json")
        summary_path = os.path.join(self.temp_dir.name, "2026-06-19.md")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-19T08:30:00+08:00",
                    "total_unfinished": 2,
                    "summary": "有 2 项需要跟进",
                    "unfinished": [
                        {
                            "thread_id": "thread-1",
                            "title": "修订 OpenSpec",
                            "status": "needs_action",
                            "next_action": "补齐日报能力",
                        }
                    ],
                    "blocked": [
                        {
                            "thread_id": "thread-2",
                            "title": "公众号草稿发布",
                            "status": "blocked",
                        }
                    ],
                },
                handle,
            )
        with open(summary_path, "w", encoding="utf-8") as handle:
            handle.write("# Codex 每日总结\n\n需要今天跟进：修订 OpenSpec。")

        report = CodexTaskReportService(self.temp_dir.name).latest_report()

        self.assertIsNotNone(report)
        self.assertEqual(report.total_unfinished, 2)
        self.assertTrue(report.has_unfinished)
        self.assertEqual(report.unfinished[0]["title"], "修订 OpenSpec")
        self.assertEqual(report.summary_path, summary_path)
        self.assertIn("Codex 每日总结", report.daily_summary_markdown)

    def test_cli_reads_latest_codex_task_report(self):
        report_path = os.path.join(self.temp_dir.name, "2026-06-19.json")
        summary_path = os.path.join(self.temp_dir.name, "2026-06-19.md")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-19T08:30:00+08:00",
                    "unfinished": [
                        {
                            "thread_id": "019ed87b",
                            "title": "ai-node 工作助手",
                            "status": "needs_action",
                            "next_action": "实现 Codex 快照识别",
                        }
                    ],
                    "completed": [
                        {
                            "thread_id": "019ed34d",
                            "title": "npki-docs MR 合并",
                            "completion_signals": ["MR !14 merged", "remote develop updated"],
                        }
                    ],
                },
                handle,
            )
        with open(summary_path, "w", encoding="utf-8") as handle:
            handle.write("# Codex 每日总结\n\n最近完成：npki-docs MR 合并。")
        cli = object.__new__(TodoCLI)
        cli.config = {
            "project_root": self.temp_dir.name,
            "codex_task_report_dir": self.temp_dir.name,
        }

        response = cli._handle_slash_command("/codex tasks")

        self.assertIn("Codex 未完成任务日报", response)
        self.assertIn("ai-node 工作助手", response)
        self.assertIn("实现 Codex 快照识别", response)
        self.assertIn("最近完成", response)
        self.assertIn("MR !14 merged", response)
        self.assertIn(summary_path, response)

    def test_malformed_report_is_skipped_and_valid_report_still_loads(self):
        bad_path = os.path.join(self.temp_dir.name, "2026-06-18.json")
        good_path = os.path.join(self.temp_dir.name, "2026-06-19.json")
        with open(bad_path, "w", encoding="utf-8") as handle:
            handle.write("{ invalid json")
        with open(good_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-19T08:30:00+08:00",
                    "unfinished": [{"title": "继续实现日报识别"}],
                },
                handle,
            )

        report = CodexTaskReportService(self.temp_dir.name).latest_report()

        self.assertIsNotNone(report)
        self.assertEqual(report.path, good_path)
        self.assertEqual(report.total_unfinished, 1)


if __name__ == "__main__":
    unittest.main()
