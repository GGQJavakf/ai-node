"""Deterministic, SQLite-only task briefing."""

from __future__ import annotations

import math
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Callable

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import Knowledge, KnowledgeType, ProjectionStatus


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

    @property
    def omitted_count(self) -> int:
        return len(self.omitted)


def tokenize(value: str) -> frozenset[str]:
    """Normalize Latin words and individual CJK characters deterministically."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    latin = re.findall(r"[a-z0-9]+", normalized)
    cjk = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", normalized)
    return frozenset([*latin, *cjk])


def estimate_tokens(value: str) -> int:
    """Apply the documented conservative UTF-8 byte estimate."""

    return math.ceil(len(value.encode("utf-8")) / 3)


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
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if default_max_tokens <= 0:
            raise ValueError("default_max_tokens must be greater than zero")
        self.repository = repository
        self.now = now
        self.monotonic = monotonic
        self.timeout_seconds = timeout_seconds
        self.default_max_tokens = default_max_tokens

    def build(self, request: BriefRequest) -> BriefResult:
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

        deadline = self.monotonic() + self.timeout_seconds
        at = self.now()
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

        mandatory = [
            *categories["project_rule"],
            *categories["global_rule"],
        ]
        required_tokens = sum(estimate_tokens(item.text) for item, _ in mandatory)
        if required_tokens > max_tokens:
            raise BriefBudgetError(required_tokens, max_tokens)

        selected: list[BriefItem] = []
        consumed = 0
        for category in (
            "project_rule",
            "global_rule",
            "task_state",
            "lesson",
        ):
            for item, score in categories[category]:
                self._check_deadline(deadline)
                cost = estimate_tokens(item.text)
                if category not in {"project_rule", "global_rule"} and (
                    consumed + cost > max_tokens
                ):
                    omitted.append(BriefOmission(item.id, "budget"))
                    continue
                selected.append(
                    BriefItem(
                        id=item.id,
                        category=category,
                        knowledge_type=item.knowledge_type.value,
                        scope=item.scope,
                        text=item.text,
                        status=item.status,
                        evidence_refs=tuple(sorted(item.evidence_ids)),
                        relevance_score=score,
                        estimated_tokens=cost,
                    )
                )
                consumed += cost

        conflicts = self.repository.list_open_conflicts(project_id)
        conflict_ids = tuple(sorted(item.id for item in conflicts))
        omitted.extend(BriefOmission(item_id, "conflict") for item_id in conflict_ids)
        warnings = self._warnings(project_id)
        self._check_deadline(deadline)
        return BriefResult(
            task=task,
            project_id=project_id,
            generated_at=at,
            max_tokens=max_tokens,
            estimated_tokens=consumed,
            items=tuple(selected),
            omitted=tuple(sorted(omitted, key=lambda value: (value.id, value.reason))),
            stale_ids=tuple(sorted(stale_ids)),
            conflict_ids=conflict_ids,
            warnings=warnings,
        )

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
        if (
            item.scope == "global"
            and item.knowledge_type is not KnowledgeType.RULE
            and item.project_id != project_id
        ):
            return "other_project"
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
        if item.project_id != project_id:
            return None
        if item.knowledge_type is KnowledgeType.TASK_STATE:
            return "task_state"
        if item.knowledge_type is KnowledgeType.LESSON:
            return "lesson"
        return None

    def _check_deadline(self, deadline: float) -> None:
        if self.monotonic() >= deadline:
            raise BriefTimeoutError()
