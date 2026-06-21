"""Workflow application services."""
from __future__ import annotations

import json
import os
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ai_todo_assistant.application.ports.workflow_repository import WorkflowRepository
from ai_todo_assistant.domain.workflow import Evidence, EvidenceType, SourceSnapshot, WorkItem, WorkItemSource, WorkItemStatus, now_text
from ai_todo_assistant.infrastructure.connectors import GitConnector, OpenSpecConnector, PlaybookConnector


@dataclass
class CodexImportResult:
    items: list[WorkItem] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    created: int = 0
    updated: int = 0
    merged: int = 0
    skipped: int = 0
    completed: int = 0
    blocked: int = 0
    reactivated: int = 0
    unchanged: int = 0

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def summary_text(self) -> str:
        return (
            f"本次闭环 {self.completed} 项，阻塞 {self.blocked} 项，"
            f"恢复 {self.reactivated} 项，未变化 {self.unchanged} 项；"
            f"导入: 新建 {self.created} / 更新 {self.updated} / 合并 {self.merged} / 跳过 {self.skipped} "
            f"(created={self.created}, updated={self.updated}, merged={self.merged}, skipped={self.skipped}, "
            f"completed={self.completed}, blocked={self.blocked}, reactivated={self.reactivated}, unchanged={self.unchanged})"
        )


class WorkItemService:
    def __init__(self, repository: WorkflowRepository):
        self.repository = repository

    def create_manual(
        self,
        title: str,
        priority: str = "medium",
        next_action: str = "",
        project_path: str = "",
    ) -> WorkItem:
        return self.repository.save_work_item(
            WorkItem(
                title=title,
                source=WorkItemSource.MANUAL.value,
                priority=priority,
                next_action=next_action,
                project_path=project_path,
            )
        )

    def import_from_snapshot(self, source: str, source_ref: str, title: str, snapshot_summary: str, project_path: str = "") -> WorkItem:
        identity = f"{source}:{source_ref}" if source_ref else ""
        existing = self.repository.find_work_item_by_source(source, source_ref)
        if not existing and identity:
            matches = self.repository.find_work_items_by_identity(identity)
            existing = matches[0] if len(matches) == 1 else None
        item = existing or WorkItem(title=title, source=source, source_ref=source_ref)
        survivor_before = item.to_dict() if existing else None
        item.title = title.strip() or item.title
        item.sync_summary = snapshot_summary
        item.project_path = project_path or item.project_path
        item.last_synced_at = now_text()
        _add_identity(item, identity)
        _add_source_ref(item, source, source_ref)
        if existing and not (existing.source == source and existing.source_ref == source_ref):
            _record_merge_audit(
                item,
                source,
                source_ref,
                "identity",
                survivor_before=survivor_before,
                separated_item=_separated_work_item_snapshot(
                    title=title,
                    source=source,
                    source_ref=source_ref,
                    source_identities=[identity] if identity else [],
                    source_refs=[{"source": source, "source_ref": source_ref, "label": ""}],
                    status=item.status,
                    priority=item.priority,
                    next_action=item.next_action,
                    project_path=project_path,
                    sync_summary=snapshot_summary,
                ),
                moved_identities=_new_identities(survivor_before, [identity] if identity else []),
                moved_source_refs=_new_source_refs(
                    survivor_before,
                    [{"source": source, "source_ref": source_ref, "label": ""}],
                ),
            )
        return self.repository.save_work_item(item)

    def import_codex_report(self, report) -> CodexImportResult:
        result = CodexImportResult()
        for entry, target_status in _ordered_codex_entries(report):
            source_ref = _codex_source_ref(entry)
            title = _codex_title(entry, source_ref, target_status)
            summary = _codex_snapshot_summary(entry, report, target_status)
            identities = _codex_identities(entry, source_ref)
            existing = self.repository.find_work_item_by_source(WorkItemSource.CODEX.value, source_ref)
            matched_by_identity = False
            survivor_before = None
            merge_conflicts: list[str] = []
            if not existing:
                identity_matches = _identity_matches(self.repository, identities)
                if len(identity_matches) == 1:
                    existing = identity_matches[0]
                    matched_by_identity = True
                    survivor_before = existing.to_dict()
                elif len(identity_matches) > 1:
                    result.skipped += 1
                    conflict = (
                        f"冲突: {title} | {','.join(identities)} "
                        f"命中多个工作项，未自动合并"
                    )
                    result.details.append(conflict)
                    merge_conflicts.append(conflict)
                elif _has_title_collision(self.repository, title):
                    result.skipped += 1
                    result.details.append(f"跳过: {title} | 标题冲突，未自动合并")
            previous_status = existing.status if existing else None
            item = existing or WorkItem(title=title, source=WorkItemSource.CODEX.value, source_ref=source_ref)
            item.title = title.strip() or item.title
            item.sync_summary = summary
            item.project_path = str(entry.get("cwd") or entry.get("project_path") or item.project_path or "")
            item.last_synced_at = now_text()
            for identity in identities:
                _add_identity(item, identity)
            _add_source_ref(item, WorkItemSource.CODEX.value, source_ref, "Codex thread")
            for conflict in merge_conflicts:
                if conflict not in item.merge_conflicts:
                    item.merge_conflicts.append(conflict)
            if target_status != WorkItemStatus.DONE.value:
                item.next_action = str(entry.get("next_action") or item.next_action)

            item.status = _next_codex_status(previous_status, target_status)
            if previous_status == WorkItemStatus.DONE.value and target_status != WorkItemStatus.DONE.value:
                result.details.append(f"保留 done: {item.title} | Codex 报告仍列为未完成/阻塞")
            saved = self.repository.save_work_item(item)
            if matched_by_identity:
                result.merged += 1
                matched_identity = next(
                    (
                        identity for identity in identities
                        if identity.startswith("redmine:") and identity in saved.source_identities
                    ),
                    "",
                ) or next((identity for identity in identities if identity in saved.source_identities), "")
                detail_suffix = f" | {matched_identity}" if matched_identity else ""
                result.details.append(f"合并: {title}{detail_suffix}")
                _record_merge_audit(
                    saved,
                    WorkItemSource.CODEX.value,
                    source_ref,
                    "identity",
                    survivor_before=survivor_before,
                    separated_item=_separated_work_item_snapshot(
                        title=title,
                        source=WorkItemSource.CODEX.value,
                        source_ref=source_ref,
                        source_identities=identities,
                        source_refs=[
                            {
                                "source": WorkItemSource.CODEX.value,
                                "source_ref": source_ref,
                                "label": "Codex thread",
                            }
                        ],
                        status=target_status,
                        priority=saved.priority,
                        next_action=str(entry.get("next_action") or ""),
                        project_path=str(entry.get("cwd") or entry.get("project_path") or ""),
                        sync_summary=summary,
                    ),
                    moved_identities=_new_identities(survivor_before, identities),
                    moved_source_refs=_new_source_refs(
                        survivor_before,
                        [
                            {
                                "source": WorkItemSource.CODEX.value,
                                "source_ref": source_ref,
                                "label": "Codex thread",
                            }
                        ],
                    ),
                )
                self.repository.save_work_item(saved)
            elif existing:
                result.updated += 1
            else:
                result.created += 1
            if target_status == WorkItemStatus.DONE.value:
                self._record_codex_completion_evidence(saved, entry, report)
            _count_codex_outcome(result, previous_status, saved.status)
            result.items.append(saved)
        return result

    def rollback_merge(self, work_item_id: str, audit_id: str) -> WorkItem:
        item = self.repository.get_work_item(work_item_id)
        if not item:
            raise ValueError(f"未知工作项: {work_item_id}")
        audit = _find_merge_audit(item, audit_id)
        if not audit:
            raise ValueError(f"未知合并记录: {audit_id}")
        separated_data = audit.get("separated_item")
        survivor_before = audit.get("survivor_before")
        if not isinstance(separated_data, dict) or not isinstance(survivor_before, dict):
            raise ValueError(f"合并记录缺少完整回滚数据: {audit_id}")

        restored_original = WorkItem.from_dict({**survivor_before, "id": item.id})
        restored_original.merge_audit = list(item.merge_audit)
        restored_original.merge_audit.append(
            {
                "id": str(uuid.uuid4()),
                "action": "rollback",
                "rollback_of": audit_id,
                "source": str(audit.get("source") or ""),
                "source_ref": str(audit.get("source_ref") or ""),
                "reason": "manual rollback",
                "merged_at": now_text(),
            }
        )
        self.repository.save_work_item(restored_original)

        split_item = WorkItem.from_dict(separated_data)
        saved_split = self.repository.save_work_item(split_item)
        moved_evidence_ids = _list_text(audit.get("moved_evidence_ids"))
        if moved_evidence_ids:
            self.repository.move_evidence_ids(moved_evidence_ids, saved_split.id)
        self.repository.add_evidence(
            Evidence(
                work_item_id=saved_split.id,
                evidence_type=EvidenceType.NOTE.value,
                summary=f"rollback merge {audit_id} from {item.id}",
                source=str(audit.get("source") or ""),
            )
        )
        return saved_split

    def preview_codex_report(self, report) -> CodexImportResult:
        result = CodexImportResult()
        for entry, target_status in _ordered_codex_entries(report):
            source_ref = _codex_source_ref(entry)
            title = _codex_title(entry, source_ref, target_status)
            summary = _codex_snapshot_summary(entry, report, target_status)
            identities = _codex_identities(entry, source_ref)
            existing = self.repository.find_work_item_by_source(WorkItemSource.CODEX.value, source_ref)
            matched_by_identity = False
            merge_conflicts: list[str] = []
            if not existing:
                identity_matches = _identity_matches(self.repository, identities)
                if len(identity_matches) == 1:
                    existing = identity_matches[0]
                    matched_by_identity = True
                elif len(identity_matches) > 1:
                    result.skipped += 1
                    conflict = (
                        f"冲突: {title} | {','.join(identities)} "
                        f"命中多个工作项，未自动合并"
                    )
                    result.details.append(conflict)
                    merge_conflicts.append(conflict)
                elif _has_title_collision(self.repository, title):
                    result.skipped += 1
                    result.details.append(f"跳过: {title} | 标题冲突，未自动合并")
            previous_status = existing.status if existing else None
            item = _clone_work_item(existing) if existing else WorkItem(title=title, source=WorkItemSource.CODEX.value, source_ref=source_ref)
            item.title = title.strip() or item.title
            item.sync_summary = summary
            item.project_path = str(entry.get("cwd") or entry.get("project_path") or item.project_path or "")
            item.last_synced_at = now_text()
            for identity in identities:
                _add_identity(item, identity)
            _add_source_ref(item, WorkItemSource.CODEX.value, source_ref, "Codex thread")
            for conflict in merge_conflicts:
                if conflict not in item.merge_conflicts:
                    item.merge_conflicts.append(conflict)
            if target_status != WorkItemStatus.DONE.value:
                item.next_action = str(entry.get("next_action") or item.next_action)
            item.status = _next_codex_status(previous_status, target_status)
            if previous_status == WorkItemStatus.DONE.value and target_status != WorkItemStatus.DONE.value:
                result.details.append(f"保留 done: {item.title} | Codex 报告仍列为未完成/阻塞")
            if matched_by_identity:
                result.merged += 1
                matched_identity = next(
                    (
                        identity for identity in identities
                        if identity.startswith("redmine:") and identity in item.source_identities
                    ),
                    "",
                ) or next((identity for identity in identities if identity in item.source_identities), "")
                detail_suffix = f" | {matched_identity}" if matched_identity else ""
                result.details.append(f"合并: {title}{detail_suffix}")
            elif existing:
                result.updated += 1
            else:
                result.created += 1
            _count_codex_outcome(result, previous_status, item.status)
            result.items.append(item)
        return result

    def split_source_ref(self, work_item_id: str, source: str, source_ref: str, title: str = "") -> WorkItem:
        item = self.repository.get_work_item(work_item_id)
        if not item:
            raise ValueError(f"未知工作项: {work_item_id}")
        matching_refs = [
            ref for ref in item.source_refs
            if ref.get("source") == source and ref.get("source_ref") == source_ref
        ]
        if not matching_refs and not (item.source == source and item.source_ref == source_ref):
            raise ValueError(f"工作项不包含来源: {source}:{source_ref}")

        split_identities = _identities_for_source_ref(source, source_ref, item.source_identities)
        split_item = WorkItem(
            title=_split_title(title, matching_refs, source, source_ref),
            source=source,
            source_ref=source_ref,
            source_identities=split_identities,
            source_refs=matching_refs or [{"source": source, "source_ref": source_ref, "label": ""}],
            status=item.status,
            priority=item.priority,
            next_action=item.next_action,
            project_path=item.project_path,
            sync_summary=item.sync_summary,
        )
        item.source_refs = [
            ref for ref in item.source_refs
            if not (ref.get("source") == source and ref.get("source_ref") == source_ref)
        ]
        item.source_identities = [
            identity for identity in item.source_identities
            if identity not in split_identities
        ]
        _record_merge_audit(item, source, source_ref, "manual split source removed")
        saved_original = self.repository.save_work_item(item)
        saved_split = self.repository.save_work_item(split_item)
        self.repository.add_evidence(
            Evidence(
                work_item_id=saved_split.id,
                evidence_type=EvidenceType.NOTE.value,
                summary=f"manual split from {saved_original.id}: {source}:{source_ref}",
                source=source,
            )
        )
        return saved_split

    def _record_codex_completion_evidence(self, item: WorkItem, entry, report) -> None:
        existing_summaries = {
            _normalize_evidence_summary(evidence.summary)
            for evidence in self.repository.list_evidence(item.id)
            if evidence.source == WorkItemSource.CODEX.value
            and evidence.evidence_type == EvidenceType.SNAPSHOT.value
        }
        for signal in _codex_completion_signals(entry, report):
            evidence_summary = f"Codex completed {item.source_ref}: {signal}"
            normalized = _normalize_evidence_summary(evidence_summary)
            if normalized in existing_summaries:
                continue
            self.repository.add_evidence(
                Evidence(
                    work_item_id=item.id,
                    evidence_type=EvidenceType.SNAPSHOT.value,
                    summary=evidence_summary,
                    output_excerpt=_codex_evidence_context(entry, report),
                    source=WorkItemSource.CODEX.value,
                    success=True,
                )
            )
            existing_summaries.add(normalized)

    def list_active(self) -> list[WorkItem]:
        return self.repository.list_work_items(include_closed=False)

    def status_summary(self, stale_after_hours: int = 24) -> str:
        items = self.list_active()
        if not items:
            return "当前没有活动工作项"
        lines = ["工作项状态", "─" * 80]
        for index, item in enumerate(_rank_work_items(items), 1):
            stale = _is_stale(item.last_synced_at, stale_after_hours)
            stale_text = " [同步已过期，建议 /sync]" if stale else ""
            source = _source_context(item)
            next_action = f" 下一步:{item.next_action}" if item.next_action else ""
            conflicts = f" 冲突:{'; '.join(item.merge_conflicts)}" if item.merge_conflicts else ""
            lines.append(
                f"  {index}. [{item.status}/{item.priority}] {item.title} | {source} | {item.project_path or '-'}{next_action}{conflicts}{stale_text}"
            )
        lines.append("─" * 80)
        return "\n".join(lines)

    def conflict_summary(self) -> str:
        items = [
            item for item in self.repository.list_work_items(include_closed=True)
            if item.merge_conflicts and item.status != WorkItemStatus.ARCHIVED.value
        ]
        if not items:
            return "冲突工作项\n\n  暂无需要人工处理的来源冲突"
        lines = ["冲突工作项", "─" * 80]
        for index, item in enumerate(_rank_work_items(items), 1):
            source = _source_context(item)
            lines.append(f"  {index}. {item.id[:8]} [{item.status}] {item.title} | {source}")
            for conflict in item.merge_conflicts:
                lines.append(f"     - {conflict}")
            lines.append(f"     处理: /work show {item.id} 或 /work split <work-id> <source> <source-ref>")
        lines.append("─" * 80)
        return "\n".join(lines)


class EvidenceService:
    def __init__(self, repository: WorkflowRepository):
        self.repository = repository

    def record(
        self,
        work_item_id: str,
        evidence_type: str,
        summary: str,
        command: str = "",
        output_excerpt: str = "",
        success: bool | None = None,
        source: str = "",
    ) -> Evidence:
        return self.repository.add_evidence(
            Evidence(
                work_item_id=work_item_id,
                evidence_type=evidence_type,
                summary=summary,
                command=command,
                output_excerpt=output_excerpt,
                success=success,
                source=source,
            )
        )

    def summarize(self, work_item_id: str) -> str:
        evidence = self.repository.list_evidence(work_item_id)
        if not evidence:
            return "该工作项暂无证据"
        grouped: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            grouped[item.evidence_type].append(item)
        lines = ["证据摘要", "─" * 80]
        for evidence_type in sorted(grouped):
            lines.append(f"{evidence_type}:")
            for item in grouped[evidence_type]:
                command = f" `{item.command}`" if item.command else ""
                outcome = "" if item.success is None else (" 通过" if item.success else " 失败")
                lines.append(f"  - {item.summary}{command}{outcome}")
        lines.append("─" * 80)
        return "\n".join(lines)

    def timeline(self, work_item_id: str) -> str:
        evidence = sorted(self.repository.list_evidence(work_item_id), key=lambda item: item.created_at)
        if not evidence:
            return "证据时间线\n\n  该工作项暂无证据"
        lines = ["证据时间线", "─" * 80]
        for item in evidence:
            source = item.source or "-"
            if item.success is True:
                outcome = "通过"
            elif item.success is False:
                outcome = "失败"
            else:
                outcome = "未知"
            command = f" | {item.command}" if item.command else ""
            lines.append(
                f"  {item.created_at} [{item.evidence_type}/{source}/{outcome}] {item.summary}{command}"
            )
        lines.append("─" * 80)
        return "\n".join(lines)


class ContinueService:
    def __init__(self, repository: WorkflowRepository):
        self.repository = repository

    def recommend(self) -> str:
        items = [item for item in self.repository.list_work_items(False) if item.next_action]
        if not items:
            return "当前没有带下一步的活动工作项，建议先 /work add 或 /work import redmine <id>"
        item = _rank_work_items(items)[0]
        return f"推荐下一步: {item.next_action}\n原因: {item.title} 是当前最高优先级活动工作项。"


class DailyReviewService:
    def __init__(self, repository: WorkflowRepository):
        self.repository = repository

    def start_day(self) -> str:
        items = _rank_work_items(self.repository.list_work_items(False))
        if not items:
            return "今日启动\n\n暂无活动工作项。"
        lines = ["今日启动", "", "推荐关注:"]
        for item in items[:5]:
            action = item.next_action or "同步状态并明确下一步"
            lines.append(f"- Recommendation: {item.title} -> {action}")
        return "\n".join(lines)

    def review_day(self) -> str:
        all_items = self.repository.list_work_items(include_closed=True)
        if not any(self.repository.list_evidence(item.id) for item in all_items):
            return "今日复盘\n\n暂无证据记录。建议先运行 /sync 或 /work evidence add <work-id>。"
        completed = [item for item in all_items if item.status == WorkItemStatus.DONE.value]
        blocked = [item for item in all_items if item.status == WorkItemStatus.BLOCKED.value]
        active = [
            item for item in all_items
            if item.status not in {WorkItemStatus.DONE.value, WorkItemStatus.BLOCKED.value}
        ]
        lines = ["今日复盘", "", "Completed facts:"]
        lines.extend(f"- {item.title}" for item in completed[:10])
        lines.append("")
        lines.append("In progress:")
        lines.extend(f"- {item.title}: {item.next_action or '待明确下一步'}" for item in active[:10])
        lines.append("")
        lines.append("Blockers:")
        lines.extend(f"- {item.title}: {item.next_action or '等待外部解除阻塞'}" for item in blocked[:10])
        lines.append("")
        lines.append("Recommended follow-ups:")
        for item in (blocked + active)[:5]:
            lines.append(f"- Recommendation: {item.next_action or '同步并补充证据'}")
        return "\n".join(lines)


class WorkflowSyncService:
    def __init__(
        self,
        repository: WorkflowRepository,
        git: GitConnector | None = None,
        openspec: OpenSpecConnector | None = None,
        playbook: PlaybookConnector | None = None,
    ):
        self.repository = repository
        self.git = git or GitConnector()
        self.openspec = openspec or OpenSpecConnector()
        self.playbook = playbook or PlaybookConnector()

    def sync_project(self, project_path: str, openspec_change: str | None = None) -> list:
        snapshots = [
            self.git.snapshot(project_path),
            self.openspec.list_changes(project_path),
            self.playbook.workspace_status(project_path),
            self.playbook.closeout_gaps(project_path),
        ]
        if openspec_change:
            snapshots.append(self.openspec.status(project_path, openspec_change))
            snapshots.append(self.openspec.apply_instructions(project_path, openspec_change))
        self._persist_project_sync(project_path, snapshots)
        return snapshots

    def import_redmine(self, project_path: str, issue_id: str) -> WorkItem:
        snapshot = self.playbook.redmine_issue(project_path, issue_id)
        if not snapshot.success:
            detail = snapshot.error or snapshot.summary or "Playbook Redmine snapshot unavailable"
            raise RuntimeError(f"无法导入 Redmine {issue_id}: {detail}")
        facts = snapshot.facts if isinstance(snapshot.facts, dict) else {}
        title = str(facts.get("subject") or facts.get("title") or f"Redmine {issue_id}")
        return WorkItemService(self.repository).import_from_snapshot(
            source=WorkItemSource.REDMINE.value,
            source_ref=issue_id,
            title=title,
            snapshot_summary=snapshot.summary,
            project_path=project_path,
        )

    def _persist_project_sync(self, project_path: str, snapshots: list[SourceSnapshot]) -> None:
        if not snapshots:
            return
        normalized_path = project_path or os.getcwd()
        source_ref = f"sync:{normalized_path}"
        summaries = [f"{snapshot.source}: {snapshot.summary or snapshot.error}" for snapshot in snapshots]
        sync_summary = "; ".join(summary for summary in summaries if summary)
        context = self.repository.find_work_item_by_source(WorkItemSource.PLAYBOOK.value, source_ref)
        if not context:
            context = WorkItem(
                title=f"项目同步上下文: {os.path.basename(os.path.abspath(normalized_path)) or normalized_path}",
                source=WorkItemSource.PLAYBOOK.value,
                source_ref=source_ref,
                priority="low",
                next_action="根据最新同步快照确定下一步",
                project_path=normalized_path,
            )
        context.sync_summary = sync_summary
        context.last_synced_at = now_text()
        saved_context = self.repository.save_work_item(context)
        for snapshot in snapshots:
            facts_excerpt = _facts_excerpt(snapshot)
            self.repository.add_evidence(
                Evidence(
                    work_item_id=saved_context.id,
                    evidence_type=EvidenceType.SNAPSHOT.value,
                    summary=f"{snapshot.source}: {snapshot.summary or snapshot.error or 'snapshot captured'}",
                    command=snapshot.command,
                    output_excerpt=facts_excerpt,
                    success=snapshot.success,
                    source=snapshot.source,
                )
            )
        for item in self.repository.list_work_items(include_closed=False):
            if item.id == saved_context.id:
                continue
            if item.project_path and os.path.abspath(item.project_path) == os.path.abspath(normalized_path):
                item.last_synced_at = saved_context.last_synced_at
                item.sync_summary = sync_summary
                self.repository.save_work_item(item)


def _rank_work_items(items: list[WorkItem]) -> list[WorkItem]:
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {WorkItemStatus.ACTIVE.value: 0, WorkItemStatus.BLOCKED.value: 1}
    return sorted(
        items,
        key=lambda item: (
            status_rank.get(item.status, 2),
            priority_rank.get(item.priority, 1),
            item.updated_at,
        ),
    )


def _source_context(item: WorkItem) -> str:
    primary = f"{item.source}:{item.source_ref}" if item.source_ref else item.source
    extra_refs = [
        f"{ref.get('source')}:{ref.get('source_ref')}"
        for ref in item.source_refs
        if ref.get("source") and ref.get("source_ref")
        and not (ref.get("source") == item.source and ref.get("source_ref") == item.source_ref)
    ]
    identities = [identity for identity in item.source_identities if identity not in extra_refs]
    details = list(dict.fromkeys(extra_refs + identities))
    if not details:
        return primary
    return f"{primary} refs={','.join(details[:4])}"


def _add_identity(item: WorkItem, identity: str) -> None:
    identity = str(identity or "").strip()
    if identity and identity not in item.source_identities:
        item.source_identities.append(identity)


def _add_source_ref(item: WorkItem, source: str, source_ref: str, label: str = "") -> None:
    source = str(source or "").strip()
    source_ref = str(source_ref or "").strip()
    if not source or not source_ref:
        return
    if any(ref.get("source") == source and ref.get("source_ref") == source_ref for ref in item.source_refs):
        return
    item.source_refs.append({"source": source, "source_ref": source_ref, "label": label})


def _record_merge_audit(
    item: WorkItem,
    source: str,
    source_ref: str,
    reason: str,
    survivor_before: dict | None = None,
    separated_item: dict | None = None,
    moved_identities: list[str] | None = None,
    moved_source_refs: list[dict[str, str]] | None = None,
    moved_evidence_ids: list[str] | None = None,
) -> None:
    for existing in item.merge_audit:
        if (
            existing.get("source") == source
            and existing.get("source_ref") == source_ref
            and existing.get("reason") == reason
        ):
            if not existing.get("id"):
                existing["id"] = f"audit-{uuid.uuid4().hex[:12]}"
            if survivor_before and not existing.get("survivor_before"):
                existing["survivor_before"] = survivor_before
            if separated_item and not existing.get("separated_item"):
                existing["separated_item"] = separated_item
            existing["moved_identities"] = list(moved_identities or existing.get("moved_identities") or [])
            existing["moved_source_refs"] = list(moved_source_refs or existing.get("moved_source_refs") or [])
            existing["moved_evidence_ids"] = list(moved_evidence_ids or existing.get("moved_evidence_ids") or [])
            return
    event = {
        "id": f"audit-{uuid.uuid4().hex[:12]}",
        "source": source,
        "source_ref": source_ref,
        "reason": reason,
        "merged_at": now_text(),
        "moved_identities": list(moved_identities or []),
        "moved_source_refs": list(moved_source_refs or []),
        "moved_evidence_ids": list(moved_evidence_ids or []),
    }
    if survivor_before:
        event["survivor_before"] = survivor_before
    if separated_item:
        event["separated_item"] = separated_item
    item.merge_audit.append(event)


def _clone_work_item(item: WorkItem | None) -> WorkItem | None:
    return WorkItem.from_dict(item.to_dict()) if item else None


def _find_merge_audit(item: WorkItem, audit_id: str) -> dict | None:
    audit_id = str(audit_id or "").strip()
    return next((event for event in item.merge_audit if str(event.get("id") or "") == audit_id), None)


def _separated_work_item_snapshot(
    title: str,
    source: str,
    source_ref: str,
    source_identities: list[str],
    source_refs: list[dict[str, str]],
    status: str,
    priority: str,
    next_action: str,
    project_path: str,
    sync_summary: str,
) -> dict:
    return WorkItem(
        title=title or f"{source}:{source_ref}",
        source=source,
        source_ref=source_ref,
        source_identities=source_identities,
        source_refs=source_refs,
        status=status,
        priority=priority,
        next_action=next_action,
        project_path=project_path,
        sync_summary=sync_summary,
    ).to_dict()


def _new_identities(before: dict | None, identities: list[str]) -> list[str]:
    before_identities = set(_list_text((before or {}).get("source_identities")))
    return [identity for identity in _list_text(identities) if identity not in before_identities]


def _new_source_refs(before: dict | None, refs: list[dict[str, str]]) -> list[dict[str, str]]:
    before_refs = {
        (str(ref.get("source") or ""), str(ref.get("source_ref") or ""))
        for ref in ((before or {}).get("source_refs") or [])
        if isinstance(ref, dict)
    }
    return [
        dict(ref)
        for ref in refs
        if (str(ref.get("source") or ""), str(ref.get("source_ref") or "")) not in before_refs
    ]


def _list_text(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _split_title(title: str, refs: list[dict[str, str]], source: str, source_ref: str) -> str:
    if title.strip():
        return title.strip()
    if refs and refs[0].get("label"):
        return str(refs[0]["label"])
    return f"{source}:{source_ref}"


def _identities_for_source_ref(source: str, source_ref: str, identities: list[str]) -> list[str]:
    candidates = {f"{source}:{source_ref}"}
    if source == WorkItemSource.CODEX.value:
        candidates.add(f"codex-thread:{source_ref}")
    if source == WorkItemSource.REDMINE.value:
        candidates.add(f"redmine:{source_ref}")
    return [identity for identity in identities if identity in candidates]


def _identity_matches(repository: WorkflowRepository, identities: list[str]) -> list[WorkItem]:
    matches: dict[str, WorkItem] = {}
    for identity in identities:
        for item in repository.find_work_items_by_identity(identity):
            if item.status != WorkItemStatus.ARCHIVED.value:
                matches[item.id] = item
    return list(matches.values())


def _has_title_collision(repository: WorkflowRepository, title: str) -> bool:
    normalized = _normalize_evidence_summary(title).lower()
    if not normalized:
        return False
    return any(
        _normalize_evidence_summary(item.title).lower() == normalized
        for item in repository.list_work_items(include_closed=True)
    )


def _ordered_codex_entries(report) -> list[tuple[dict, str]]:
    ordered: list[tuple[dict, str]] = []
    seen: set[str] = set()
    sections = [
        (list(getattr(report, "completed", [])), WorkItemStatus.DONE.value),
        (list(getattr(report, "blocked", [])), WorkItemStatus.BLOCKED.value),
        (list(getattr(report, "unfinished", [])), WorkItemStatus.ACTIVE.value),
    ]
    for entries, status in sections:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source_ref = _codex_source_ref(entry)
            if source_ref in seen:
                continue
            seen.add(source_ref)
            ordered.append((entry, status))
    return ordered


def _codex_source_ref(entry: dict) -> str:
    return str(entry.get("thread_id") or entry.get("id") or entry.get("title") or entry.get("name") or "")


def _codex_identities(entry: dict, source_ref: str) -> list[str]:
    identities: list[str] = []
    thread_id = str(entry.get("thread_id") or entry.get("id") or "").strip()
    if thread_id:
        identities.append(f"codex-thread:{thread_id}")
    for issue_id in _redmine_issue_ids(entry):
        identities.append(f"redmine:{issue_id}")
    text = _entry_identity_text(entry)
    for change_id in _openspec_change_ids(text):
        identities.append(f"openspec:{change_id}")
    for mr_id in _gitlab_mr_ids(text):
        identities.append(f"gitlab-mr:{_identity_project_scope(entry)}:{mr_id}")
    return list(dict.fromkeys(identities))


def _redmine_issue_ids(entry: dict) -> list[str]:
    return re.findall(r"(?:Redmine|issue|#)\s*([0-9]{4,})", _entry_identity_text(entry), flags=re.IGNORECASE)


def _entry_identity_text(entry: dict) -> str:
    text_parts = [
        entry.get("source_ref"),
        entry.get("title"),
        entry.get("name"),
        entry.get("next_action"),
        entry.get("summary"),
    ]
    return " ".join(str(part) for part in text_parts if part)


def _openspec_change_ids(text: str) -> list[str]:
    patterns = [
        r"openspec/changes/([A-Za-z0-9][A-Za-z0-9_.-]*)",
        r"OpenSpec(?:\s+change)?[:\s]+([A-Za-z0-9][A-Za-z0-9_.-]*)",
    ]
    changes: list[str] = []
    for pattern in patterns:
        changes.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    return list(dict.fromkeys(changes))


def _gitlab_mr_ids(text: str) -> list[str]:
    ids = re.findall(r"(?:\bMR\s*!|/merge_requests/)([0-9]+)", text, flags=re.IGNORECASE)
    ids.extend(re.findall(r"(?<!\w)!([0-9]+)", text))
    return list(dict.fromkeys(ids))


def _identity_project_scope(entry: dict) -> str:
    return str(entry.get("cwd") or entry.get("project_path") or "unknown").strip() or "unknown"


def _codex_title(entry: dict, source_ref: str, target_status: str) -> str:
    fallback = "Codex 已完成工作项" if target_status == WorkItemStatus.DONE.value else "Codex 工作项"
    return str(entry.get("title") or entry.get("name") or source_ref or fallback)


def _codex_snapshot_summary(entry: dict, report, target_status: str) -> str:
    if target_status == WorkItemStatus.DONE.value:
        return "; ".join(_codex_completion_signals(entry, report))
    return str(entry.get("next_action") or entry.get("status") or getattr(report, "summary", "") or "")


def _codex_completion_signals(entry: dict, report) -> list[str]:
    signals: list[str] = []
    raw_signals = entry.get("completion_signals")
    if isinstance(raw_signals, list):
        signals.extend(str(signal).strip() for signal in raw_signals if str(signal).strip())
    raw_evidence = entry.get("evidence")
    if isinstance(raw_evidence, list):
        signals.extend(str(signal).strip() for signal in raw_evidence if str(signal).strip())
    elif isinstance(raw_evidence, str) and raw_evidence.strip():
        signals.append(raw_evidence.strip())
    if not signals:
        fallback = str(entry.get("status") or entry.get("summary") or getattr(report, "summary", "") or "completed")
        signals.append(fallback.strip() or "completed")
    return list(dict.fromkeys(signals))


def _codex_evidence_context(entry: dict, report) -> str:
    context = {
        "generated_at": getattr(report, "generated_at", ""),
        "report_path": getattr(report, "path", ""),
        "source_ref": _codex_source_ref(entry),
        "title": entry.get("title") or entry.get("name") or "",
    }
    return json.dumps(context, ensure_ascii=False, sort_keys=True)


def _normalize_evidence_summary(summary: str) -> str:
    return " ".join(str(summary).split())


def _next_codex_status(previous_status: str | None, target_status: str) -> str:
    if previous_status == WorkItemStatus.DONE.value and target_status != WorkItemStatus.DONE.value:
        return WorkItemStatus.DONE.value
    return target_status


def _count_codex_outcome(result: CodexImportResult, previous_status: str | None, new_status: str) -> None:
    if previous_status == new_status:
        result.unchanged += 1
    elif new_status == WorkItemStatus.DONE.value:
        result.completed += 1
    elif new_status == WorkItemStatus.BLOCKED.value:
        result.blocked += 1
    elif previous_status == WorkItemStatus.BLOCKED.value and new_status == WorkItemStatus.ACTIVE.value:
        result.reactivated += 1
    elif previous_status is not None:
        result.unchanged += 1


def _is_stale(last_synced_at: str | None, stale_after_hours: int) -> bool:
    if not last_synced_at:
        return False
    try:
        parsed = datetime.strptime(last_synced_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return parsed < datetime.now() - timedelta(hours=stale_after_hours)


def _facts_excerpt(snapshot: SourceSnapshot) -> str:
    if snapshot.error:
        return snapshot.error[:1000]
    if not snapshot.facts:
        return ""
    try:
        return json.dumps(snapshot.facts, ensure_ascii=False, sort_keys=True)[:1000]
    except (TypeError, ValueError):
        return str(snapshot.facts)[:1000]
