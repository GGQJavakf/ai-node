"""JSON workflow repository for compatibility and tests."""
from __future__ import annotations

import json
import os

from ai_todo_assistant.domain.workflow import Evidence, WorkItem, WorkItemStatus, now_text


class JsonWorkflowRepository:
    def __init__(self, data_file: str = "data/workflow.json"):
        self.data_file = data_file
        self.work_items: list[WorkItem] = []
        self.evidence: list[Evidence] = []
        self._load()

    def save_work_item(self, item: WorkItem) -> WorkItem:
        item.updated_at = now_text()
        for index, existing in enumerate(self.work_items):
            if existing.id == item.id:
                self.work_items[index] = item
                self._save()
                return item
        self.work_items.append(item)
        self._save()
        return item

    def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return next((item for item in self.work_items if item.id == work_item_id), None)

    def find_work_item_by_source(self, source: str, source_ref: str) -> WorkItem | None:
        return next(
            (
                item for item in self.work_items
                if (
                    item.source == source and item.source_ref == source_ref
                ) or any(
                    ref.get("source") == source and ref.get("source_ref") == source_ref
                    for ref in item.source_refs
                )
            ),
            None,
        )

    def find_work_items_by_identity(self, identity: str) -> list[WorkItem]:
        return [
            item for item in self.work_items
            if identity in item.source_identities
            and item.status not in {WorkItemStatus.ARCHIVED.value}
        ]

    def list_work_items(self, include_closed: bool = False) -> list[WorkItem]:
        items = self.work_items
        if not include_closed:
            items = [
                item for item in items
                if item.status not in {WorkItemStatus.DONE.value, WorkItemStatus.ARCHIVED.value}
            ]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    def add_evidence(self, evidence: Evidence) -> Evidence:
        if not self.get_work_item(evidence.work_item_id):
            raise ValueError(f"未知工作项: {evidence.work_item_id}")
        self.evidence.append(evidence)
        self._save()
        return evidence

    def list_evidence(self, work_item_id: str) -> list[Evidence]:
        return [
            item for item in self.evidence
            if item.work_item_id == work_item_id
        ]

    def move_evidence(self, from_work_item_id: str, to_work_item_id: str) -> list[str]:
        moved: list[str] = []
        for item in self.evidence:
            if item.work_item_id == from_work_item_id:
                item.work_item_id = to_work_item_id
                moved.append(item.id)
        if moved:
            self._save()
        return moved

    def move_evidence_ids(self, evidence_ids: list[str], to_work_item_id: str) -> list[str]:
        evidence_id_set = {str(evidence_id) for evidence_id in evidence_ids}
        moved: list[str] = []
        for item in self.evidence:
            if item.id in evidence_id_set:
                item.work_item_id = to_work_item_id
                moved.append(item.id)
        if moved:
            self._save()
        return moved

    def _load(self) -> None:
        if not os.path.exists(self.data_file):
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        self.work_items = [
            WorkItem.from_dict(item)
            for item in payload.get("work_items", [])
            if isinstance(item, dict) and item.get("title")
        ]
        self.evidence = [
            Evidence.from_dict(item)
            for item in payload.get("evidence", [])
            if isinstance(item, dict) and item.get("work_item_id") and item.get("summary")
        ]

    def _save(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.data_file))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.data_file, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "work_items": [item.to_dict() for item in self.work_items],
                    "evidence": [item.to_dict() for item in self.evidence],
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
