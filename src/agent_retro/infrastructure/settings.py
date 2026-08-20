"""Environment-backed AgentRetro settings without filesystem side effects."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from agent_retro.domain.models import KnowledgeType


@dataclass(frozen=True)
class RetroSettings:
    state_dir: Path
    db_path: Path
    backup_dir: Path
    obsidian_root: Path | None
    brief_max_tokens: int
    discovery_max_files: int
    discovery_timeout_seconds: float
    session_max_bytes: int
    model_timeout_seconds: int | None
    brief_timeout_seconds: float
    thresholds: Mapping[KnowledgeType, float]


def _read_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw_value = values.get(name, str(default))
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer greater than zero") from exc


def _read_float(values: Mapping[str, str], name: str, default: float) -> float:
    raw_value = values.get(name, str(default))
    try:
        return float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number greater than zero") from exc


def load_retro_settings(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> RetroSettings:
    """Load AgentRetro-only settings and validate their safety boundaries."""

    values = dict(os.environ if env is None else env)
    user_home = Path.home() if home is None else Path(home)
    state_dir = Path(values.get("AGENTRETRO_HOME", user_home / ".agentretro"))
    obsidian_value = values.get("AGENTRETRO_OBSIDIAN_ROOT", "").strip()
    model_timeout_value = values.get("AGENTRETRO_MODEL_TIMEOUT_SECONDS", "")
    settings = RetroSettings(
        state_dir=state_dir,
        db_path=Path(values.get("AGENTRETRO_DB_PATH", state_dir / "retro.db")),
        backup_dir=Path(values.get("AGENTRETRO_BACKUP_DIR", state_dir / "backups")),
        obsidian_root=Path(obsidian_value) if obsidian_value else None,
        brief_max_tokens=_read_int(values, "AGENTRETRO_BRIEF_MAX_TOKENS", 6000),
        discovery_max_files=_read_int(values, "AGENTRETRO_DISCOVERY_MAX_FILES", 1000),
        discovery_timeout_seconds=_read_float(
            values, "AGENTRETRO_DISCOVERY_TIMEOUT_SECONDS", 10.0
        ),
        session_max_bytes=_read_int(
            values, "AGENTRETRO_SESSION_MAX_BYTES", 128 * 1024 * 1024
        ),
        model_timeout_seconds=(
            _read_int(values, "AGENTRETRO_MODEL_TIMEOUT_SECONDS", 120)
            if model_timeout_value
            else None
        ),
        brief_timeout_seconds=_read_float(
            values, "AGENTRETRO_BRIEF_TIMEOUT_SECONDS", 5.0
        ),
        thresholds=MappingProxyType(
            {
                KnowledgeType.RULE: 0.97,
                KnowledgeType.LESSON: 0.93,
                KnowledgeType.TASK_STATE: 0.90,
            }
        ),
    )
    _validate_settings(settings)
    return settings


def _validate_settings(settings: RetroSettings) -> None:
    state_root = settings.state_dir.resolve()
    for name, child in (
        ("AGENTRETRO_DB_PATH", settings.db_path),
        ("AGENTRETRO_BACKUP_DIR", settings.backup_dir),
    ):
        resolved_child = child.resolve()
        try:
            resolved_child.relative_to(state_root)
        except ValueError as exc:
            raise ValueError(f"{name} must stay within AGENTRETRO_HOME") from exc

    numeric_limits = (
        ("AGENTRETRO_BRIEF_MAX_TOKENS", settings.brief_max_tokens),
        ("AGENTRETRO_DISCOVERY_MAX_FILES", settings.discovery_max_files),
        (
            "AGENTRETRO_DISCOVERY_TIMEOUT_SECONDS",
            settings.discovery_timeout_seconds,
        ),
        ("AGENTRETRO_SESSION_MAX_BYTES", settings.session_max_bytes),
        ("AGENTRETRO_MODEL_TIMEOUT_SECONDS", settings.model_timeout_seconds),
        ("AGENTRETRO_BRIEF_TIMEOUT_SECONDS", settings.brief_timeout_seconds),
    )
    for name, value in numeric_limits:
        is_non_finite = isinstance(value, float) and not math.isfinite(value)
        if value is not None and (value <= 0 or is_non_finite):
            raise ValueError(f"{name} must be greater than zero")


def effective_model_timeout(
    settings: RetroSettings, legacy: Mapping[str, object]
) -> int:
    """Resolve the bounded model timeout without retaining legacy settings."""

    if settings.model_timeout_seconds is not None:
        return _validated_timeout(
            settings.model_timeout_seconds,
            "AGENTRETRO_MODEL_TIMEOUT_SECONDS",
        )

    for source_key in ("request_timeout", "codex_request_timeout"):
        if source_key in legacy and legacy[source_key] is not None:
            return _validated_timeout(legacy[source_key], source_key)

    return 120


def _validated_timeout(value: object, source_key: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{source_key} must be a positive integer timeout")

    if isinstance(value, int):
        timeout = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{source_key} must be a positive integer timeout")
        timeout = int(value)
    elif isinstance(value, str):
        try:
            timeout = int(value.strip(), 10)
        except ValueError as exc:
            raise ValueError(
                f"{source_key} must be a positive integer timeout"
            ) from exc
    else:
        raise ValueError(f"{source_key} must be a positive integer timeout")

    if timeout <= 0:
        raise ValueError(f"{source_key} must be a positive integer timeout")
    return timeout
