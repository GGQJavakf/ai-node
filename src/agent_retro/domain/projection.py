"""Canonical projection identity and fence errors shared across layers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from agent_retro.domain.models import Knowledge


class ProjectionFenceError(RuntimeError):
    """The authoritative project state moved beyond a projection event."""


def projection_input_hash(knowledge: Sequence[Knowledge]) -> str:
    payload = [
        [
            item.id,
            item.version,
            item.knowledge_type.value,
            item.scope,
            item.status,
            item.text,
            item.updated_at.isoformat(),
        ]
        for item in sorted(knowledge, key=lambda value: value.id)
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
