import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import _path  # noqa: F401
from ai_todo_assistant.application.workflow import (
    ContinueService,
    DailyReviewService,
    EvidenceService,
    WorkItemService,
)
from ai_todo_assistant.domain.workflow import SourceSnapshot, WorkItem, WorkItemStatus
from ai_todo_assistant.infrastructure.persistence.json_todo_repository import TodoManager
from ai_todo_assistant.infrastructure.persistence import SQLiteWorkflowRepository
from ai_todo_assistant.presentation.cli import TodoCLI


class TestWorkflowServicesAndCli(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workflow_path = os.path.join(self.temp_dir.name, "workflow.db")
        self.report_dir = os.path.join(self.temp_dir.name, "reports")
        os.makedirs(self.report_dir, exist_ok=True)
        self.repository = SQLiteWorkflowRepository(self.workflow_path)
        self.cli = object.__new__(TodoCLI)
        self.cli.workflow_repository = self.repository
        self.cli.config = {
            "project_root": self.temp_dir.name,
            "codex_task_report_dir": self.report_dir,
            "storage_backend": "sqlite",
            "sqlite_path": self.workflow_path,
        }
        self.cli.manager = TodoManager(os.path.join(self.temp_dir.name, "todos.json"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_can_create_status_and_record_evidence(self):
        created = self.cli._handle_slash_command("/work add 实现工作助手")
        work_id = created.split("ID:")[1]

        status = self.cli._handle_slash_command("/work status")
        evidence = self.cli._handle_slash_command(f"/work evidence add {work_id} 单元测试通过")
        summary = self.cli._handle_slash_command(f"/work evidence summary {work_id}")

        self.assertIn("已创建工作项", created)
        self.assertIn("实现工作助手", status)
        self.assertIn("已记录证据", evidence)
        self.assertIn("单元测试通过", summary)

    def test_codex_tasks_imports_unfinished_entries_as_work_items(self):
        with open(os.path.join(self.report_dir, "2026-06-19.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-19T08:30:00+08:00",
                    "unfinished": [
                        {
                            "thread_id": "thread-1",
                            "title": "继续 OpenSpec 实现",
                            "status": "needs_action",
                            "next_action": "实现 WorkItem sync",
                        }
                    ],
                    "blocked": [],
                    "completed": [],
                },
                handle,
            )

        response = self.cli._handle_slash_command("/codex tasks")
        items = self.repository.list_work_items()

        self.assertIn("已同步工作项: 1", response)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "codex")
        self.assertEqual(items[0].next_action, "实现 WorkItem sync")

    def test_codex_tasks_imports_completed_entries_as_done_evidence(self):
        with open(os.path.join(self.report_dir, "2026-06-19.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-19T08:30:00+08:00",
                    "unfinished": [],
                    "blocked": [],
                    "completed": [
                        {
                            "thread_id": "thread-done",
                            "title": "MR 合并闭环",
                            "completion_signals": ["MR !14 merged", "closeout verified"],
                        }
                    ],
                },
                handle,
            )

        response = self.cli._handle_slash_command("/codex tasks")
        items = self.repository.list_work_items(include_closed=True)

        self.assertIn("MR !14 merged", response)
        self.assertEqual(items[0].status, WorkItemStatus.DONE.value)
        self.assertIn("MR !14 merged", self.repository.list_evidence(items[0].id)[0].summary)

    def test_codex_completion_sync_is_idempotent_and_appends_new_signals(self):
        service = WorkItemService(self.repository)
        existing = WorkItem(title="待闭环", source="codex", source_ref="thread-done")
        self.repository.save_work_item(existing)
        first_report = SimpleNamespace(
            path="report-1.json",
            generated_at="2026-06-19T08:30:00+08:00",
            summary="",
            unfinished=[],
            blocked=[],
            completed=[
                {
                    "thread_id": "thread-done",
                    "title": "待闭环",
                    "completion_signals": ["MR merged"],
                }
            ],
        )
        second_report = SimpleNamespace(
            path="report-2.json",
            generated_at="2026-06-20T08:30:00+08:00",
            summary="",
            unfinished=[],
            blocked=[],
            completed=[
                {
                    "thread_id": "thread-done",
                    "title": "待闭环",
                    "completion_signals": ["MR merged", "closeout verified"],
                }
            ],
        )

        first = service.import_codex_report(first_report)
        repeated = service.import_codex_report(first_report)
        second = service.import_codex_report(second_report)
        item = self.repository.find_work_item_by_source("codex", "thread-done")
        evidence = self.repository.list_evidence(item.id)

        self.assertEqual(first.completed, 1)
        self.assertEqual(repeated.unchanged, 1)
        self.assertEqual(second.unchanged, 1)
        self.assertEqual(item.status, WorkItemStatus.DONE.value)
        self.assertEqual(len(evidence), 2)
        self.assertIn("MR merged", evidence[0].summary)
        self.assertIn("closeout verified", evidence[1].summary)

    def test_codex_state_machine_blocks_reactivates_and_prevents_done_regression(self):
        active = self.repository.save_work_item(WorkItem(title="会阻塞", source="codex", source_ref="thread-block"))
        blocked = WorkItem(title="会恢复", source="codex", source_ref="thread-active")
        blocked.status = WorkItemStatus.BLOCKED.value
        self.repository.save_work_item(blocked)
        done = WorkItem(title="已完成", source="codex", source_ref="thread-done")
        done.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(done)
        report = SimpleNamespace(
            path="report.json",
            generated_at="2026-06-20T08:30:00+08:00",
            summary="",
            unfinished=[
                {"thread_id": "thread-active", "title": "会恢复"},
                {"thread_id": "thread-done", "title": "已完成又出现"},
            ],
            blocked=[{"thread_id": "thread-block", "title": "会阻塞"}],
            completed=[],
        )

        result = WorkItemService(self.repository).import_codex_report(report)

        self.assertEqual(result.blocked, 1)
        self.assertEqual(result.reactivated, 1)
        self.assertEqual(result.unchanged, 1)
        self.assertEqual(
            self.repository.find_work_item_by_source("codex", active.source_ref).status,
            WorkItemStatus.BLOCKED.value,
        )
        self.assertEqual(
            self.repository.find_work_item_by_source("codex", blocked.source_ref).status,
            WorkItemStatus.ACTIVE.value,
        )
        self.assertEqual(
            self.repository.find_work_item_by_source("codex", done.source_ref).status,
            WorkItemStatus.DONE.value,
        )

    def test_list_default_combines_todos_and_imported_work_items(self):
        self.cli.manager.add("传统 Todo")
        WorkItemService(self.repository).create_manual("Codex 导入任务", next_action="继续修复")

        table = self.cli._handle_slash_command("/list")

        rendered = _render_table(table)
        self.assertIn("传统 Todo", rendered)
        self.assertIn("Codex 导入任务", rendered)
        self.assertIn("todo", rendered)
        self.assertIn("manual", rendered)

    def test_list_default_groups_daily_triage_with_reasons_and_stale_markers(self):
        today = datetime.now().strftime("%Y-%m-%d 09:00:00")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 09:00:00")
        self.cli.manager.add("low priority reminder", priority="low")
        blocked = WorkItem(
            title="Redmine 232211 blocked",
            source="redmine",
            source_ref="232211",
            priority="high",
            last_synced_at=today,
        )
        blocked.status = WorkItemStatus.BLOCKED.value
        self.repository.save_work_item(blocked)
        validation = WorkItem(
            title="implement triage default view",
            source="codex",
            source_ref="thread-validation",
            priority="medium",
            next_action="run validation tests",
            last_synced_at=today,
        )
        self.repository.save_work_item(validation)
        closeout = WorkItem(
            title="MR !42 merged but closeout missing",
            source="codex",
            source_ref="thread-closeout",
            priority="medium",
            next_action="MR merged but closeout missing",
            last_synced_at=today,
        )
        self.repository.save_work_item(closeout)
        stale = WorkItem(
            title="stale codex item",
            source="codex",
            source_ref="thread-stale",
            priority="medium",
            last_synced_at=yesterday,
        )
        self.repository.save_work_item(stale)
        completed = WorkItem(
            title="recently completed closeout",
            source="codex",
            source_ref="thread-done",
            priority="medium",
            last_synced_at=yesterday,
        )
        completed.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(completed)

        rendered = _render_table(self.cli._handle_slash_command("/list"))

        self.assertIn("blocked", rendered)
        self.assertIn("active needs action", rendered)
        self.assertIn("waiting closeout", rendered)
        self.assertIn("stale sync", rendered)
        self.assertIn("recently completed", rendered)
        self.assertIn("todo reminders", rendered)
        self.assertIn("blocked by Redmine", rendered)
        self.assertIn("needs validation", rendered)
        self.assertIn("MR merged but closeout missing", rendered)
        self.assertIn("Codex thread still active", rendered)
        self.assertIn("[stale]", rendered)
        self.assertLess(rendered.index("blocked by Redmine"), rendered.index("todo reminder"))
        completed_line = next(line for line in rendered.splitlines() if "recently completed" in line)
        self.assertNotIn("[stale]", completed_line)

    def test_list_default_source_todo_filter_suppresses_work_items(self):
        self.cli.manager.add("只看 Todo")
        WorkItemService(self.repository).create_manual("不应出现", next_action="继续")

        rendered = _render_table(self.cli._handle_slash_command("/list --source todo"))

        self.assertIn("只看 Todo", rendered)
        self.assertIn("todo reminders", rendered)
        self.assertNotIn("不应出现", rendered)

    def test_continue_start_and_review_use_work_items_and_evidence(self):
        item = WorkItemService(self.repository).create_manual(
            "修复工作流",
            priority="high",
            next_action="运行全量测试",
        )
        EvidenceService(self.repository).record(item.id, "test", "workflow tests passed", success=True)

        recommended = ContinueService(self.repository).recommend()
        start = DailyReviewService(self.repository).start_day()
        review = DailyReviewService(self.repository).review_day()

        self.assertIn("运行全量测试", recommended)
        self.assertIn("Recommendation", start)
        self.assertIn("Recommended follow-ups", review)

    def test_review_day_has_blockers_section(self):
        blocked = WorkItemService(self.repository).create_manual("等待 MR 合并", next_action="确认流水线")
        blocked.status = WorkItemStatus.BLOCKED.value
        self.repository.save_work_item(blocked)
        EvidenceService(self.repository).record(blocked.id, "note", "流水线仍在等待", success=False)

        review = DailyReviewService(self.repository).review_day()

        self.assertIn("Blockers:", review)
        self.assertIn("等待 MR 合并", review)

    def test_cli_import_redmine_uses_workflow_sync_service(self):
        class FakeSyncService:
            def __init__(self, repository):
                self.repository = repository

            def import_redmine(self, project_path, issue_id):
                item = WorkItem(title="Redmine 导入任务", source="redmine", source_ref=issue_id)
                return self.repository.save_work_item(item)

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FakeSyncService):
            response = self.cli._handle_slash_command("/work import redmine 232211")

        self.assertIn("已导入 Redmine 工作项", response)
        self.assertEqual(self.repository.list_work_items()[0].source_ref, "232211")

    def test_cli_import_redmine_reports_failure_without_persisting(self):
        class FailingSyncService:
            def __init__(self, repository):
                self.repository = repository

            def import_redmine(self, project_path, issue_id):
                raise RuntimeError("playbook missing")

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FailingSyncService):
            response = self.cli._handle_slash_command("/work import redmine 232211")

        self.assertIn("导入失败", response)
        self.assertEqual(self.repository.list_work_items(include_closed=True), [])

    def test_cli_sync_summarizes_readonly_snapshots(self):
        class FakeSyncService:
            def __init__(self, repository):
                self.repository = repository

            def sync_project(self, project_path):
                return [
                    SourceSnapshot(source="git", project_path=project_path, summary="branch=main"),
                    SourceSnapshot(source="openspec", project_path=project_path, summary="1 active changes"),
                ]

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FakeSyncService):
            response = self.cli._handle_slash_command("/sync D:/repo")

        self.assertIn("[OK] git: branch=main", response)
        self.assertIn("[OK] openspec: 1 active changes", response)

    def test_cli_sync_imports_latest_codex_report(self):
        with open(os.path.join(self.report_dir, "2026-06-19.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-19T08:30:00+08:00",
                    "unfinished": [
                        {
                            "thread_id": "thread-1",
                            "title": "Codex 后续任务",
                            "next_action": "继续验证",
                        }
                    ],
                    "completed": [
                        {
                            "thread_id": "thread-done",
                            "title": "已完成任务",
                            "completion_signals": ["MR merged"],
                        }
                    ],
                },
                handle,
            )

        class FakeSyncService:
            def __init__(self, repository):
                self.repository = repository

            def sync_project(self, project_path):
                return [SourceSnapshot(source="git", project_path=project_path, summary="branch=main")]

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FakeSyncService):
            response = self.cli._handle_slash_command("/sync D:/repo")

        items = self.repository.list_work_items(include_closed=True)
        self.assertIn("codex: 已导入/刷新 2 项", response)
        self.assertIn("completed=1", response)
        self.assertIn("unchanged=0", response)
        self.assertEqual(len(items), 2)
        self.assertEqual(
            self.repository.find_work_item_by_source("codex", "thread-done").status,
            WorkItemStatus.DONE.value,
        )

    def test_cli_sync_summarizes_codex_status_changes_and_list_completed_shows_done_work(self):
        self.repository.save_work_item(WorkItem(title="会完成", source="codex", source_ref="thread-complete"))
        blocked = WorkItem(title="会恢复", source="codex", source_ref="thread-reactivate")
        blocked.status = WorkItemStatus.BLOCKED.value
        self.repository.save_work_item(blocked)
        unchanged = WorkItem(title="保持完成", source="codex", source_ref="thread-unchanged")
        unchanged.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(unchanged)
        with open(os.path.join(self.report_dir, "2026-06-20.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-20T08:30:00+08:00",
                    "unfinished": [
                        {"thread_id": "thread-reactivate", "title": "会恢复"},
                    ],
                    "blocked": [
                        {"thread_id": "thread-block", "title": "新阻塞"},
                    ],
                    "completed": [
                        {
                            "thread_id": "thread-complete",
                            "title": "会完成",
                            "completion_signals": ["tests passed"],
                        },
                        {
                            "thread_id": "thread-unchanged",
                            "title": "保持完成",
                            "completion_signals": ["already done"],
                        },
                    ],
                },
                handle,
            )

        class FakeSyncService:
            def __init__(self, repository):
                self.repository = repository

            def sync_project(self, project_path):
                return [SourceSnapshot(source="git", project_path=project_path, summary="branch=main")]

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FakeSyncService):
            response = self.cli._handle_slash_command("/sync D:/repo")

        completed_table = self.cli._handle_slash_command("/list completed")
        rendered = _render_table(completed_table)

        self.assertIn("completed=1", response)
        self.assertIn("blocked=1", response)
        self.assertIn("reactivated=1", response)
        self.assertIn("unchanged=1", response)
        self.assertIn("会完成", rendered)
        self.assertIn("codex", rendered)

    def test_cli_sync_uses_human_readable_codex_summary(self):
        self.repository.save_work_item(WorkItem(title="会完成", source="codex", source_ref="thread-complete"))
        with open(os.path.join(self.report_dir, "2026-06-21.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-21T08:30:00+08:00",
                    "unfinished": [],
                    "blocked": [],
                    "completed": [
                        {
                            "thread_id": "thread-complete",
                            "title": "会完成",
                            "completion_signals": ["tests passed"],
                        }
                    ],
                },
                handle,
            )

        class FakeSyncService:
            def __init__(self, repository):
                self.repository = repository

            def sync_project(self, project_path):
                return [SourceSnapshot(source="git", project_path=project_path, summary="branch=main")]

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FakeSyncService):
            response = self.cli._handle_slash_command("/sync D:/repo")

        self.assertIn("本次闭环 1 项", response)
        self.assertIn("导入: 新建 0 / 更新 1 / 合并 0 / 跳过 0", response)
        self.assertIn("completed=1", response)

    def test_cli_sync_invalid_project_path_keeps_codex_import_result(self):
        with open(os.path.join(self.report_dir, "2026-06-21.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-21T08:30:00+08:00",
                    "unfinished": [],
                    "blocked": [],
                    "completed": [
                        {
                            "thread_id": "thread-done",
                            "title": "已完成任务",
                            "completion_signals": ["review approved"],
                        }
                    ],
                },
                handle,
            )

        response = self.cli._handle_slash_command("/sync Z:/definitely/not/a/repo")

        self.assertIn("本次闭环 1 项", response)
        self.assertIn("项目路径不可用", response)
        self.assertEqual(
            self.repository.find_work_item_by_source("codex", "thread-done").status,
            WorkItemStatus.DONE.value,
        )

    def test_cli_sync_explains_skipped_and_done_regression_items(self):
        WorkItemService(self.repository).create_manual("标题冲突任务")
        done = WorkItem(title="已闭环任务", source="codex", source_ref="thread-done")
        done.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(done)
        with open(os.path.join(self.report_dir, "2026-06-21.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-21T08:30:00+08:00",
                    "unfinished": [
                        {
                            "thread_id": "thread-skipped",
                            "title": "标题冲突任务",
                        },
                        {
                            "thread_id": "thread-done",
                            "title": "已闭环任务",
                        },
                    ],
                    "blocked": [],
                    "completed": [],
                },
                handle,
            )

        class FakeSyncService:
            def __init__(self, repository):
                self.repository = repository

            def sync_project(self, project_path):
                return [SourceSnapshot(source="git", project_path=project_path, summary="branch=main")]

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FakeSyncService):
            response = self.cli._handle_slash_command("/sync D:/repo")

        self.assertIn("跳过: 标题冲突任务", response)
        self.assertIn("保留 done: 已闭环任务", response)

    def test_cli_sync_reports_codex_merge_summary(self):
        with open(os.path.join(self.report_dir, "2026-06-20.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-20T08:30:00+08:00",
                    "unfinished": [
                        {
                            "thread_id": "thread-redmine-a",
                            "title": "Redmine 232211 日志整改",
                            "next_action": "继续 Redmine 232211",
                            "cwd": "D:/repo",
                        },
                        {
                            "thread_id": "thread-redmine-b",
                            "source_ref": "issue 232211",
                            "title": "同一问题后续",
                            "next_action": "Redmine 232211 closeout",
                            "cwd": "D:/repo",
                        },
                    ],
                    "blocked": [],
                    "completed": [],
                },
                handle,
            )

        class FakeSyncService:
            def __init__(self, repository):
                self.repository = repository

            def sync_project(self, project_path):
                return [SourceSnapshot(source="git", project_path=project_path, summary="branch=main")]

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FakeSyncService):
            response = self.cli._handle_slash_command("/sync D:/repo")

        rendered = _render_table(self.cli._handle_slash_command("/list"))
        self.assertIn("merged=1", response)
        self.assertIn("created=1", response)
        self.assertIn("updated=0", response)
        self.assertIn("skipped=0", response)
        self.assertIn("合并: 同一问题后续", response)
        self.assertIn("redmine:232211", response)
        self.assertEqual(len(self.repository.list_work_items()), 1)
        self.assertEqual(rendered.count("Redmine 232211"), 1)

    def test_cli_sync_dry_run_previews_without_persisting_codex_changes(self):
        self.repository.save_work_item(WorkItem(title="待预览闭环", source="codex", source_ref="thread-dry"))
        with open(os.path.join(self.report_dir, "2026-06-21.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-21T08:30:00+08:00",
                    "unfinished": [],
                    "blocked": [],
                    "completed": [
                        {
                            "thread_id": "thread-dry",
                            "title": "待预览闭环",
                            "completion_signals": ["dry-run tests passed"],
                        }
                    ],
                },
                handle,
            )

        class FailingSyncService:
            def __init__(self, repository):
                self.repository = repository

            def sync_project(self, project_path):
                raise AssertionError("dry-run must not sync project snapshots")

        with patch("ai_todo_assistant.presentation.cli.WorkflowSyncService", FailingSyncService):
            response = self.cli._handle_slash_command("/sync --dry-run D:/repo")

        item = self.repository.find_work_item_by_source("codex", "thread-dry")
        self.assertIn("DRY-RUN", response)
        self.assertIn("不会写入", response)
        self.assertIn("本次闭环 1 项", response)
        self.assertEqual(item.status, WorkItemStatus.ACTIVE.value)
        self.assertEqual(self.repository.list_evidence(item.id), [])

    def test_cli_sync_status_reports_latest_report_and_work_item_counts(self):
        active = WorkItem(title="活动任务", source="codex", source_ref="thread-active")
        active.last_synced_at = "2026-06-21 08:00:00"
        self.repository.save_work_item(active)
        blocked = WorkItem(title="阻塞任务", source="codex", source_ref="thread-blocked")
        blocked.status = WorkItemStatus.BLOCKED.value
        self.repository.save_work_item(blocked)
        done = WorkItem(title="完成任务", source="codex", source_ref="thread-done")
        done.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(done)
        with open(os.path.join(self.report_dir, "2026-06-21.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-21T08:30:00+08:00",
                    "unfinished": [],
                    "blocked": [],
                    "completed": [],
                },
                handle,
            )

        response = self.cli._handle_slash_command("/sync status")

        self.assertIn("同步状态", response)
        self.assertIn("最新 Codex report", response)
        self.assertIn("2026-06-21T08:30:00+08:00", response)
        self.assertIn("active=1", response)
        self.assertIn("blocked=1", response)
        self.assertIn("done=1", response)
        self.assertIn("最近 WorkItem 同步: 2026-06-21 08:00:00", response)

    def test_cli_list_completed_filters_by_work_item_source(self):
        codex = WorkItem(title="Codex 闭环任务", source="codex", source_ref="thread-done")
        codex.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(codex)
        manual = WorkItem(title="手动完成任务", source="manual")
        manual.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(manual)

        rendered = _render_table(self.cli._handle_slash_command("/list completed --source codex"))

        self.assertIn("Codex 闭环任务", rendered)
        self.assertIn("codex", rendered)
        self.assertNotIn("手动完成任务", rendered)

    def test_cli_work_split_recreates_source_ref_work_item(self):
        item = self.repository.save_work_item(
            WorkItem(
                title="Redmine 和 Codex 合并项",
                source="redmine",
                source_ref="232211",
                source_identities=["redmine:232211", "codex-thread:thread-1"],
                source_refs=[
                    {"source": "redmine", "source_ref": "232211", "label": "Redmine 232211"},
                    {"source": "codex", "source_ref": "thread-1", "label": "Codex thread"},
                ],
            )
        )

        response = self.cli._handle_slash_command(f"/work split {item.id} codex thread-1")

        items = self.repository.list_work_items(include_closed=True)
        self.assertIn("已拆分工作项", response)
        self.assertIn("thread-1", response)
        self.assertEqual(len(items), 2)
        self.assertIsNotNone(self.repository.find_work_item_by_source("codex", "thread-1"))

    def test_cli_work_show_displays_full_source_chain(self):
        item = self.repository.save_work_item(
            WorkItem(
                title="完整来源链",
                source="redmine",
                source_ref="232211",
                source_identities=[
                    "redmine:232211",
                    "codex-thread:thread-1",
                    "openspec:merge-duplicate-work-sources",
                    "gitlab-mr:D:/repo:42",
                    "codex-thread:thread-2",
                ],
                source_refs=[
                    {"source": "redmine", "source_ref": "232211", "label": "Redmine 232211"},
                    {"source": "codex", "source_ref": "thread-1", "label": "Codex thread 1"},
                    {"source": "codex", "source_ref": "thread-2", "label": "Codex thread 2"},
                ],
                merge_audit=[
                    {
                        "id": "audit-1",
                        "source": "codex",
                        "source_ref": "thread-1",
                        "reason": "identity",
                        "merged_at": "2026-06-21 10:00:00",
                    }
                ],
                merge_conflicts=["MR project scope conflict"],
            )
        )
        self.repository.add_evidence(
            SimpleNamespace(
                id="evidence-1",
                work_item_id=item.id,
                evidence_type="note",
                summary="测试证据",
                command="",
                output_excerpt="",
                success=True,
                source="codex",
                created_at="2026-06-21 10:01:00",
            )
        )

        response = self.cli._handle_slash_command(f"/work show {item.id}")

        self.assertIn("完整来源链", response)
        self.assertIn("redmine:232211", response)
        self.assertIn("codex:thread-1", response)
        self.assertIn("codex-thread:thread-2", response)
        self.assertIn("audit-1", response)
        self.assertIn("MR project scope conflict", response)
        self.assertIn("测试证据", response)

    def test_cli_work_conflicts_lists_items_needing_manual_resolution(self):
        conflicted = self.repository.save_work_item(
            WorkItem(
                title="存在来源冲突",
                source="redmine",
                source_ref="232211",
                source_identities=["redmine:232211", "codex-thread:thread-1"],
                merge_conflicts=["MR project scope conflict", "title mismatch"],
            )
        )
        clean = WorkItem(title="无冲突任务", source="codex", source_ref="thread-clean")
        clean.status = WorkItemStatus.BLOCKED.value
        self.repository.save_work_item(clean)

        response = self.cli._handle_slash_command("/work conflicts")

        self.assertIn("冲突工作项", response)
        self.assertIn("存在来源冲突", response)
        self.assertIn(conflicted.id[:8], response)
        self.assertIn("MR project scope conflict", response)
        self.assertIn("/work show", response)
        self.assertNotIn("无冲突任务", response)

    def test_cli_work_evidence_timeline_shows_time_source_and_outcome(self):
        item = self.repository.save_work_item(WorkItem(title="证据时间线", source="codex", source_ref="thread-1"))
        self.repository.add_evidence(
            SimpleNamespace(
                id="evidence-old",
                work_item_id=item.id,
                evidence_type="test",
                summary="单元测试失败",
                command="python -m unittest",
                output_excerpt="",
                success=False,
                source="local",
                created_at="2026-06-21 09:00:00",
            )
        )
        self.repository.add_evidence(
            SimpleNamespace(
                id="evidence-new",
                work_item_id=item.id,
                evidence_type="snapshot",
                summary="Codex completed thread-1",
                command="",
                output_excerpt="",
                success=True,
                source="codex",
                created_at="2026-06-21 10:00:00",
            )
        )

        response = self.cli._handle_slash_command(f"/work evidence timeline {item.id}")

        self.assertIn("证据时间线", response)
        self.assertLess(response.index("2026-06-21 09:00:00"), response.index("2026-06-21 10:00:00"))
        self.assertIn("[test/local/失败]", response)
        self.assertIn("[snapshot/codex/通过]", response)
        self.assertIn("python -m unittest", response)

    def test_cli_work_rollback_recreates_split_source(self):
        existing = self.repository.save_work_item(
            WorkItem(
                title="Redmine 232211",
                source="redmine",
                source_ref="232211",
                source_identities=["redmine:232211"],
            )
        )
        with open(os.path.join(self.report_dir, "2026-06-21.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "generated_at": "2026-06-21T08:30:00+08:00",
                    "unfinished": [
                        {
                            "thread_id": "thread-rollback",
                            "title": "Redmine 232211 Codex 后续",
                            "next_action": "继续 Redmine 232211",
                        }
                    ],
                    "blocked": [],
                    "completed": [],
                },
                handle,
            )
        self.cli._handle_slash_command("/sync D:/repo")
        merged = self.repository.get_work_item(existing.id)
        audit_id = merged.merge_audit[-1]["id"]

        response = self.cli._handle_slash_command(f"/work rollback {existing.id} {audit_id}")

        self.assertIn("已回滚合并", response)
        self.assertIn("thread-rollback", response)
        self.assertIsNotNone(self.repository.find_work_item_by_source("codex", "thread-rollback"))


def _render_table(table) -> str:
    import io

    from rich.console import Console

    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=140)
    console.print(table)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
