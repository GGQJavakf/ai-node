"""Resume safe Codex threads from the latest report snapshot."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ai_todo_assistant.application.ports.workflow_repository import WorkflowRepository
from ai_todo_assistant.domain.workflow import Evidence, EvidenceType, WorkItem, WorkItemSource, now_text


@dataclass(frozen=True)
class CodexThreadResumeOutcome:
    success: bool
    message: str = ""


class CodexThreadResumeClient(Protocol):
    def resume_thread(self, thread_id: str, prompt: str) -> CodexThreadResumeOutcome: ...


class UnavailableCodexThreadResumeClient:
    def resume_thread(self, thread_id: str, prompt: str) -> CodexThreadResumeOutcome:
        return CodexThreadResumeOutcome(
            success=False,
            message="resume client unavailable",
        )


@dataclass(frozen=True)
class CodexResumeCandidate:
    thread_id: str
    title: str
    prompt: str
    status: str
    entry: dict


@dataclass(frozen=True)
class CodexResumeSkip:
    thread_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class CodexResumeAttempt:
    thread_id: str
    title: str
    prompt: str
    success: bool
    message: str
    work_item_id: str


@dataclass(frozen=True)
class CodexResumeResult:
    dry_run: bool = False
    candidates: list[CodexResumeCandidate] = field(default_factory=list)
    skipped: list[CodexResumeSkip] = field(default_factory=list)
    attempts: list[CodexResumeAttempt] = field(default_factory=list)
    report_path: str = ""


class CodexResumeService:
    """Selects safe Codex report entries and resumes them through a client."""

    def __init__(
        self,
        repository: WorkflowRepository,
        client: CodexThreadResumeClient | None = None,
    ):
        self.repository = repository
        self.client = client or UnavailableCodexThreadResumeClient()

    def resume(self, report, dry_run: bool = False, thread_id: str = "") -> CodexResumeResult:
        candidates, skipped = self._select_candidates(report, thread_id=thread_id)
        if dry_run:
            return CodexResumeResult(
                dry_run=True,
                candidates=candidates,
                skipped=skipped,
                report_path=str(getattr(report, "path", "") or ""),
            )

        attempts: list[CodexResumeAttempt] = []
        for candidate in candidates:
            item = self._ensure_work_item(candidate)
            try:
                outcome = self.client.resume_thread(candidate.thread_id, candidate.prompt)
            except Exception as exc:
                outcome = CodexThreadResumeOutcome(success=False, message=f"resume client error: {exc}")
            evidence = self.repository.add_evidence(
                Evidence(
                    work_item_id=item.id,
                    evidence_type=EvidenceType.COMMAND.value,
                    summary=(
                        f"Codex resume {candidate.thread_id}: "
                        f"{'success' if outcome.success else 'failed'}"
                    ),
                    command=f"codex resume {candidate.thread_id}",
                    output_excerpt=_join_excerpt(candidate.prompt, outcome.message),
                    success=outcome.success,
                    source=WorkItemSource.CODEX.value,
                )
            )
            attempts.append(
                CodexResumeAttempt(
                    thread_id=candidate.thread_id,
                    title=candidate.title,
                    prompt=candidate.prompt,
                    success=bool(evidence.success),
                    message=outcome.message,
                    work_item_id=item.id,
                )
            )
        return CodexResumeResult(
            dry_run=False,
            candidates=candidates,
            skipped=skipped,
            attempts=attempts,
            report_path=str(getattr(report, "path", "") or ""),
        )

    def _select_candidates(self, report, thread_id: str = "") -> tuple[list[CodexResumeCandidate], list[CodexResumeSkip]]:
        target = str(thread_id or "").strip()
        candidates: list[CodexResumeCandidate] = []
        skipped: list[CodexResumeSkip] = []
        denied = _blocked_or_completed_entries(report)

        for entry in list(getattr(report, "unfinished", []) or []):
            if not isinstance(entry, dict):
                continue
            candidate, skip = _candidate_from_unfinished(entry)
            entry_thread_id = candidate.thread_id if candidate else skip.thread_id
            if target and entry_thread_id != target:
                continue
            if entry_thread_id and entry_thread_id in denied:
                skipped.append(denied[entry_thread_id])
                continue
            if candidate:
                candidates.append(candidate)
            elif skip:
                skipped.append(skip)

        for bucket_name in ("blocked", "completed"):
            for entry in list(getattr(report, bucket_name, []) or []):
                if not isinstance(entry, dict):
                    continue
                entry_thread_id = _thread_id(entry)
                if target and entry_thread_id != target:
                    continue
                if entry_thread_id and entry_thread_id in denied:
                    already_reported = any(
                        skip.thread_id == entry_thread_id and skip.reason == denied[entry_thread_id].reason
                        for skip in skipped
                    )
                    if already_reported:
                        continue
                skipped.append(
                    CodexResumeSkip(
                        thread_id=entry_thread_id,
                        title=_title(entry, entry_thread_id),
                        reason=f"{bucket_name} bucket entries are not resumeable",
                    )
                )

        if target and not candidates and not skipped:
            skipped.append(CodexResumeSkip(thread_id=target, title=target, reason="thread not found in latest report"))
        return candidates, skipped

    def _ensure_work_item(self, candidate: CodexResumeCandidate) -> WorkItem:
        item = self.repository.find_work_item_by_source(WorkItemSource.CODEX.value, candidate.thread_id)
        if not item:
            item = WorkItem(
                title=candidate.title,
                source=WorkItemSource.CODEX.value,
                source_ref=candidate.thread_id,
                next_action=candidate.prompt,
                project_path=_project_path(candidate.entry),
            )
        item.title = candidate.title or item.title
        item.next_action = candidate.prompt or item.next_action
        item.project_path = _project_path(candidate.entry) or item.project_path
        item.sync_summary = candidate.status or item.sync_summary
        item.last_synced_at = now_text()
        return self.repository.save_work_item(item)


def format_codex_resume_result(result: CodexResumeResult) -> str:
    title = "Codex resume [DRY-RUN]" if result.dry_run else "Codex resume"
    lines = [title, "─" * 80]
    if result.report_path:
        lines.append(f"  report: {result.report_path}")
    if result.dry_run:
        if result.candidates:
            lines.append(f"  可推进: {len(result.candidates)} 项")
            for candidate in result.candidates:
                lines.append(f"  [DRY-RUN] {candidate.thread_id} | {candidate.title}")
                lines.append(f"     prompt: {_excerpt(candidate.prompt)}")
        else:
            lines.append("  可推进: 0 项")
    else:
        if result.attempts:
            lines.append(f"  已尝试: {len(result.attempts)} 项")
            for attempt in result.attempts:
                status = "OK" if attempt.success else "FAIL"
                message = f" | {attempt.message}" if attempt.message else ""
                lines.append(f"  [{status}] {attempt.thread_id} | {attempt.title}{message}")
        else:
            lines.append("  已尝试: 0 项")

    if result.skipped:
        lines.append("")
        lines.append(f"  跳过: {len(result.skipped)} 项")
        for skip in result.skipped[:10]:
            thread = skip.thread_id or "-"
            lines.append(f"  [SKIP] {thread} | {skip.title}: {skip.reason}")
    lines.append("─" * 80)
    return "\n".join(lines)


def _candidate_from_unfinished(entry: dict) -> tuple[CodexResumeCandidate | None, CodexResumeSkip | None]:
    thread_id = _thread_id(entry)
    title = _title(entry, thread_id)
    statuses = _statuses(entry)
    status = _display_status(statuses)
    prompt = _prompt(entry)
    if not thread_id:
        return None, CodexResumeSkip(thread_id="", title=title, reason="缺少 thread id")
    if any(_needs_user(item) for item in statuses):
        return None, CodexResumeSkip(thread_id=thread_id, title=title, reason="需要用户输入")
    blocked_status = next((item for item in statuses if _is_blocked_or_done(item)), "")
    if blocked_status:
        return None, CodexResumeSkip(thread_id=thread_id, title=title, reason=f"status {blocked_status} is not resumeable")
    if not prompt:
        return None, CodexResumeSkip(thread_id=thread_id, title=title, reason="缺少 continuation prompt")
    if not _is_resumeable(entry, statuses):
        return None, CodexResumeSkip(thread_id=thread_id, title=title, reason="not marked resumeable")
    return CodexResumeCandidate(thread_id=thread_id, title=title, prompt=prompt, status=status, entry=entry), None


def _thread_id(entry: dict) -> str:
    return str(entry.get("thread_id") or entry.get("id") or "").strip()


def _title(entry: dict, thread_id: str) -> str:
    return str(entry.get("title") or entry.get("name") or thread_id or "Codex thread").strip()


def _prompt(entry: dict) -> str:
    return str(entry.get("resume_prompt") or entry.get("next_action") or entry.get("next") or "").strip()


def _statuses(entry: dict) -> list[str]:
    statuses = [
        str(entry.get(field) or "").strip().lower()
        for field in ("classification", "status", "state")
    ]
    return [status for status in statuses if status]


def _display_status(statuses: list[str]) -> str:
    return statuses[0] if statuses else ""


def _project_path(entry: dict) -> str:
    return str(entry.get("cwd") or entry.get("project_path") or "").strip()


def _is_resumeable(entry: dict, statuses: list[str]) -> bool:
    marker = entry.get("resume_eligible")
    if marker is True:
        return True
    if isinstance(marker, str) and marker.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    resumeable_statuses = {"continueable", "continuable", "paused", "ready", "needs_action", "needs_resume"}
    return any(status in resumeable_statuses for status in statuses)


def _blocked_or_completed_entries(report) -> dict[str, CodexResumeSkip]:
    denied: dict[str, CodexResumeSkip] = {}
    for bucket_name in ("blocked", "completed"):
        for entry in list(getattr(report, bucket_name, []) or []):
            if not isinstance(entry, dict):
                continue
            thread_id = _thread_id(entry)
            if not thread_id:
                continue
            denied[thread_id] = CodexResumeSkip(
                thread_id=thread_id,
                title=_title(entry, thread_id),
                reason=f"{bucket_name} bucket entries are not resumeable",
            )
    return denied


def _needs_user(status: str) -> bool:
    return status in {"needs_user", "needs_human", "waiting_user", "user_input_required"}


def _is_blocked_or_done(status: str) -> bool:
    return status in {"blocked", "complete", "completed", "done"}


def _join_excerpt(prompt: str, message: str) -> str:
    parts = [f"prompt: {_excerpt(prompt)}"]
    if message:
        parts.append(f"result: {message}")
    return "\n".join(parts)


def _excerpt(value: str, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit - 3]}..."
