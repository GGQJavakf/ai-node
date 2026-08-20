"""Content-free, read-only review work summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import BriefHealthCounts, PendingCandidateSummary


class InboxLimitError(ValueError):
    def __init__(self, limit: int) -> None:
        super().__init__("review_inbox_limit_out_of_bounds")
        self.limit = limit
        self.reason = "review_inbox_limit_out_of_bounds"


@dataclass(frozen=True)
class ProjectInboxSummary:
    project_id: str
    pending_count: int
    retryable_count: int
    oldest_pending_age_seconds: int | None
    eligible_knowledge_count: int
    expired_task_state_count: int
    active_task_state_count: int


@dataclass(frozen=True)
class CrossProjectInbox:
    projects: tuple[ProjectInboxSummary, ...]
    awaiting_unknown_count: int
    awaiting_ambiguous_count: int


@dataclass(frozen=True)
class ProjectInboxItem:
    candidate_id: str
    age_seconds: int
    retryable: bool
    show_command: str
    accept_command: str
    edit_command: str
    reject_command: str
    retry_command: str | None


@dataclass(frozen=True)
class ProjectInbox:
    project_id: str
    total_count: int
    returned_count: int
    truncated: bool
    retryable_count: int
    items: tuple[ProjectInboxItem, ...]
    health: BriefHealthCounts
    inbox_command: str


@dataclass(frozen=True)
class AwaitingInboxItem:
    session_id: str
    routing_status: str
    age_seconds: int
    reclassify_command: str


@dataclass(frozen=True)
class AwaitingInbox:
    total_count: int
    returned_count: int
    truncated: bool
    items: tuple[AwaitingInboxItem, ...]
    project_list_command: str


class ReviewInboxService:
    """Build bounded inbox projections without reading content-bearing rows."""

    def __init__(
        self,
        repository: RetroRepository,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository
        self.now = now

    def cross_project(self) -> CrossProjectInbox:
        at = self.now()
        pending = self.repository.list_pending_candidate_summaries()
        project_ids = {
            mapping.obsidian_project
            for mapping in self.repository.list_project_mappings()
        }
        project_ids.update(item.project_id for item in pending)
        rows = tuple(
            self._project_summary(
                project_id,
                [item for item in pending if item.project_id == project_id],
                at,
            )
            for project_id in sorted(project_ids)
        )
        awaiting = self.repository.list_awaiting_session_summaries()
        return CrossProjectInbox(
            projects=rows,
            awaiting_unknown_count=sum(
                item.routing_status == "unknown" for item in awaiting
            ),
            awaiting_ambiguous_count=sum(
                item.routing_status == "ambiguous" for item in awaiting
            ),
        )

    def project(self, project_id: str, limit: int = 20) -> ProjectInbox:
        self._validate_limit(limit)
        at = self.now()
        pending = self.repository.list_pending_candidate_summaries(project_id)
        returned = pending[:limit]
        items = tuple(self._project_item(item, at) for item in returned)
        return ProjectInbox(
            project_id=project_id,
            total_count=len(pending),
            returned_count=len(items),
            truncated=len(pending) > len(items),
            retryable_count=sum(item.retryable for item in pending),
            items=items,
            health=self.repository.brief_health_counts(project_id, at),
            inbox_command=f"retro review inbox --project {project_id}",
        )

    def awaiting(self, limit: int = 20) -> AwaitingInbox:
        self._validate_limit(limit)
        at = self.now()
        awaiting = self.repository.list_awaiting_session_summaries()
        returned = awaiting[:limit]
        items = tuple(
            AwaitingInboxItem(
                session_id=item.source_session_id,
                routing_status=item.routing_status,
                age_seconds=_age_seconds(at, item.captured_at),
                reclassify_command=(
                    "retro project reclassify --session "
                    f"{item.source_session_id} --mapping <mapping-id>"
                ),
            )
            for item in returned
        )
        return AwaitingInbox(
            total_count=len(awaiting),
            returned_count=len(items),
            truncated=len(awaiting) > len(items),
            items=items,
            project_list_command="retro project list",
        )

    def _project_summary(
        self,
        project_id: str,
        pending: list[PendingCandidateSummary],
        at: datetime,
    ) -> ProjectInboxSummary:
        health = self.repository.brief_health_counts(project_id, at)
        return ProjectInboxSummary(
            project_id=project_id,
            pending_count=len(pending),
            retryable_count=sum(item.retryable for item in pending),
            oldest_pending_age_seconds=(
                None if not pending else _age_seconds(at, pending[0].created_at)
            ),
            eligible_knowledge_count=health.eligible_knowledge_count,
            expired_task_state_count=health.expired_task_state_count,
            active_task_state_count=health.active_task_state_count,
        )

    @staticmethod
    def _project_item(
        item: PendingCandidateSummary, at: datetime
    ) -> ProjectInboxItem:
        candidate_id = item.id
        return ProjectInboxItem(
            candidate_id=candidate_id,
            age_seconds=_age_seconds(at, item.created_at),
            retryable=item.retryable,
            show_command=f"retro review show {candidate_id}",
            accept_command=f"retro review accept {candidate_id}",
            edit_command=f"retro review edit {candidate_id} --text <text>",
            reject_command=f"retro review reject {candidate_id}",
            retry_command=(
                f"retro review retry --candidate {candidate_id}"
                if item.retryable
                else None
            ),
        )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not 1 <= limit <= 50:
            raise InboxLimitError(limit)


def _age_seconds(at: datetime, created_at: datetime) -> int:
    return max(0, int((_as_utc(at) - _as_utc(created_at)).total_seconds()))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
