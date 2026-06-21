"""Read Codex-generated task reports from a local snapshot directory."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CodexTaskReport:
    """A normalized view of one Codex unfinished-task snapshot."""

    path: str
    summary_path: str | None
    generated_at: str
    total_unfinished: int
    unfinished: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    completed: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    daily_summary_markdown: str = ""

    @property
    def has_unfinished(self) -> bool:
        return self.total_unfinished > 0 or bool(self.unfinished or self.blocked)


class CodexTaskReportService:
    """Loads daily reports produced by a Codex automation.

    The automation owns Codex thread inspection. ai-node only consumes stable
    JSON files so it is not coupled to Codex's internal session format.
    """

    def __init__(self, report_dir: str):
        self.report_dir = os.path.abspath(report_dir)

    def latest_report(self) -> CodexTaskReport | None:
        reports = self.list_reports()
        return reports[-1] if reports else None

    def list_reports(self) -> list[CodexTaskReport]:
        if not os.path.isdir(self.report_dir):
            return []

        reports: list[CodexTaskReport] = []
        for name in os.listdir(self.report_dir):
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(self.report_dir, name)
            try:
                reports.append(self._load_report(path))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
        return sorted(reports, key=lambda report: (report.generated_at, report.path))

    def _load_report(self, path: str) -> CodexTaskReport:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("Codex task report must be a JSON object.")

        unfinished = _as_list(payload.get("unfinished"))
        blocked = _as_list(payload.get("blocked"))
        completed = _as_list(payload.get("completed"))
        total = payload.get("total_unfinished", len(unfinished) + len(blocked))
        try:
            total_unfinished = int(total)
        except (TypeError, ValueError):
            total_unfinished = len(unfinished) + len(blocked)

        generated_at = str(payload.get("generated_at") or _mtime_iso(path))
        summary = str(payload.get("summary") or "")
        summary_path, daily_summary_markdown = _load_paired_markdown(path)
        return CodexTaskReport(
            path=path,
            summary_path=summary_path if daily_summary_markdown else None,
            generated_at=generated_at,
            total_unfinished=total_unfinished,
            unfinished=unfinished,
            blocked=blocked,
            completed=completed,
            summary=summary,
            daily_summary_markdown=daily_summary_markdown,
        )


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _mtime_iso(path: str) -> str:
    return datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")


def _paired_markdown_path(path: str) -> str:
    root, _ = os.path.splitext(path)
    return f"{root}.md"


def _load_paired_markdown(path: str) -> tuple[str, str]:
    summary_path = _paired_markdown_path(path)
    if not os.path.exists(summary_path):
        return summary_path, ""
    try:
        with open(summary_path, "r", encoding="utf-8") as handle:
            return summary_path, handle.read()
    except OSError:
        return summary_path, ""
