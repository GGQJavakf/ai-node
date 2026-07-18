"""Explicit, redacted, transactional AgentRetro capture use case."""

from __future__ import annotations

import hashlib
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


@dataclass(frozen=True)
class CaptureResult:
    session_id: str
    captured: bool
    reused: bool
    warnings: tuple[str, ...]
    project_status: str


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

    def _capture(self, source_session: NormalizedSession) -> CaptureResult:
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
        find_by_identity = getattr(
            self.repository, "find_session_by_source_id", None
        )
        if callable(find_by_identity):
            conflicting = find_by_identity(source_session.source_session_id)
            if conflicting is not None:
                raise SourceIntegrityError(
                    "Codex 会话源哈希发生冲突: "
                    f"{source_session.source_session_id}"
                )

        resolution = self._resolve_project(source_session.project_id)
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
        return self.project_resolver.resolve(root, remote)

    def _redacted_session(
        self, session: NormalizedSession
    ) -> NormalizedSession:
        return replace(
            session,
            events=tuple(
                replace(event, content=self.redactor.redact(event.content))
                for event in session.events
            ),
        )

    def _minimal_evidence(
        self, session: NormalizedSession
    ) -> tuple[Evidence, ...]:
        items: list[Evidence] = []
        for event in session.events:
            excerpt = _excerpt(event.content, self.evidence_excerpt_chars)
            evidence_id = "evidence-" + hashlib.sha256(
                (
                    f"{session.source_session_id}:{event.id}:"
                    f"{event.locator.content_hash}"
                ).encode("utf-8")
            ).hexdigest()[:24]
            items.append(
                Evidence(
                    id=evidence_id,
                    session_id=session.id,
                    kind=event.kind,
                    locator=event.locator,
                    excerpt=excerpt,
                )
            )
        return tuple(items)

    def _persistent_session(
        self,
        session: NormalizedSession,
        resolution: ProjectResolution,
        evidence: Sequence[Evidence],
    ) -> NormalizedSession:
        excerpts = {item.locator.event_id: item.excerpt for item in evidence}
        project_id = (
            resolution.project_id
            if resolution.status == "resolved"
            else f"awaiting:{resolution.status}"
        )
        events: list[NormalizedEvent] = []
        for event in session.events:
            value = excerpts[event.locator.event_id]
            events.append(
                replace(event, content=self.redactor.redact(value))
            )
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
