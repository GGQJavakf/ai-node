"""Deterministic, SQLite-only task briefing."""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Callable

from agent_retro.application.ports import RetroRepository
from agent_retro.application.purge import require_no_active_purge
from agent_retro.domain.models import (
    BriefHealthCounts,
    Knowledge,
    KnowledgeType,
    ProjectionStatus,
)


DEFAULT_RELEVANCE_WEIGHTS = MappingProxyType(
    {"keyword": 0.70, "recency": 0.20, "evidence": 0.10}
)


class BriefError(RuntimeError):
    """Base class for stable briefing failures."""


class BriefBudgetError(BriefError):
    def __init__(self, required_tokens: int, max_tokens: int) -> None:
        self.required_tokens = required_tokens
        self.max_tokens = max_tokens
        self.reason = "mandatory_rules_over_budget"
        super().__init__("规则所需预算超过上限；请提高 max_tokens 或整理规则。")


class BriefTimeoutError(BriefError):
    def __init__(self) -> None:
        self.reason = "brief_deadline_exceeded"
        super().__init__("本地 briefing 超过配置时限；未返回部分结果。")


@dataclass(frozen=True)
class BriefRequest:
    task: str
    project_id: str
    max_tokens: int | None = None


@dataclass(frozen=True)
class BriefItem:
    id: str
    category: str
    knowledge_type: str
    scope: str
    text: str
    status: str
    evidence_refs: tuple[str, ...]
    relevance_score: float
    estimated_tokens: int


@dataclass(frozen=True)
class BriefOmission:
    id: str
    reason: str


@dataclass(frozen=True)
class BriefResult:
    task: str
    project_id: str
    generated_at: datetime
    max_tokens: int
    estimated_tokens: int
    items: tuple[BriefItem, ...]
    omitted: tuple[BriefOmission, ...]
    stale_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    health: BriefHealthCounts | None = None
    review_inbox_command: str = ""
    recent_capture_command: str = ""

    @property
    def omitted_count(self) -> int:
        return len(self.omitted)


@dataclass(frozen=True)
class _BriefContext:
    task: str
    project_id: str
    generated_at: datetime
    max_tokens: int
    stale_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    warnings: tuple[str, ...]


def tokenize(value: str) -> frozenset[str]:
    """Normalize Latin words and individual CJK characters deterministically."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    latin = re.findall(r"[a-z0-9]+", normalized)
    cjk = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", normalized)
    return frozenset([*latin, *cjk])


def estimate_tokens(value: str) -> int:
    """Apply the documented conservative UTF-8 byte estimate."""

    return math.ceil(len(value.encode("utf-8")) / 3)


def brief_json_data(result: BriefResult) -> dict[str, object]:
    """Return the canonical stable JSON view used for output and budgeting."""

    data: dict[str, object] = {
        "conflict_ids": list(result.conflict_ids),
        "estimated_tokens": result.estimated_tokens,
        "generated_at": result.generated_at.isoformat(),
        "items": [_brief_item_data(item) for item in result.items],
        "max_tokens": result.max_tokens,
        "omitted": [{"id": item.id, "reason": item.reason} for item in result.omitted],
        "omitted_count": result.omitted_count,
        "project_id": result.project_id,
        "stale_ids": list(result.stale_ids),
        "task": result.task,
        "warnings": list(result.warnings),
    }
    if result.health is not None:
        data.update(
            {
                "eligible_knowledge_count": result.health.eligible_knowledge_count,
                "expired_task_state_count": result.health.expired_task_state_count,
                "pending_review_count": result.health.pending_review_count,
                "captured_session_count": result.health.captured_session_count,
                "review_inbox_command": result.review_inbox_command,
                "recent_capture_command": result.recent_capture_command,
            }
        )
    return data


def render_brief_markdown(result: BriefResult) -> str:
    lines = [
        f"# AgentRetro Brief: {result.project_id}",
        "",
        f"Task: {result.task}",
        f"Budget: {result.estimated_tokens}/{result.max_tokens}",
        "",
    ]
    for item in result.items:
        lines.extend(
            [
                f"## {item.category}: {item.id}",
                "",
                item.text,
                "",
                "Evidence: " + (", ".join(item.evidence_refs) or "none"),
                "",
            ]
        )
    _append_brief_health(lines, result)
    return "\n".join(lines).rstrip() + "\n"


def render_brief_terminal(result: BriefResult) -> str:
    lines = [
        f"AgentRetro Brief [{result.project_id}]",
        f"Task: {result.task}",
        f"Budget: {result.estimated_tokens}/{result.max_tokens}",
    ]
    for item in result.items:
        evidence = ", ".join(item.evidence_refs) or "none"
        lines.append(f"[{item.category}] {item.id}: {item.text} (evidence: {evidence})")
    if result.omitted:
        lines.append(
            "Omitted: "
            + ", ".join(f"{item.id}={item.reason}" for item in result.omitted)
        )
    if result.warnings:
        lines.append("Warnings: " + ", ".join(result.warnings))
    if result.health is not None:
        lines.extend(
            [
                "Health: "
                f"eligible={result.health.eligible_knowledge_count}, "
                f"expired_task_state={result.health.expired_task_state_count}, "
                f"pending_review={result.health.pending_review_count}, "
                f"captured_session={result.health.captured_session_count}",
                f"Review: {result.review_inbox_command}",
                f"Capture: {result.recent_capture_command}",
            ]
        )
    return "\n".join(lines) + "\n"


def render_brief_json(result: BriefResult) -> str:
    return (
        json.dumps(brief_json_data(result), ensure_ascii=False, sort_keys=True) + "\n"
    )


def renderer_token_cost(result: BriefResult) -> int:
    """Conservatively budget the largest complete visible renderer."""

    return max(
        estimate_tokens(render_brief_terminal(result)),
        estimate_tokens(render_brief_markdown(result)),
        estimate_tokens(render_brief_json(result)),
    )


def _brief_item_data(item: BriefItem) -> dict[str, object]:
    return {
        "category": item.category,
        "estimated_tokens": item.estimated_tokens,
        "evidence_refs": list(item.evidence_refs),
        "id": item.id,
        "knowledge_type": item.knowledge_type,
        "relevance_score": item.relevance_score,
        "scope": item.scope,
        "status": item.status,
        "text": item.text,
    }


def _append_brief_health(lines: list[str], result: BriefResult) -> None:
    if result.health is not None:
        lines.extend(
            [
                "## Health",
                "",
                f"- Eligible knowledge: {result.health.eligible_knowledge_count}",
                f"- Expired task state: {result.health.expired_task_state_count}",
                f"- Pending review: {result.health.pending_review_count}",
                f"- Captured sessions: {result.health.captured_session_count}",
                f"- Review: `{result.review_inbox_command}`",
                f"- Capture: `{result.recent_capture_command}`",
                "",
            ]
        )
    if result.omitted:
        lines.extend(
            [
                "## Omitted",
                "",
                *[f"- {item.id}: {item.reason}" for item in result.omitted],
                "",
            ]
        )
    if result.warnings:
        lines.extend(
            [
                "## Warnings",
                "",
                *[f"- {warning}" for warning in result.warnings],
                "",
            ]
        )


def _with_item_cost(item: BriefItem) -> BriefItem:
    current = item
    for _ in range(8):
        terminal = (
            f"[{current.category}] {current.id}: {current.text} "
            f"(evidence: {', '.join(current.evidence_refs) or 'none'})\n"
        )
        markdown = (
            f"## {current.category}: {current.id}\n\n{current.text}\n\n"
            f"Evidence: {', '.join(current.evidence_refs) or 'none'}\n"
        )
        json_text = json.dumps(
            _brief_item_data(current), ensure_ascii=False, sort_keys=True
        )
        cost = max(
            estimate_tokens(terminal),
            estimate_tokens(markdown),
            estimate_tokens(json_text),
        )
        if cost == current.estimated_tokens:
            return current
        current = replace(current, estimated_tokens=cost)
    return current


def _with_result_cost(result: BriefResult) -> BriefResult:
    current = result
    for _ in range(8):
        cost = renderer_token_cost(current)
        if cost == current.estimated_tokens:
            return current
        current = replace(current, estimated_tokens=cost)
    return current


def relevance_score(task: str, item: Knowledge, at: datetime) -> float:
    task_tokens = tokenize(task)
    item_tokens = tokenize(item.text)
    overlap = len(task_tokens & item_tokens) / max(1, len(task_tokens | item_tokens))
    age_days = max(0.0, (at - item.updated_at).total_seconds() / 86400)
    recency = 1.0 / (1.0 + age_days / 30.0)
    evidence = min(1.0, len(item.evidence_ids) / 3.0)
    return (
        DEFAULT_RELEVANCE_WEIGHTS["keyword"] * overlap
        + DEFAULT_RELEVANCE_WEIGHTS["recency"] * recency
        + DEFAULT_RELEVANCE_WEIGHTS["evidence"] * evidence
    )


class BriefService:
    """Build a bounded brief from accepted SQLite knowledge only."""

    def __init__(
        self,
        repository: RetroRepository,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        timeout_seconds: float = 5.0,
        default_max_tokens: int = 6000,
        recent_capture_max: int = 20,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if default_max_tokens <= 0:
            raise ValueError("default_max_tokens must be greater than zero")
        if recent_capture_max <= 0:
            raise ValueError("recent_capture_max must be greater than zero")
        self.repository = repository
        self.now = now
        self.monotonic = monotonic
        self.timeout_seconds = timeout_seconds
        self.default_max_tokens = default_max_tokens
        self.recent_capture_max = recent_capture_max

    def build(self, request: BriefRequest) -> BriefResult:
        task, project_id, max_tokens = self._validate_request(request)
        require_no_active_purge(self.repository, project_id=project_id)

        deadline = self.monotonic() + self.timeout_seconds
        at = self.now()
        categories, omitted, stale_ids = self._collect_knowledge(
            task, project_id, at, deadline
        )
        conflicts = self.repository.list_open_conflicts(project_id)
        conflict_ids = tuple(sorted(item.id for item in conflicts))
        omitted.extend(BriefOmission(item_id, "conflict") for item_id in conflict_ids)
        context = _BriefContext(
            task=task,
            project_id=project_id,
            generated_at=at,
            max_tokens=max_tokens,
            stale_ids=tuple(sorted(stale_ids)),
            conflict_ids=conflict_ids,
            warnings=self._warnings(project_id),
        )
        by_category = self._build_items(categories, deadline)
        result = self._select_items(by_category, omitted, context, deadline)
        if not result.items:
            result = self._add_empty_health(result, context)
        self._check_deadline(deadline)
        return result

    def _validate_request(self, request: BriefRequest) -> tuple[str, str, int]:
        task = request.task.strip()
        project_id = request.project_id.strip()
        max_tokens = (
            self.default_max_tokens
            if request.max_tokens is None
            else request.max_tokens
        )
        if not task:
            raise ValueError("task must not be empty")
        if not project_id:
            raise ValueError("project_id must not be empty")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero")
        return task, project_id, max_tokens

    def _collect_knowledge(
        self, task: str, project_id: str, at: datetime, deadline: float
    ) -> tuple[dict[str, list[tuple[Knowledge, float]]], list[BriefOmission], set[str]]:
        knowledge = self.repository.list_brief_knowledge(project_id, at)
        self._check_deadline(deadline)
        categories: dict[str, list[tuple[Knowledge, float]]] = {
            "project_rule": [],
            "global_rule": [],
            "task_state": [],
            "lesson": [],
        }
        omitted: list[BriefOmission] = []
        stale_ids: set[str] = set()
        for item in knowledge:
            self._check_deadline(deadline)
            invalid_reason = self._invalid_reason(item, project_id, at)
            if invalid_reason is not None:
                if invalid_reason in {"expired", "stale"}:
                    stale_ids.add(item.id)
                if invalid_reason != "other_project":
                    omitted.append(BriefOmission(item.id, invalid_reason))
                continue
            category = self._category(item, project_id)
            if category is None:
                continue
            categories[category].append((item, relevance_score(task, item, at)))
        for values in categories.values():
            values.sort(key=lambda value: (-value[1], value[0].id))
        return categories, omitted, stale_ids

    def _build_items(
        self,
        categories: dict[str, list[tuple[Knowledge, float]]],
        deadline: float,
    ) -> dict[str, list[BriefItem]]:
        by_category: dict[str, list[BriefItem]] = {
            "project_rule": [],
            "global_rule": [],
            "task_state": [],
            "lesson": [],
        }
        for category, values in categories.items():
            for item, score in values:
                self._check_deadline(deadline)
                by_category[category].append(
                    _with_item_cost(
                        BriefItem(
                            id=item.id,
                            category=category,
                            knowledge_type=item.knowledge_type.value,
                            scope=item.scope,
                            text=item.text,
                            status=item.status,
                            evidence_refs=tuple(sorted(item.evidence_ids)),
                            relevance_score=score,
                            estimated_tokens=0,
                        )
                    )
                )
        return by_category

    def _select_items(
        self,
        by_category: dict[str, list[BriefItem]],
        omitted: list[BriefOmission],
        context: _BriefContext,
        deadline: float,
    ) -> BriefResult:
        mandatory = [
            *by_category["project_rule"],
            *by_category["global_rule"],
        ]
        optional = [*by_category["task_state"], *by_category["lesson"]]
        base_omitted = [
            *omitted,
            *[BriefOmission(item.id, "budget") for item in optional],
        ]
        selected = list(mandatory)
        current_omitted = list(base_omitted)
        required = self._result_for(context, selected, current_omitted)
        self._check_deadline(deadline)
        if required.estimated_tokens > context.max_tokens:
            raise BriefBudgetError(required.estimated_tokens, context.max_tokens)

        for brief_item in optional:
            self._check_deadline(deadline)
            trial_omitted = [
                omission
                for omission in current_omitted
                if not (omission.id == brief_item.id and omission.reason == "budget")
            ]
            trial = self._result_for(context, [*selected, brief_item], trial_omitted)
            self._check_deadline(deadline)
            if trial.estimated_tokens <= context.max_tokens:
                selected.append(brief_item)
                current_omitted = trial_omitted
        return self._result_for(context, selected, current_omitted)

    @staticmethod
    def _result_for(
        context: _BriefContext,
        items: list[BriefItem],
        omissions: list[BriefOmission],
    ) -> BriefResult:
        return _with_result_cost(
            BriefResult(
                task=context.task,
                project_id=context.project_id,
                generated_at=context.generated_at,
                max_tokens=context.max_tokens,
                estimated_tokens=0,
                items=tuple(items),
                omitted=tuple(
                    sorted(omissions, key=lambda value: (value.id, value.reason))
                ),
                stale_ids=context.stale_ids,
                conflict_ids=context.conflict_ids,
                warnings=context.warnings,
            )
        )

    def _add_empty_health(
        self, result: BriefResult, context: _BriefContext
    ) -> BriefResult:
        result = _with_result_cost(
            replace(
                result,
                health=self.repository.brief_health_counts(
                    context.project_id, context.generated_at
                ),
                review_inbox_command=(
                    f"retro review inbox --project {context.project_id}"
                ),
                recent_capture_command=(
                    "retro capture --recent "
                    f"{min(5, self.recent_capture_max)} --dry-run"
                ),
            )
        )
        if result.estimated_tokens > context.max_tokens:
            raise BriefBudgetError(result.estimated_tokens, context.max_tokens)
        return result

    def _warnings(self, project_id: str) -> tuple[str, ...]:
        warnings = [
            f"sync_pending:{event.id}"
            for event in sorted(
                self.repository.list_projection_events(project_id),
                key=lambda value: value.id,
            )
            if event.status is ProjectionStatus.SYNC_PENDING
        ]
        if self.repository.has_rollback_required_sync():
            warnings.append("rollback_required")
        if self.repository.has_purge_incomplete():
            warnings.append("purge_incomplete")
        return tuple(warnings)

    @staticmethod
    def _invalid_reason(item: Knowledge, project_id: str, at: datetime) -> str | None:
        if item.scope != "global" and item.project_id != project_id:
            return "other_project"
        if item.status != "active":
            return item.status
        if item.valid_until is not None and item.valid_until <= at:
            return "expired"
        return None

    @staticmethod
    def _category(item: Knowledge, project_id: str) -> str | None:
        if item.knowledge_type is KnowledgeType.RULE:
            return "global_rule" if item.scope == "global" else "project_rule"
        if item.scope != "global" and item.project_id != project_id:
            return None
        if item.knowledge_type is KnowledgeType.TASK_STATE:
            return "task_state"
        if item.knowledge_type is KnowledgeType.LESSON:
            return "lesson"
        return None

    def _check_deadline(self, deadline: float) -> None:
        if self.monotonic() >= deadline:
            raise BriefTimeoutError()
