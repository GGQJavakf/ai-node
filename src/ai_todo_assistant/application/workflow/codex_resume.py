"""Resume safe Codex threads from the latest report snapshot."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from ai_todo_assistant.application.ports.codex_resume_client import CodexThreadResumeClient, CodexThreadResumeOutcome
from ai_todo_assistant.application.ports.workflow_repository import WorkflowRepository
from ai_todo_assistant.domain.workflow import Evidence, EvidenceType, WorkItem, WorkItemSource, now_text


@dataclass(frozen=True)
class CodexResumeExclusion:
    thread_id: str
    reason: str = ""
    created_at: str = ""


class CodexResumeExclusionStore(Protocol):
    def list_exclusions(self) -> list[CodexResumeExclusion]: ...
    def exclude(self, thread_id: str, reason: str = "") -> CodexResumeExclusion: ...
    def include(self, thread_id: str) -> bool: ...


class UnavailableCodexThreadResumeClient:
    def resume_thread(self, thread_id: str, prompt: str) -> CodexThreadResumeOutcome:
        return CodexThreadResumeOutcome(
            success=False,
            message="resume client unavailable",
        )


class CodexResumeExclusionService:
    """Manages manual exclusions through an application-level use case."""

    def __init__(self, store: CodexResumeExclusionStore):
        self.store = store

    def list_exclusions(self) -> list[CodexResumeExclusion]:
        return self.store.list_exclusions()

    def exclude(self, thread_id: str, reason: str = "") -> CodexResumeExclusion:
        return self.store.exclude(thread_id, reason)

    def include(self, thread_id: str) -> bool:
        return self.store.include(thread_id)


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


@dataclass(frozen=True)
class CodexResumeDisplayRow:
    index: int
    status: str
    thread_id: str
    title: str
    note: str
    progress: str = ""
    next_action: str = ""


class CodexResumeService:
    """Selects safe Codex report entries and resumes them through a client."""

    def __init__(
        self,
        repository: WorkflowRepository,
        client: CodexThreadResumeClient | None = None,
        exclusion_store: CodexResumeExclusionStore | None = None,
    ):
        self.repository = repository
        self.client = client or UnavailableCodexThreadResumeClient()
        self.exclusion_store = exclusion_store

    def resume(
        self,
        report,
        dry_run: bool = False,
        thread_id: str = "",
        respect_exclusions: bool | None = None,
        skip_repeated: bool | None = None,
    ) -> CodexResumeResult:
        is_targeted = bool(str(thread_id or "").strip())
        if respect_exclusions is None:
            respect_exclusions = not is_targeted
        if skip_repeated is None:
            skip_repeated = not is_targeted
        candidates, skipped = self._select_candidates(
            report,
            thread_id=thread_id,
            respect_exclusions=respect_exclusions,
        )
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
            if skip_repeated and self._has_successful_resume_evidence(item.id, candidate):
                skipped.append(
                    CodexResumeSkip(
                        thread_id=candidate.thread_id,
                        title=candidate.title,
                        reason="already resumed successfully for same prompt",
                    )
                )
                continue
            if skip_repeated and self._has_failed_resume_evidence(item.id, candidate):
                skipped.append(
                    CodexResumeSkip(
                        thread_id=candidate.thread_id,
                        title=candidate.title,
                        reason="already failed for same prompt",
                    )
                )
                continue
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

    def _select_candidates(
        self,
        report,
        thread_id: str = "",
        respect_exclusions: bool = True,
    ) -> tuple[list[CodexResumeCandidate], list[CodexResumeSkip]]:
        target = str(thread_id or "").strip()
        candidates: list[CodexResumeCandidate] = []
        skipped: list[CodexResumeSkip] = []
        denied = _blocked_or_completed_entries(report)
        exclusions, exclusion_error = self._manual_exclusions() if respect_exclusions else ({}, "")
        if exclusion_error:
            return [], [
                CodexResumeSkip(
                    thread_id="",
                    title="Codex resume exclusions",
                    reason=f"manual exclusion policy unavailable: {exclusion_error}",
                )
            ]

        for entry in list(getattr(report, "unfinished", []) or []):
            if not isinstance(entry, dict):
                continue
            entry_thread_id = _thread_id(entry)
            if target and entry_thread_id != target:
                continue
            if entry_thread_id and entry_thread_id in denied:
                skipped.append(denied[entry_thread_id])
                continue
            if entry_thread_id and entry_thread_id in exclusions:
                skipped.append(
                    CodexResumeSkip(
                        thread_id=entry_thread_id,
                        title=_title(entry, entry_thread_id),
                        reason=_manual_exclusion_reason(exclusions[entry_thread_id]),
                    )
                )
                continue
            candidate, skip = _candidate_from_unfinished(entry)
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

    def _manual_exclusions(self) -> tuple[dict[str, CodexResumeExclusion], str]:
        if not self.exclusion_store:
            return {}, ""
        try:
            exclusions = {
                exclusion.thread_id: exclusion
                for exclusion in self.exclusion_store.list_exclusions()
                if exclusion.thread_id
            }
        except Exception as exc:
            return {}, str(exc) or exc.__class__.__name__
        return exclusions, ""

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

    def _has_successful_resume_evidence(self, work_item_id: str, candidate: CodexResumeCandidate) -> bool:
        return self._has_resume_evidence(work_item_id, candidate, success=True)

    def _has_failed_resume_evidence(self, work_item_id: str, candidate: CodexResumeCandidate) -> bool:
        return self._has_resume_evidence(work_item_id, candidate, success=False)

    def _has_resume_evidence(self, work_item_id: str, candidate: CodexResumeCandidate, success: bool) -> bool:
        marker = _resume_prompt_hash_marker(candidate.prompt)
        command = f"codex resume {candidate.thread_id}"
        for evidence in self.repository.list_evidence(work_item_id):
            if evidence.source != WorkItemSource.CODEX.value:
                continue
            if evidence.evidence_type != EvidenceType.COMMAND.value:
                continue
            if evidence.command != command or evidence.success is not success:
                continue
            if marker in evidence.output_excerpt:
                return True
        return False


def format_codex_resume_result(result: CodexResumeResult) -> str:
    title = "Codex resume [DRY-RUN]" if result.dry_run else "Codex resume"
    lines = [title, "─" * 80]
    if result.report_path:
        lines.append(f"  report: {result.report_path}")
    rows = codex_resume_display_rows(result)
    if result.dry_run:
        lines.append(f"  进度: 可推进 {len(result.candidates)} 项；暂不推进 {len(result.skipped)} 项；总计 {len(rows)} 项")
        if result.candidates:
            lines.append(f"  建议: /r all 批量推进 {len(result.candidates)} 项，或 /r <序号> 单独推进")
        else:
            lines.append("  建议: 当前没有可自动推进项，先处理暂不推进任务的原因")
    else:
        lines.append(f"  进度: 已尝试 {len(result.attempts)} 项；暂不推进 {len(result.skipped)} 项；总计 {len(rows)} 项")
        if result.attempts:
            failed = len([attempt for attempt in result.attempts if not attempt.success])
            lines.append(f"  结果: 成功 {len(result.attempts) - failed} 项；失败 {failed} 项")
        else:
            lines.append("  结果: 未发送任何继续请求")

    if rows:
        visible_rows = rows[:20]
        _append_resume_section(
            lines,
            "可推进任务",
            [row for row in visible_rows if row.status == "READY"],
        )
        _append_resume_section(
            lines,
            "已尝试任务",
            [row for row in visible_rows if row.status in {"OK", "FAIL"}],
        )
        _append_resume_section(
            lines,
            "暂不推进任务",
            [row for row in visible_rows if row.status == "SKIP"],
        )
        if len(rows) > 20:
            lines.append(f"  ... 还有 {len(rows) - 20} 项未显示")
        lines.append("  提示: /r <序号> 手动推进；/r skip <序号> 排除自动推进")

    if result.skipped and not result.dry_run:
        lines.append("")
        lines.append(f"  跳过: {len(result.skipped)} 项")
    lines.append("─" * 80)
    return "\n".join(lines)


def codex_resume_display_rows(result: CodexResumeResult) -> list[CodexResumeDisplayRow]:
    rows: list[CodexResumeDisplayRow] = []
    if result.dry_run:
        for candidate in result.candidates:
            rows.append(
                CodexResumeDisplayRow(
                    index=len(rows) + 1,
                    status="READY",
                    thread_id=candidate.thread_id,
                    title=candidate.title,
                    note="可推进",
                    progress="暂停，可继续",
                    next_action=candidate.prompt,
                )
            )
    for attempt in result.attempts:
        rows.append(
            CodexResumeDisplayRow(
                index=len(rows) + 1,
                status="OK" if attempt.success else "FAIL",
                thread_id=attempt.thread_id,
                title=attempt.title,
                note=attempt.message,
                progress="已发送" if attempt.success else "发送失败",
                next_action=attempt.message or ("等待 Codex 继续执行" if attempt.success else "检查失败原因后可手动重试"),
            )
        )
    for skip in result.skipped:
        rows.append(
            CodexResumeDisplayRow(
                index=len(rows) + 1,
                status="SKIP",
                thread_id=skip.thread_id or "",
                title=skip.title,
                note=skip.reason,
                progress=_skip_progress(skip.reason),
                next_action=_skip_next_action(skip.reason),
            )
        )
    return rows


def _append_resume_section(lines: list[str], title: str, rows: list[CodexResumeDisplayRow]) -> None:
    if not rows:
        return
    lines.append("")
    lines.append(f"{title}:")
    lines.extend(
        _format_text_table(
            ["#", "状态", "任务", "当前进度", "后续推进方向"],
            [[str(row.index), row.status, row.title, row.progress, row.next_action] for row in rows],
        )
    )


def _format_text_table(headers: list[str], rows: list[list[str]], max_width: int = 118) -> list[str]:
    widths = _table_widths(headers, rows, max_width)
    border = "  +" + "+".join("-" * (width + 2) for width in widths) + "+"
    lines = [border, _format_table_row(headers, widths), border]
    for row in rows:
        lines.append(_format_table_row([_excerpt(cell, width) for cell, width in zip(row, widths)], widths))
    lines.append(border)
    return lines


def _table_widths(headers: list[str], rows: list[list[str]], max_width: int) -> list[int]:
    floor_by_header = {
        "#": 3,
        "状态": 6,
        "thread": 12,
        "title": 12,
        "任务": 18,
        "当前进度": 12,
        "后续推进方向": 24,
        "prompt": 16,
        "reason": 16,
        "说明": 16,
        "message": 16,
    }
    cap_by_header = {
        "#": 4,
        "状态": 8,
        "thread": 32,
        "title": 46,
        "任务": 44,
        "当前进度": 24,
        "后续推进方向": 50,
        "prompt": 42,
        "reason": 42,
        "说明": 44,
        "message": 42,
    }
    floors = [floor_by_header.get(header, 8) for header in headers]
    widths = [
        max(
            floors[index],
            min(
                max(len(str(row[index] if index < len(row) else "")) for row in [headers, *rows]),
                cap_by_header.get(headers[index], 24),
            ),
        )
        for index in range(len(headers))
    ]
    total = sum(widths) + len(widths) * 3 + 3
    while total > max_width and any(width > floor for width, floor in zip(widths, floors)):
        index = max(range(len(widths)), key=lambda item: widths[item] - floors[item])
        widths[index] -= 1
        total = sum(widths) + len(widths) * 3 + 3
    return widths


def _format_table_row(values: list[str], widths: list[int]) -> str:
    cells = []
    for value, width in zip(values, widths):
        text = _excerpt(value, width)
        cells.append(f" {text.ljust(width)} ")
    return "  |" + "|".join(cells) + "|"


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
    if _looks_like_manual_action_prompt(prompt):
        return None, CodexResumeSkip(thread_id=thread_id, title=title, reason="需要用户输入")
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


def _skip_progress(reason: str) -> str:
    text = str(reason or "").lower()
    if "completed bucket" in text:
        return "已完成"
    if "blocked bucket" in text:
        return "阻塞中"
    if "manual exclusion" in text:
        return "已手动排除"
    if "需要用户输入" in reason:
        return "需要用户输入"
    if "缺少 thread id" in reason:
        return "缺少线程 ID"
    if "缺少 continuation prompt" in reason:
        return "缺少后续指令"
    if "not marked resumeable" in text:
        return "未标记可继续"
    if "already resumed successfully" in text:
        return "同指令已推进"
    if "already failed" in text:
        return "同指令曾失败"
    if "manual exclusion policy unavailable" in text:
        return "排除列表不可用"
    if "not resumeable" in text:
        return "不可自动推进"
    return reason or "暂不推进"


def _skip_next_action(reason: str) -> str:
    text = str(reason or "").lower()
    if "completed bucket" in text:
        return "无需继续推进"
    if "blocked bucket" in text:
        return "等待阻塞解除或人工确认"
    if "manual exclusion" in text:
        return "需要恢复自动推进时执行 /r unskip <序号>"
    if "需要用户输入" in reason:
        return "补充用户输入后再生成可推进指令"
    if "缺少 thread id" in reason:
        return "更新 report，补充稳定 thread_id"
    if "缺少 continuation prompt" in reason:
        return "更新 report，补充 next_action/resume_prompt"
    if "not marked resumeable" in text:
        return "确认安全后标记 resume_eligible 或 continueable"
    if "already resumed successfully" in text:
        return "无需重复发送"
    if "already failed" in text:
        return "排查失败原因；必要时 /r <序号> 手动重试"
    if "manual exclusion policy unavailable" in text:
        return "修复排除列表文件后重试"
    if "not resumeable" in text:
        return "确认状态后再重新纳入自动推进"
    return "查看原因后人工判断"


def _looks_like_manual_action_prompt(prompt: str) -> bool:
    text = str(prompt or "").lower()
    manual_markers = [
        "人工确认",
        "人工将",
        "人工处理",
        "等待人工",
        "等待用户",
        "需要用户",
        "用户输入",
        "人为确认",
        "权限",
        "审批",
        "释放占用",
        "manual",
        "human",
        "user input",
        "waiting user",
    ]
    return any(marker in text for marker in manual_markers)


def _manual_exclusion_reason(exclusion: CodexResumeExclusion) -> str:
    if exclusion.reason:
        return f"manual exclusion: {exclusion.reason}"
    return "manual exclusion"


def _join_excerpt(prompt: str, message: str) -> str:
    parts = [_resume_prompt_hash_marker(prompt), _resume_prompt_marker(prompt)]
    if message:
        parts.append(f"result: {message}")
    return "\n".join(parts)


def _resume_prompt_hash_marker(prompt: str) -> str:
    digest = hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()
    return f"prompt_sha256: {digest}"


def _resume_prompt_marker(prompt: str) -> str:
    return f"prompt: {_excerpt(prompt)}"


def _excerpt(value: str, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit - 3]}..."
