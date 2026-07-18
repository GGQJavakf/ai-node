"""Stable and Unicode-safe AgentRetro output helpers."""

from __future__ import annotations

import json
import sys
from typing import TextIO


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
