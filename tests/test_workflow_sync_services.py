import os
import tempfile
import unittest
from datetime import datetime, timedelta

import _path  # noqa: F401
from ai_todo_assistant.application.workflow import WorkItemService, WorkflowSyncService
from ai_todo_assistant.application.workflow.codex_reports import CodexTaskReport
from ai_todo_assistant.domain.workflow import Evidence, EvidenceType, WorkItem, WorkItemStatus
from ai_todo_assistant.domain.workflow import SourceSnapshot
from ai_todo_assistant.infrastructure.persistence import SQLiteWorkflowRepository


class FakeGit:
    def snapshot(self, project_path):
        return SourceSnapshot(source="git", project_path=project_path, summary="branch=main, dirty=False")


class FakeOpenSpec:
    def list_changes(self, project_path):
        return SourceSnapshot(source="openspec", project_path=project_path, summary="1 active changes")

    def status(self, project_path, change):
        return SourceSnapshot(source="openspec", project_path=project_path, summary=f"{change}: ready")

    def apply_instructions(self, project_path, change):
        return SourceSnapshot(source="openspec", project_path=project_path, summary="apply ready")


class CloseoutGapOpenSpec(FakeOpenSpec):
    def list_changes(self, project_path):
        return SourceSnapshot(
            source="openspec",
            project_path=project_path,
            summary="1 active changes",
            command="openspec list --json",
            facts={
                "changes": [
                    {
                        "name": "add-closeout",
                        "tasks": {"complete": 3, "total": 3},
                        "archived": False,
                    }
                ]
            },
        )


class FakePlaybook:
    def redmine_issue(self, project_path, issue_id):
        return SourceSnapshot(
            source="playbook",
            project_path=project_path,
            summary=f"Redmine {issue_id} 敏感日志",
            facts={"id": int(issue_id), "subject": "敏感日志"},
        )

    def workspace_status(self, project_path):
        return SourceSnapshot(source="playbook", project_path=project_path, summary="0 workspace tasks")

    def closeout_gaps(self, project_path):
        return SourceSnapshot(source="playbook", project_path=project_path, summary="0 closeout gaps")


class CloseoutGapPlaybook(FakePlaybook):
    def closeout_gaps(self, project_path):
        return SourceSnapshot(
            source="playbook",
            project_path=project_path,
            summary="3 closeout gaps",
            command="playbook workspace task closeout --dry-run --output json",
            facts={
                "gaps": [
                    {
                        "name": "redmine",
                        "mr": {"iid": 42, "state": "merged"},
                        "redmine": {"id": 232211, "status": "open"},
                    },
                    {
                        "name": "validation",
                        "redmine": {"id": 232212, "status": "resolved"},
                        "validation": {"missing": True},
                    },
                    {
                        "name": "openspec",
                        "openspec": {"change": "add-closeout", "tasks_complete": True, "archived": False},
                    },
                ]
            },
        )


class UnavailableSnapshotPlaybook(FakePlaybook):
    def workspace_status(self, project_path):
        return SourceSnapshot(
            source="playbook",
            project_path=project_path,
            summary="playbook unavailable",
            command="playbook workspace task status --output json --full",
            success=False,
            error="playbook missing",
        )

    def closeout_gaps(self, project_path):
        return SourceSnapshot(
            source="playbook",
            project_path=project_path,
            summary="playbook unavailable",
            command="playbook workspace task closeout --dry-run --output json",
            success=False,
            error="closeout dry-run unavailable",
        )


class UnavailablePlaybook(FakePlaybook):
    def redmine_issue(self, project_path, issue_id):
        return SourceSnapshot(
            source="playbook",
            project_path=project_path,
            summary="playbook unavailable",
            command="playbook redmine pm issue",
            success=False,
            error="playbook missing",
        )


class TestWorkflowSyncServices(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteWorkflowRepository(os.path.join(self.temp_dir.name, "workflow.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_import_redmine_work_item_through_playbook_snapshot(self):
        service = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=FakeOpenSpec(),
            playbook=FakePlaybook(),
        )

        item = service.import_redmine("repo", "232211")

        self.assertEqual(item.source, "redmine")
        self.assertEqual(item.source_ref, "232211")
        self.assertEqual(item.title, "敏感日志")

    def test_redmine_identity_from_codex_fields_merges_with_redmine_import(self):
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-20T08:00:00+08:00",
            total_unfinished=3,
            unfinished=[
                {
                    "thread_id": "019ed87b-8dfe-7251-9b7a-d7a6a67cfb75",
                    "source_ref": "codex thread for Redmine 232211",
                    "title": "修复 Redmine 232211 日志问题",
                    "next_action": "继续 issue 232211 的验证",
                    "cwd": "repo",
                },
                {
                    "thread_id": "019ed87b-8dfe-7251-9b7a-d7a6a67cfb76",
                    "title": "Redmine 232211 后续 closeout",
                    "next_action": "继续 Redmine 232211",
                    "cwd": "repo",
                },
            ],
            blocked=[],
            completed=[],
        )

        imported = WorkItemService(self.repository).import_codex_report(report)
        redmine = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=FakeOpenSpec(),
            playbook=FakePlaybook(),
        ).import_redmine("repo", "232211")

        items = self.repository.list_work_items(include_closed=True)
        self.assertEqual(len(items), 1)
        self.assertEqual(imported.merged, 1)
        self.assertEqual(redmine.id, items[0].id)
        self.assertIn("redmine:232211", items[0].source_identities)
        self.assertIn("codex-thread:019ed87b-8dfe-7251-9b7a-d7a6a67cfb75", items[0].source_identities)
        self.assertIn("codex-thread:019ed87b-8dfe-7251-9b7a-d7a6a67cfb76", items[0].source_identities)

    def test_codex_import_extracts_openspec_mr_and_thread_identities(self):
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-20T08:00:00+08:00",
            total_unfinished=1,
            unfinished=[
                {
                    "thread_id": "019ed87b-8dfe-7251-9b7a-d7a6a67cfb75",
                    "title": "OpenSpec merge-duplicate-work-sources MR !42",
                    "next_action": "继续 openspec/changes/merge-duplicate-work-sources",
                    "cwd": "D:/repo",
                },
            ],
            blocked=[],
            completed=[],
        )

        WorkItemService(self.repository).import_codex_report(report)

        item = self.repository.list_work_items()[0]
        self.assertIn("codex-thread:019ed87b-8dfe-7251-9b7a-d7a6a67cfb75", item.source_identities)
        self.assertIn("openspec:merge-duplicate-work-sources", item.source_identities)
        self.assertIn("gitlab-mr:D:/repo:42", item.source_identities)

    def test_ambiguous_title_only_match_is_skipped_for_manual_confirmation(self):
        WorkItemService(self.repository).create_manual("修复工作流同步")
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-20T08:00:00+08:00",
            total_unfinished=1,
            unfinished=[
                {
                    "thread_id": "thread-without-stable-id",
                    "title": "修复工作流同步",
                    "next_action": "继续处理",
                    "cwd": "repo",
                }
            ],
            blocked=[],
            completed=[],
        )

        imported = WorkItemService(self.repository).import_codex_report(report)

        self.assertEqual(len(self.repository.list_work_items(include_closed=True)), 2)
        self.assertEqual(imported.skipped, 1)

    def test_merge_keeps_evidence_and_records_audit(self):
        existing = WorkItem(
            title="Codex 232211",
            source="codex",
            source_ref="thread-1",
            source_identities=["redmine:232211", "codex-thread:thread-1"],
        )
        existing = self.repository.save_work_item(existing)
        self.repository.add_evidence(
            Evidence(
                work_item_id=existing.id,
                evidence_type=EvidenceType.NOTE.value,
                summary="Codex 已定位",
                source="codex",
            )
        )

        redmine = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=FakeOpenSpec(),
            playbook=FakePlaybook(),
        ).import_redmine("repo", "232211")

        self.assertEqual(redmine.id, existing.id)
        self.assertIn("Codex 已定位", [item.summary for item in self.repository.list_evidence(redmine.id)])
        self.assertTrue(redmine.merge_audit)

    def test_manual_split_source_ref_recreates_separate_work_item(self):
        item = WorkItem(
            title="合并工作项",
            source="redmine",
            source_ref="232211",
            source_identities=["redmine:232211", "codex-thread:thread-1"],
            source_refs=[
                {"source": "redmine", "source_ref": "232211", "label": "Redmine 232211"},
                {"source": "codex", "source_ref": "thread-1", "label": "Codex thread"},
            ],
        )
        item = self.repository.save_work_item(item)

        split = WorkItemService(self.repository).split_source_ref(item.id, "codex", "thread-1", title="拆分 Codex thread")

        original = self.repository.get_work_item(item.id)
        items = self.repository.list_work_items(include_closed=True)
        self.assertEqual(len(items), 2)
        self.assertEqual(split.source, "codex")
        self.assertEqual(split.source_ref, "thread-1")
        self.assertNotIn("codex-thread:thread-1", original.source_identities)
        self.assertTrue(any("manual split" in evidence.summary for evidence in self.repository.list_evidence(split.id)))

    def test_multiple_identity_candidates_are_preserved_as_conflict(self):
        first = WorkItem(title="Redmine 232211 A", source="redmine", source_ref="232211-a")
        first.source_identities = ["redmine:232211"]
        second = WorkItem(title="Redmine 232211 B", source="manual")
        second.source_identities = ["redmine:232211"]
        self.repository.save_work_item(first)
        self.repository.save_work_item(second)
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-20T08:00:00+08:00",
            total_unfinished=1,
            unfinished=[
                {
                    "thread_id": "thread-conflict",
                    "title": "Redmine 232211 多候选冲突",
                    "next_action": "继续 Redmine 232211",
                    "cwd": "repo",
                }
            ],
            blocked=[],
            completed=[],
        )

        imported = WorkItemService(self.repository).import_codex_report(report)

        conflict_item = self.repository.find_work_item_by_source("codex", "thread-conflict")
        self.assertEqual(imported.skipped, 1)
        self.assertEqual(imported.merged, 0)
        self.assertIsNotNone(conflict_item)
        self.assertTrue(conflict_item.merge_conflicts)
        self.assertIn("命中多个工作项", imported.details[0])

    def test_preview_reports_multiple_identity_candidates_as_conflict(self):
        first = WorkItem(title="Redmine 232211 A", source="redmine", source_ref="232211-a")
        first.source_identities = ["redmine:232211"]
        second = WorkItem(title="Redmine 232211 B", source="manual")
        second.source_identities = ["redmine:232211"]
        self.repository.save_work_item(first)
        self.repository.save_work_item(second)
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-20T08:00:00+08:00",
            total_unfinished=1,
            unfinished=[
                {
                    "thread_id": "thread-conflict",
                    "title": "Redmine 232211 多候选冲突",
                    "next_action": "继续 Redmine 232211",
                    "cwd": "repo",
                }
            ],
            blocked=[],
            completed=[],
        )

        preview = WorkItemService(self.repository).preview_codex_report(report)

        self.assertEqual(preview.skipped, 1)
        self.assertEqual(preview.created, 1)
        self.assertIn("命中多个工作项", preview.details[0])
        self.assertEqual(len(self.repository.list_work_items(include_closed=True)), 2)

    def test_rollback_merge_restores_source_as_separate_work_item(self):
        existing = WorkItem(
            title="Redmine 232211",
            source="redmine",
            source_ref="232211",
            source_identities=["redmine:232211"],
        )
        existing = self.repository.save_work_item(existing)
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-20T08:00:00+08:00",
            total_unfinished=1,
            unfinished=[
                {
                    "thread_id": "thread-rollback",
                    "title": "Redmine 232211 Codex 后续",
                    "next_action": "继续 Redmine 232211",
                    "cwd": "repo",
                }
            ],
            blocked=[],
            completed=[],
        )
        WorkItemService(self.repository).import_codex_report(report)
        merged = self.repository.get_work_item(existing.id)
        audit_id = merged.merge_audit[-1]["id"]

        restored = WorkItemService(self.repository).rollback_merge(existing.id, audit_id)

        original = self.repository.get_work_item(existing.id)
        split = self.repository.find_work_item_by_source("codex", "thread-rollback")
        self.assertEqual(restored.id, split.id)
        self.assertNotIn("codex-thread:thread-rollback", original.source_identities)
        self.assertFalse(any(ref.get("source_ref") == "thread-rollback" for ref in original.source_refs))
        self.assertEqual(split.source, "codex")
        self.assertEqual(split.source_ref, "thread-rollback")
        self.assertTrue(any("rollback merge" in evidence.summary for evidence in self.repository.list_evidence(split.id)))

    def test_import_redmine_does_not_persist_when_playbook_snapshot_fails(self):
        service = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=FakeOpenSpec(),
            playbook=UnavailablePlaybook(),
        )

        with self.assertRaises(RuntimeError):
            service.import_redmine("repo", "232211")

        self.assertEqual(self.repository.list_work_items(include_closed=True), [])

    def test_sync_project_combines_git_openspec_and_playbook_snapshots(self):
        service = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=FakeOpenSpec(),
            playbook=FakePlaybook(),
        )

        snapshots = service.sync_project("repo", openspec_change="change-a")

        self.assertEqual([snapshot.source for snapshot in snapshots], [
            "git",
            "openspec",
            "playbook",
            "playbook",
            "openspec",
            "openspec",
        ])
        self.assertIn("apply", snapshots[-1].summary)
        items = self.repository.list_work_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_ref, "sync:repo")
        self.assertIsNotNone(items[0].last_synced_at)
        self.assertEqual(len(self.repository.list_evidence(items[0].id)), 6)

    def test_sync_project_records_closeout_gap_evidence_on_matching_work_items(self):
        redmine = WorkItem(title="Redmine 232211 closeout", source="redmine", source_ref="232211")
        redmine.source_identities = ["redmine:232211", "gitlab-mr:repo:42"]
        redmine.project_path = "repo"
        self.repository.save_work_item(redmine)
        validation = WorkItem(title="Redmine 232212 validation", source="redmine", source_ref="232212")
        validation.source_identities = ["redmine:232212"]
        validation.project_path = "repo"
        self.repository.save_work_item(validation)
        openspec = WorkItem(title="OpenSpec add-closeout", source="openspec", source_ref="add-closeout")
        openspec.source_identities = ["openspec:add-closeout"]
        openspec.project_path = "repo"
        self.repository.save_work_item(openspec)
        service = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=FakeOpenSpec(),
            playbook=CloseoutGapPlaybook(),
        )

        service.sync_project("repo")

        redmine_evidence = [item.summary for item in self.repository.list_evidence(redmine.id)]
        validation_evidence = [item.summary for item in self.repository.list_evidence(validation.id)]
        openspec_evidence = [item.summary for item in self.repository.list_evidence(openspec.id)]
        self.assertTrue(any("MR merged but Redmine not closed" in summary for summary in redmine_evidence))
        self.assertTrue(any("Redmine resolved but validation evidence missing" in summary for summary in validation_evidence))
        self.assertTrue(any("OpenSpec completed but not archived" in summary for summary in openspec_evidence))

    def test_sync_project_records_openspec_completion_archive_gap_from_openspec_snapshot(self):
        openspec = WorkItem(title="OpenSpec add-closeout", source="openspec", source_ref="add-closeout")
        openspec.source_identities = ["openspec:add-closeout"]
        openspec.project_path = "repo"
        openspec = self.repository.save_work_item(openspec)
        service = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=CloseoutGapOpenSpec(),
            playbook=FakePlaybook(),
        )

        service.sync_project("repo")

        summaries = [item.summary for item in self.repository.list_evidence(openspec.id)]
        self.assertTrue(any("OpenSpec completed but not archived" in summary for summary in summaries))

    def test_closeout_gap_evidence_is_idempotent_and_falls_back_to_project_context(self):
        service = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=FakeOpenSpec(),
            playbook=CloseoutGapPlaybook(),
        )

        service.sync_project("repo")
        service.sync_project("repo")

        context = self.repository.find_work_item_by_source("playbook", "sync:repo")
        evidence = [
            item.summary
            for item in self.repository.list_evidence(context.id)
            if item.summary.startswith("closeout gap:")
        ]
        self.assertEqual(len(evidence), 3)
        self.assertEqual(len(set(evidence)), 3)

    def test_sync_project_records_unavailable_connector_evidence_without_aborting(self):
        service = WorkflowSyncService(
            self.repository,
            git=FakeGit(),
            openspec=FakeOpenSpec(),
            playbook=UnavailableSnapshotPlaybook(),
        )

        snapshots = service.sync_project("repo")

        self.assertEqual(len(snapshots), 4)
        context = self.repository.find_work_item_by_source("playbook", "sync:repo")
        summaries = [item.summary for item in self.repository.list_evidence(context.id)]
        self.assertTrue(any("playbook unavailable" in summary for summary in summaries))
        self.assertTrue(any("closeout dry-run unavailable" in item.output_excerpt for item in self.repository.list_evidence(context.id)))

    def test_status_summary_marks_stale_sync_data(self):
        item = WorkItemService(self.repository).create_manual("旧同步工作项")
        item.last_synced_at = (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
        self.repository.save_work_item(item)

        summary = WorkItemService(self.repository).status_summary(stale_after_hours=24)

        self.assertIn("同步已过期", summary)
        self.assertIn("/sync", summary)

    def test_completion_signals_in_unfinished_and_blocked_close_codex_items(self):
        for thread_id, title in [
            ("thread-mr", "MR merged task"),
            ("thread-redmine", "Redmine resolved task"),
            ("thread-openspec", "OpenSpec archived task"),
            ("thread-playbook", "Playbook closeout task"),
            ("thread-validation", "Validation passed task"),
        ]:
            self.repository.save_work_item(WorkItem(title=title, source="codex", source_ref=thread_id))
        blocked = self.repository.find_work_item_by_source("codex", "thread-redmine")
        blocked.status = WorkItemStatus.BLOCKED.value
        self.repository.save_work_item(blocked)
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-21T08:00:00+08:00",
            total_unfinished=5,
            unfinished=[
                {
                    "thread_id": "thread-mr",
                    "title": "MR merged task",
                    "completion_signals": ["MR !42 merged"],
                },
                {
                    "thread_id": "thread-openspec",
                    "title": "OpenSpec archived task",
                    "summary": "OpenSpec change archived and tasks complete",
                },
                {
                    "thread_id": "thread-playbook",
                    "title": "Playbook closeout task",
                    "evidence": "Playbook closeout verified",
                },
                {
                    "thread_id": "thread-validation",
                    "title": "Validation passed task",
                    "next_action": "final validation passed with no follow-up",
                },
            ],
            blocked=[
                {
                    "thread_id": "thread-redmine",
                    "title": "Redmine resolved task",
                    "summary": "Redmine 232211 resolved",
                }
            ],
            completed=[],
        )

        result = WorkItemService(self.repository).import_codex_report(report)

        self.assertEqual(result.completed, 5)
        for thread_id in ["thread-mr", "thread-redmine", "thread-openspec", "thread-playbook", "thread-validation"]:
            item = self.repository.find_work_item_by_source("codex", thread_id)
            self.assertEqual(item.status, WorkItemStatus.DONE.value)
            self.assertTrue(self.repository.list_evidence(item.id))

    def test_done_items_become_reopen_candidates_without_status_regression(self):
        done = WorkItem(title="已闭环但又出现", source="codex", source_ref="thread-done")
        done.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(done)
        strong_done = WorkItem(title="已闭环且有完成证据", source="codex", source_ref="thread-strong")
        strong_done.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(strong_done)
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-21T08:00:00+08:00",
            total_unfinished=2,
            unfinished=[
                {"thread_id": "thread-done", "title": "已闭环但又出现", "next_action": "继续处理"},
                {
                    "thread_id": "thread-strong",
                    "title": "已闭环且有完成证据",
                    "completion_signals": ["writeback complete"],
                },
            ],
            blocked=[],
            completed=[],
        )

        result = WorkItemService(self.repository).import_codex_report(report)

        self.assertEqual(result.reopen_candidates, 1)
        self.assertEqual(result.unchanged, 2)
        self.assertIn("reopen candidate", " ".join(result.details))
        self.assertEqual(self.repository.find_work_item_by_source("codex", "thread-done").status, WorkItemStatus.DONE.value)
        self.assertEqual(self.repository.find_work_item_by_source("codex", "thread-strong").status, WorkItemStatus.DONE.value)
        self.assertTrue(self.repository.list_evidence(strong_done.id))

    def test_preview_completion_signal_detection_does_not_write(self):
        self.repository.save_work_item(WorkItem(title="待预览闭环", source="codex", source_ref="thread-preview"))
        done = WorkItem(title="预览 reopen 候选", source="codex", source_ref="thread-reopen")
        done.status = WorkItemStatus.DONE.value
        self.repository.save_work_item(done)
        report = CodexTaskReport(
            path="report.json",
            summary_path=None,
            generated_at="2026-06-21T08:00:00+08:00",
            total_unfinished=2,
            unfinished=[
                {
                    "thread_id": "thread-preview",
                    "title": "待预览闭环",
                    "completion_signals": ["MR !42 merged"],
                },
                {"thread_id": "thread-reopen", "title": "预览 reopen 候选"},
            ],
            blocked=[],
            completed=[],
        )

        result = WorkItemService(self.repository).preview_codex_report(report)

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.reopen_candidates, 1)
        self.assertEqual(
            self.repository.find_work_item_by_source("codex", "thread-preview").status,
            WorkItemStatus.ACTIVE.value,
        )
        self.assertEqual(self.repository.list_evidence(self.repository.find_work_item_by_source("codex", "thread-preview").id), [])


if __name__ == "__main__":
    unittest.main()
