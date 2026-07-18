"""Stable and Unicode-safe AgentRetro output helpers."""

from __future__ import annotations

import json
import sys
from typing import TextIO

from agent_retro.application.brief import BriefResult
from agent_retro.application.doctor import DoctorReport


def safe_text(value: object, encoding: str | None = None) -> str:
    """Replace only characters unsupported by the active output encoding."""

    text = str(value)
    target = encoding or getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(target)
    except UnicodeEncodeError:
        return text.encode(target, errors="replace").decode(target, errors="replace")
    except LookupError:
        return text
    return text


def write_json(value: object, stream: TextIO | None = None) -> None:
    """Write one deterministic JSON value without ASCII-escaping Unicode text."""

    output = sys.stdout if stream is None else stream
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    output.write(safe_text(serialized, getattr(output, "encoding", None)) + "\n")


def brief_json_data(result: BriefResult) -> dict[str, object]:
    """Return the stable JSON view shared by all briefing output modes."""

    return {
        "conflict_ids": list(result.conflict_ids),
        "estimated_tokens": result.estimated_tokens,
        "generated_at": result.generated_at.isoformat(),
        "items": [
            {
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
            for item in result.items
        ],
        "max_tokens": result.max_tokens,
        "omitted": [{"id": item.id, "reason": item.reason} for item in result.omitted],
        "omitted_count": result.omitted_count,
        "project_id": result.project_id,
        "stale_ids": list(result.stale_ids),
        "task": result.task,
        "warnings": list(result.warnings),
    }


def doctor_json_data(report: DoctorReport) -> dict[str, object]:
    """Return the stable, path-free doctor payload."""

    return report.as_dict()


def render_doctor_terminal(report: DoctorReport) -> str:
    lines = ["AgentRetro Doctor"]
    lines.extend(
        f"[{check.status}] {check.name}: {check.summary}; recovery: {check.recovery}"
        for check in report.checks
    )
    return "\n".join(lines) + "\n"


def render_brief_markdown(result: BriefResult) -> str:
    data = brief_json_data(result)
    lines = [
        f"# AgentRetro Brief: {data['project_id']}",
        "",
        f"Task: {data['task']}",
        f"Budget: {data['estimated_tokens']}/{data['max_tokens']}",
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
    return "\n".join(lines) + "\n"


def _append_brief_health(lines: list[str], result: BriefResult) -> None:
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
