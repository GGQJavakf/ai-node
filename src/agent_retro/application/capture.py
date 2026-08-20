"""Explicit, redacted, transactional AgentRetro capture use case."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import (
    Evidence,
    NormalizedEvent,
    NormalizedSession,
)
from agent_retro.infrastructure.codex_sessions import CodexSessionSource
from agent_retro.infrastructure.project_mapping import (
    GitProjectError,
    ProjectResolution,
    ProjectResolver,
    resolve_git_identity,
)
from agent_retro.infrastructure.redaction import Redactor


class SourceIntegrityError(RuntimeError):
    """A known source identity was observed with changed bytes."""


class RecentCaptureBoundsError(ValueError):
    def __init__(self, count: int, maximum: int) -> None:
        super().__init__("recent_capture_count_out_of_bounds")
        self.count = count
        self.maximum = maximum
        self.reason = "recent_capture_count_out_of_bounds"


class CapturePlanChangedError(ValueError):
    def __init__(self, count: int) -> None:
        super().__init__("capture_plan_changed")
        self.count = count
        self.reason = "capture_plan_changed"
        self.recovery_command = f"retro capture --recent {count} --dry-run"


@dataclass(frozen=True)
class CaptureResult:
    session_id: str
    captured: bool
    reused: bool
    warnings: tuple[str, ...]
    project_status: str


@dataclass(frozen=True)
class RecentCapturePlanItem:
    session_id: str
    source_hash: str
    resolution_status: str
    canonical_project_id: str
    mapping_id: str
    reuse_status: str


@dataclass(frozen=True)
class RecentCapturePlan:
    plan_id: str
    schema_version: int
    requested_count: int
    recent_capture_max: int
    items: tuple[RecentCapturePlanItem, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchCaptureItem:
    session_id: str
    reason: str = ""


@dataclass(frozen=True)
class RecentCaptureResult:
    plan_id: str
    requested_count: int
    captured: tuple[BatchCaptureItem, ...]
    reused: tuple[BatchCaptureItem, ...]
    failed: tuple[BatchCaptureItem, ...]
    skipped: tuple[BatchCaptureItem, ...]
    recovery_command: str


def _recent_capture_plan_id(
    schema_version: int,
    requested_count: int,
    recent_capture_max: int,
    items: Sequence[RecentCapturePlanItem],
) -> str:
    payload = {
        "schema_version": schema_version,
        "requested_count": requested_count,
        "recent_capture_max": recent_capture_max,
        "items": [
            {
                "session_id": item.session_id,
                "source_hash": item.source_hash,
                "resolution_status": item.resolution_status,
                "canonical_project_id": item.canonical_project_id,
                "mapping_id": item.mapping_id,
                "reuse_status": item.reuse_status,
            }
            for item in items
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


class CaptureService:
    """Capture one explicitly selected completed session."""

    def __init__(
        self,
        source: CodexSessionSource,
        repository: RetroRepository,
        redactor: Redactor,
        project_resolver: ProjectResolver,
        *,
        evidence_excerpt_chars: int = 512,
    ) -> None:
        if evidence_excerpt_chars <= 0:
            raise ValueError("evidence_excerpt_chars must be positive")
        self.source = source
        self.repository = repository
        self.redactor = redactor
        self.project_resolver = project_resolver
        self.evidence_excerpt_chars = evidence_excerpt_chars

    def capture_last(self) -> CaptureResult:
        return self._capture(self.source.latest_completed())

    def capture_session(self, session_id: str) -> CaptureResult:
        return self._capture(self.source.load(session_id))

    def preview_recent(self, count: int, maximum: int) -> RecentCapturePlan:
        plan, _, _ = self._recent_plan(count, maximum)
        return plan

    def apply_recent(
        self, count: int, maximum: int, expected_plan_id: str
    ) -> RecentCaptureResult:
        plan, sessions, resolutions = self._recent_plan(count, maximum)
        if plan.plan_id != expected_plan_id:
            raise CapturePlanChangedError(count)

        captured: list[BatchCaptureItem] = []
        reused: list[BatchCaptureItem] = []
        failed: list[BatchCaptureItem] = []
        skipped: list[BatchCaptureItem] = []
        stopped = False
        for item, session, resolution in zip(plan.items, sessions, resolutions):
            if stopped:
                skipped.append(BatchCaptureItem(item.session_id, "batch_stopped"))
                continue
            if item.resolution_status != "resolved":
                skipped.append(
                    BatchCaptureItem(item.session_id, item.resolution_status)
                )
                continue
            try:
                result = self._capture(session, resolution=resolution)
            except Exception:
                failed.append(BatchCaptureItem(item.session_id, "capture_failed"))
                stopped = True
                continue
            target = reused if result.reused else captured
            target.append(BatchCaptureItem(item.session_id))

        return RecentCaptureResult(
            plan_id=plan.plan_id,
            requested_count=count,
            captured=tuple(captured),
            reused=tuple(reused),
            failed=tuple(failed),
            skipped=tuple(skipped),
            recovery_command=f"retro capture --recent {count} --dry-run",
        )

    def _recent_plan(
        self, count: int, maximum: int
    ) -> tuple[
        RecentCapturePlan,
        tuple[NormalizedSession, ...],
        tuple[ProjectResolution, ...],
    ]:
        if count < 1 or maximum < 1 or count > maximum:
            raise RecentCaptureBoundsError(count, maximum)
        sessions = self.source.recent_completed(count)
        items: list[RecentCapturePlanItem] = []
        resolutions: list[ProjectResolution] = []
        for session in sessions:
            resolution = self._resolve_project(session.project_id)
            resolutions.append(resolution)
            existing = self.repository.find_session(
                session.source_session_id, session.source_hash
            )
            conflicting = self.repository.find_session_by_source_id(
                session.source_session_id
            )
            reuse_status = (
                "reused"
                if existing is not None
                else "source_conflict"
                if conflicting is not None
                else "new"
            )
            items.append(
                RecentCapturePlanItem(
                    session_id=session.source_session_id,
                    source_hash=session.source_hash,
                    resolution_status=resolution.status,
                    canonical_project_id=resolution.project_id,
                    mapping_id=resolution.mapping_id,
                    reuse_status=reuse_status,
                )
            )
        item_tuple = tuple(items)
        schema_version = 1
        plan_id = _recent_capture_plan_id(schema_version, count, maximum, item_tuple)
        return (
            RecentCapturePlan(
                plan_id=plan_id,
                schema_version=schema_version,
                requested_count=count,
                recent_capture_max=maximum,
                items=item_tuple,
                warnings=self.source.last_discovery.warnings,
            ),
            sessions,
            tuple(resolutions),
        )

    def _capture(
        self,
        source_session: NormalizedSession,
        *,
        resolution: ProjectResolution | None = None,
    ) -> CaptureResult:
        existing = self.repository.find_session(
            source_session.source_session_id, source_session.source_hash
        )
        if existing is not None:
            return CaptureResult(
                session_id=existing.source_session_id,
                captured=False,
                reused=True,
                warnings=self.source.last_discovery.warnings,
                project_status=_persisted_project_status(existing.project_id),
            )
        conflicting = self.repository.find_session_by_source_id(
            source_session.source_session_id
        )
        if conflicting is not None:
            raise SourceIntegrityError(
                f"Codex 会话源哈希发生冲突: {source_session.source_session_id}"
            )

        resolution = resolution or self._resolve_project(source_session.project_id)
        # Pass 1: values are redacted before any future model consumer can see
        # the normalized capture payload.
        model_safe_session = self._redacted_session(source_session)
        evidence = self._minimal_evidence(model_safe_session)
        # Pass 2: run the identical boundary immediately before serialization.
        persistent_session = self._persistent_session(
            model_safe_session, resolution, evidence
        )
        persistent_evidence = tuple(
            replace(item, excerpt=self.redactor.redact(item.excerpt))
            for item in evidence
        )
        # SQLiteRetroRepository.save_capture persists session, events, evidence,
        # and its audit record in one transaction.
        self.repository.save_capture(persistent_session, persistent_evidence)
        warnings = list(self.source.last_discovery.warnings)
        if resolution.diagnostic:
            warnings.append(resolution.diagnostic)
        return CaptureResult(
            session_id=source_session.source_session_id,
            captured=True,
            reused=False,
            warnings=tuple(warnings),
            project_status=resolution.status,
        )

    def _resolve_project(self, cwd: str) -> ProjectResolution:
        path = Path(cwd)
        try:
            root, remote = resolve_git_identity(path)
        except GitProjectError:
            root, remote = path, ""
        return self.project_resolver.resolve(root, remote, source_path=path)

    def _redacted_session(self, session: NormalizedSession) -> NormalizedSession:
        events: list[NormalizedEvent] = []
        for event in session.events:
            content = self.redactor.redact(event.content)
            locator = replace(
                event.locator,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
            events.append(replace(event, content=content, locator=locator))
        return replace(
            session,
            events=tuple(events),
        )

    def _minimal_evidence(self, session: NormalizedSession) -> tuple[Evidence, ...]:
        items: dict[tuple[str, str], Evidence] = {}
        for event in session.events:
            key = (event.kind, event.locator.content_hash)
            existing = items.get(key)
            if existing is not None:
                if event.locator not in existing.all_locators:
                    items[key] = replace(
                        existing,
                        locators=existing.all_locators + (event.locator,),
                    )
                continue
            excerpt = _excerpt(event.content, self.evidence_excerpt_chars)
            evidence_id = (
                "evidence-"
                + hashlib.sha256(
                    (
                        f"{session.source_session_id}:{event.kind}:"
                        f"{event.locator.content_hash}"
                    ).encode("utf-8")
                ).hexdigest()[:24]
            )
            items[key] = Evidence(
                id=evidence_id,
                session_id=session.id,
                kind=event.kind,
                locator=event.locator,
                excerpt=excerpt,
                locators=(event.locator,),
            )
        return tuple(items.values())

    def _persistent_session(
        self,
        session: NormalizedSession,
        resolution: ProjectResolution,
        evidence: Sequence[Evidence],
    ) -> NormalizedSession:
        excerpts = {
            locator.event_id: item.excerpt
            for item in evidence
            for locator in item.all_locators
        }
        project_id = (
            resolution.project_id
            if resolution.status == "resolved"
            else f"awaiting:{resolution.status}"
        )
        events: list[NormalizedEvent] = []
        for event in session.events:
            value = excerpts[event.locator.event_id]
            events.append(replace(event, content=self.redactor.redact(value)))
        return replace(session, project_id=project_id, events=tuple(events))


def _excerpt(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _persisted_project_status(project_id: str) -> str:
    if project_id.startswith("awaiting:"):
        return project_id.split(":", 1)[1]
    return "resolved"
