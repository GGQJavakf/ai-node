import os
import tempfile
import unittest
from types import SimpleNamespace

import _path  # noqa: F401
from ai_todo_assistant.application.workflow.codex_resume import (
    CodexResumeService,
    CodexThreadResumeOutcome,
    format_codex_resume_result,
)
from ai_todo_assistant.domain.workflow import WorkItem
from ai_todo_assistant.infrastructure.persistence import SQLiteWorkflowRepository


class FakeResumeClient:
    def __init__(self, success=True, message="sent"):
        self.calls = []
        self.success = success
        self.message = message

    def resume_thread(self, thread_id, prompt):
        self.calls.append((thread_id, prompt))
        return CodexThreadResumeOutcome(success=self.success, message=self.message)


class RaisingResumeClient:
    def __init__(self, message="bridge timeout"):
        self.calls = []
        self.message = message

    def resume_thread(self, thread_id, prompt):
        self.calls.append((thread_id, prompt))
        raise RuntimeError(self.message)


class TestCodexThreadResume(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteWorkflowRepository(os.path.join(self.temp_dir.name, "workflow.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dry_run_lists_only_explicitly_continueable_entries(self):
        client = FakeResumeClient()
        report = _report(
            unfinished=[
                {
                    "thread_id": "thread-ready",
                    "title": "继续开发",
                    "resume_eligible": True,
                    "resume_prompt": "继续执行到测试通过",
                },
                {"thread_id": "thread-needs-user", "title": "等输入", "status": "needs_user", "next_action": "问用户"},
                {"title": "缺少 thread id", "status": "continueable", "next_action": "继续"},
                {"thread_id": "thread-missing-prompt", "status": "continueable"},
            ],
            blocked=[{"thread_id": "thread-blocked", "title": "阻塞"}],
            completed=[{"thread_id": "thread-done", "title": "已完成"}],
        )

        result = CodexResumeService(self.repository, client).resume(report, dry_run=True)

        self.assertTrue(result.dry_run)
        self.assertEqual([candidate.thread_id for candidate in result.candidates], ["thread-ready"])
        self.assertEqual(client.calls, [])
        self.assertEqual(self.repository.list_work_items(include_closed=True), [])
        skip_text = "\n".join(skip.reason for skip in result.skipped)
        self.assertIn("需要用户输入", skip_text)
        self.assertIn("缺少 thread id", skip_text)
        self.assertIn("缺少 continuation prompt", skip_text)
        self.assertIn("blocked bucket", skip_text)
        self.assertIn("completed bucket", skip_text)

    def test_resume_calls_client_and_records_success_evidence(self):
        client = FakeResumeClient(success=True, message="queued")
        self.repository.save_work_item(WorkItem(title="继续开发", source="codex", source_ref="thread-ready"))
        report = _report(
            unfinished=[
                {
                    "thread_id": "thread-ready",
                    "title": "继续开发",
                    "status": "continueable",
                    "next_action": "继续执行到测试通过",
                }
            ]
        )

        result = CodexResumeService(self.repository, client).resume(report)

        self.assertEqual(client.calls, [("thread-ready", "继续执行到测试通过")])
        self.assertEqual(len(result.attempts), 1)
        self.assertTrue(result.attempts[0].success)
        item = self.repository.find_work_item_by_source("codex", "thread-ready")
        evidence = self.repository.list_evidence(item.id)
        self.assertEqual(len(evidence), 1)
        self.assertTrue(evidence[0].success)
        self.assertIn("thread-ready", evidence[0].summary)
        self.assertIn("继续执行到测试通过", evidence[0].output_excerpt)

    def test_resume_creates_missing_work_item_and_records_failure_evidence(self):
        client = FakeResumeClient(success=False, message="resume client unavailable")
        report = _report(
            unfinished=[
                {
                    "thread_id": "thread-new",
                    "title": "新线程",
                    "resume_eligible": True,
                    "resume_prompt": "继续",
                    "cwd": "D:/repo",
                }
            ]
        )

        result = CodexResumeService(self.repository, client).resume(report)

        self.assertFalse(result.attempts[0].success)
        item = self.repository.find_work_item_by_source("codex", "thread-new")
        self.assertIsNotNone(item)
        self.assertEqual(item.project_path, "D:/repo")
        evidence = self.repository.list_evidence(item.id)
        self.assertEqual(len(evidence), 1)
        self.assertFalse(evidence[0].success)
        self.assertIn("resume client unavailable", evidence[0].output_excerpt)

    def test_targeted_resume_only_evaluates_requested_thread(self):
        client = FakeResumeClient()
        report = _report(
            unfinished=[
                {"thread_id": "thread-1", "status": "continueable", "next_action": "继续 1"},
                {"thread_id": "thread-2", "status": "continueable", "next_action": "继续 2"},
            ]
        )

        result = CodexResumeService(self.repository, client).resume(report, thread_id="thread-2")

        self.assertEqual(client.calls, [("thread-2", "继续 2")])
        self.assertEqual([candidate.thread_id for candidate in result.candidates], ["thread-2"])

    def test_formatter_reports_candidates_attempts_and_skips(self):
        client = FakeResumeClient()
        report = _report(
            unfinished=[
                {"thread_id": "thread-ready", "status": "continueable", "next_action": "继续"},
                {"thread_id": "thread-user", "status": "needs_user", "next_action": "等待"},
            ]
        )

        dry_run = CodexResumeService(self.repository, client).resume(report, dry_run=True)
        executed = CodexResumeService(self.repository, client).resume(report)

        self.assertIn("Codex resume [DRY-RUN]", format_codex_resume_result(dry_run))
        self.assertIn("thread-ready", format_codex_resume_result(dry_run))
        self.assertIn("跳过", format_codex_resume_result(dry_run))
        self.assertIn("[OK]", format_codex_resume_result(executed))

    def test_selection_handles_edge_inputs_and_missing_target(self):
        client = FakeResumeClient()
        report = _report(
            unfinished=[
                "not-a-dict",
                {"thread_id": "thread-blocked-status", "status": "blocked", "next_action": "继续"},
                {"thread_id": "thread-unmarked", "status": "idle", "next_action": "继续"},
                {"thread_id": "thread-string-marker", "resume_eligible": "true", "next_action": "继续"},
            ],
            blocked=["not-a-dict", {"thread_id": "thread-blocked-bucket", "title": "阻塞桶"}],
            completed=[{"thread_id": "thread-done-bucket", "title": "完成桶"}],
        )

        all_result = CodexResumeService(self.repository, client).resume(report, dry_run=True)
        missing = CodexResumeService(self.repository, client).resume(report, dry_run=True, thread_id="missing-thread")

        self.assertEqual([candidate.thread_id for candidate in all_result.candidates], ["thread-string-marker"])
        skip_text = "\n".join(skip.reason for skip in all_result.skipped)
        self.assertIn("status blocked is not resumeable", skip_text)
        self.assertIn("not marked resumeable", skip_text)
        self.assertIn("blocked bucket", skip_text)
        self.assertIn("completed bucket", skip_text)
        self.assertEqual(missing.skipped[0].reason, "thread not found in latest report")

    def test_formatter_reports_zero_candidates_or_attempts(self):
        dry_run = CodexResumeService(self.repository, FakeResumeClient()).resume(_report(), dry_run=True)
        executed = CodexResumeService(self.repository, FakeResumeClient()).resume(_report())

        self.assertIn("可推进: 0 项", format_codex_resume_result(dry_run))
        self.assertIn("已尝试: 0 项", format_codex_resume_result(executed))

    def test_conflicting_status_fields_fail_closed(self):
        report = _report(
            unfinished=[
                {
                    "thread_id": "thread-conflict-user",
                    "classification": "continueable",
                    "status": "needs_user",
                    "next_action": "继续",
                },
                {
                    "thread_id": "thread-conflict-blocked",
                    "classification": "continueable",
                    "state": "blocked",
                    "next_action": "继续",
                },
            ]
        )

        result = CodexResumeService(self.repository, FakeResumeClient()).resume(report, dry_run=True)

        self.assertEqual(result.candidates, [])
        skip_text = "\n".join(skip.reason for skip in result.skipped)
        self.assertIn("需要用户输入", skip_text)
        self.assertIn("status blocked is not resumeable", skip_text)

    def test_blocked_or_completed_bucket_overrides_unfinished_candidate(self):
        report = _report(
            unfinished=[
                {"thread_id": "thread-blocked", "status": "continueable", "next_action": "继续 blocked"},
                {"thread_id": "thread-done", "status": "continueable", "next_action": "继续 done"},
                {"thread_id": "thread-ready", "status": "continueable", "next_action": "继续 ready"},
            ],
            blocked=[{"thread_id": "thread-blocked", "title": "阻塞覆盖"}],
            completed=[{"thread_id": "thread-done", "title": "完成覆盖"}],
        )

        result = CodexResumeService(self.repository, FakeResumeClient()).resume(report, dry_run=True)

        self.assertEqual([candidate.thread_id for candidate in result.candidates], ["thread-ready"])
        skip_text = "\n".join(f"{skip.thread_id}:{skip.reason}" for skip in result.skipped)
        self.assertIn("thread-blocked:blocked bucket entries are not resumeable", skip_text)
        self.assertIn("thread-done:completed bucket entries are not resumeable", skip_text)

    def test_client_exception_records_failed_evidence(self):
        client = RaisingResumeClient()
        report = _report(
            unfinished=[
                {"thread_id": "thread-raises", "status": "continueable", "next_action": "继续"},
            ]
        )

        result = CodexResumeService(self.repository, client).resume(report)
        item = self.repository.find_work_item_by_source("codex", "thread-raises")
        evidence = self.repository.list_evidence(item.id)

        self.assertEqual(client.calls, [("thread-raises", "继续")])
        self.assertFalse(result.attempts[0].success)
        self.assertIn("bridge timeout", result.attempts[0].message)
        self.assertFalse(evidence[0].success)
        self.assertIn("bridge timeout", evidence[0].output_excerpt)


def _report(unfinished=None, blocked=None, completed=None):
    return SimpleNamespace(
        path="report.json",
        generated_at="2026-06-23T10:00:00+08:00",
        summary="",
        unfinished=list(unfinished or []),
        blocked=list(blocked or []),
        completed=list(completed or []),
    )


if __name__ == "__main__":
    unittest.main()
