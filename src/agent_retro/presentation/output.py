"""Stable and Unicode-safe AgentRetro output helpers."""

from __future__ import annotations

import json
import sys
from typing import TextIO

from agent_retro.application.brief import (
    BriefResult,
    brief_json_data as _brief_json_data,
    render_brief_markdown as _render_brief_markdown,
    render_brief_terminal as _render_brief_terminal,
)
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

    return _brief_json_data(result)


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
    return _render_brief_markdown(result)


def render_brief_terminal(result: BriefResult) -> str:
    return _render_brief_terminal(result)
