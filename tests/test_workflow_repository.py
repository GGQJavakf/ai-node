import os
import tempfile
import unittest

import _path  # noqa: F401
from ai_todo_assistant.application.workflow import EvidenceService, WorkItemService
from ai_todo_assistant.domain.workflow import EvidenceType, WorkItemSource
from ai_todo_assistant.infrastructure.persistence import JsonWorkflowRepository, SQLiteWorkflowRepository


class WorkflowRepositoryContract:
    repository_cls = None

    def make_repository(self, path):
        return self.repository_cls(path)

    def test_create_and_list_work_items(self):
        repository = self.make_repository(self.path)
        service = WorkItemService(repository)

        item = service.create_manual(
            "实现个人工作助手",
            priority="high",
            next_action="补齐 WorkItem 持久化",
            project_path="D:/IdeaProjects/npki/ai/ai-node",
        )

        reloaded = self.make_repository(self.path)
        items = reloaded.list_work_items()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].id, item.id)
        self.assertEqual(items[0].source, WorkItemSource.MANUAL.value)
        self.assertEqual(items[0].priority, "high")

    def test_attach_and_list_evidence(self):
        repository = self.make_repository(self.path)
        item = WorkItemService(repository).create_manual("验证 workflow evidence")
        evidence_service = EvidenceService(repository)

        evidence_service.record(
            item.id,
            EvidenceType.COMMAND.value,
            "workflow tests passed",
            command="python -m unittest",
            success=True,
        )
        evidence_service.record(item.id, EvidenceType.NOTE.value, "人工确认边界")

        reloaded = self.make_repository(self.path)
        evidence = reloaded.list_evidence(item.id)

        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0].command, "python -m unittest")
        self.assertTrue(evidence[0].success)

    def test_work_item_source_identity_metadata_round_trips(self):
        repository = self.make_repository(self.path)
        item = WorkItemService(repository).create_manual("统一去重")
        item.source_identities = ["redmine:232211", "codex-thread:thread-1"]
        item.source_refs = [
            {"source": "redmine", "source_ref": "232211", "label": "Redmine 232211"},
            {"source": "codex", "source_ref": "thread-1", "label": "Codex thread"},
        ]
        item.merge_audit = [{"reason": "identity match", "absorbed_id": "old-id"}]
        item.merge_conflicts = ["project_path mismatch"]
        repository.save_work_item(item)

        reloaded = self.make_repository(self.path)
        saved = reloaded.get_work_item(item.id)

        self.assertEqual(saved.source_identities, ["redmine:232211", "codex-thread:thread-1"])
        self.assertEqual(saved.source_refs[0]["source_ref"], "232211")
        self.assertEqual(saved.merge_audit[0]["absorbed_id"], "old-id")
        self.assertEqual(saved.merge_conflicts, ["project_path mismatch"])


class TestSQLiteWorkflowRepository(WorkflowRepositoryContract, unittest.TestCase):
    repository_cls = SQLiteWorkflowRepository

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "todos.db")

    def tearDown(self):
        self.temp_dir.cleanup()


class TestJsonWorkflowRepository(WorkflowRepositoryContract, unittest.TestCase):
    repository_cls = JsonWorkflowRepository

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "workflow.json")

    def tearDown(self):
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
