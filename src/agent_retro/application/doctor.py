"""Read-only AgentRetro readiness diagnostics with redacted summaries."""

from __future__ import annotations

import locale
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHECK_ORDER = (
    "codex_source",
    "safety_limits",
    "database",
    "migration",
    "model",
    "obsidian_root",
    "project_mapping",
    "backup_path",
    "sync_recovery",
    "purge_recovery",
    "codex_integration",
    "codex_override",
    "console_encoding",
)


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    summary: str
    recovery: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "recovery": self.recovery,
        }


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    def by_name(self, name: str) -> DoctorCheck:
        return next(check for check in self.checks if check.name == name)

    @property
    def exit_code(self) -> int:
        return 2 if any(check.status == "error" for check in self.checks) else 0

    def as_dict(self) -> dict[str, object]:
        return {
            "checks": [check.as_dict() for check in self.checks],
            "overall_status": "error" if self.exit_code else "ok",
        }


class DoctorService:
    """Inspect readiness without writing any configured location."""

    def __init__(
        self,
        settings: Any,
        repository: Any,
        *,
        codex_home: Path,
        model_config_loader: Callable[[], Mapping[str, object]],
        integration_discoverer: Callable[[Path], bool] = lambda _: False,
        console_encoding: Callable[[], str | None] = lambda: (
            locale.getpreferredencoding(False)
        ),
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.codex_home = Path(codex_home)
        self.model_config_loader = model_config_loader
        self.integration_discoverer = integration_discoverer
        self.console_encoding = console_encoding

    def run(self) -> DoctorReport:
        checks = {
            "codex_source": self._codex_source(),
            "safety_limits": self._safety_limits(),
            "database": self._database(),
            "migration": self._migration(),
            "model": self._model(),
            "obsidian_root": self._obsidian_root(),
            "project_mapping": self._project_mapping(),
            "backup_path": self._backup_path(),
            "sync_recovery": self._sync_recovery(),
            "purge_recovery": self._purge_recovery(),
            "codex_integration": self._codex_integration(),
            "codex_override": self._codex_override(),
            "console_encoding": self._console_encoding(),
        }
        return DoctorReport(tuple(checks[name] for name in CHECK_ORDER))

    @staticmethod
    def _check(name: str, status: str, summary: str, recovery: str = "none"):
        return DoctorCheck(name, status, summary, recovery)

    def _codex_source(self) -> DoctorCheck:
        sessions = self.codex_home / "sessions"
        healthy = (
            self.codex_home.is_dir()
            and sessions.is_dir()
            and os.access(sessions, os.R_OK)
        )
        if healthy:
            return self._check("codex_source", "healthy", "available")
        return self._check(
            "codex_source",
            "error",
            "unavailable",
            "configure CODEX_HOME or restore readable sessions",
        )

    def _safety_limits(self) -> DoctorCheck:
        values = (
            self.settings.discovery_max_files,
            self.settings.discovery_timeout_seconds,
            self.settings.session_max_bytes,
            self.settings.brief_max_tokens,
            self.settings.brief_timeout_seconds,
        )
        if all(value > 0 for value in values):
            return self._check("safety_limits", "healthy", "configured")
        return self._check(
            "safety_limits", "error", "invalid", "fix AGENTRETRO limit settings"
        )

    def _schema_version(self) -> int | None:
        try:
            return int(self.repository.schema_version())
        except Exception:
            return None

    def _database(self) -> DoctorCheck:
        if not self.settings.db_path.is_file():
            return self._check(
                "database", "warning", "missing", "run an AgentRetro state command"
            )
        version = self._schema_version()
        if version is None:
            return self._check(
                "database", "error", "unreadable", "restore a verified database backup"
            )
        return self._check("database", "healthy", "readable")

    def _migration(self) -> DoctorCheck:
        version = self._schema_version()
        if version == 2:
            return self._check("migration", "healthy", "current")
        if version is None:
            return self._check(
                "migration", "error", "unknown", "repair database before migration"
            )
        return self._check(
            "migration", "warning", "pending", "run a backed-up AgentRetro migration"
        )

    def _model(self) -> DoctorCheck:
        try:
            model = self.model_config_loader().get("model")
        except Exception:
            model = None
        configured = isinstance(model, str) and bool(model.strip())
        return self._check(
            "model",
            "healthy" if configured else "warning",
            "configured" if configured else "missing",
            "none" if configured else "configure the existing ai-todo model",
        )

    def _obsidian_root(self) -> DoctorCheck:
        root = self.settings.obsidian_root
        if root is None:
            return self._check(
                "obsidian_root",
                "warning",
                "missing",
                "configure AGENTRETRO_OBSIDIAN_ROOT",
            )
        if (
            root.is_dir()
            and not _has_symlink_component(root)
            and os.access(root, os.W_OK)
        ):
            return self._check("obsidian_root", "healthy", "available")
        return self._check(
            "obsidian_root",
            "error",
            "unsafe_or_unavailable",
            "repair the configured vault root",
        )

    def _project_mapping(self) -> DoctorCheck:
        try:
            mappings: Sequence[object] = self.repository.list_project_mappings()
        except Exception:
            return self._check(
                "project_mapping", "error", "unavailable", "repair mapping storage"
            )
        if mappings:
            return self._check(
                "project_mapping", "healthy", f"configured:{len(mappings)}"
            )
        return self._check("project_mapping", "warning", "missing", "retro project map")

    def _backup_path(self) -> DoctorCheck:
        path = self.settings.backup_dir
        try:
            path.resolve().relative_to(self.settings.state_dir.resolve())
        except ValueError:
            return self._check(
                "backup_path", "error", "unsafe", "restore AgentRetro path containment"
            )
        if path.is_dir() and os.access(path, os.W_OK):
            return self._check("backup_path", "healthy", "available")
        return self._check(
            "backup_path",
            "warning",
            "not_created",
            "create through a backed-up write operation",
        )

    def _sync_recovery(self) -> DoctorCheck:
        try:
            jobs = tuple(self.repository.rollback_required_sync_jobs())
        except Exception:
            try:
                blocked = bool(self.repository.has_rollback_required_sync())
            except Exception:
                return self._check(
                    "sync_recovery",
                    "error",
                    "unavailable",
                    "repair sync journal storage",
                )
            if not blocked:
                return self._check("sync_recovery", "healthy", "clear")
            return self._check(
                "sync_recovery",
                "error",
                "rollback_required",
                "recover the blocked sync run from its verified backup",
            )
        if not jobs:
            return self._check("sync_recovery", "healthy", "clear")
        run_ids = ",".join(sorted(_safe_identity(job.id) for job in jobs))
        return self._check(
            "sync_recovery",
            "error",
            "rollback_required",
            f"recover sync run {run_ids} from its verified backup",
        )

    def _purge_recovery(self) -> DoctorCheck:
        try:
            incomplete = bool(self.repository.has_purge_incomplete())
        except Exception:
            return self._check(
                "purge_recovery", "error", "unavailable", "repair purge journal storage"
            )
        if incomplete:
            return self._check(
                "purge_recovery",
                "error",
                "purge_incomplete",
                "resume exact purge operations",
            )
        return self._check("purge_recovery", "healthy", "clear")

    def _codex_integration(self) -> DoctorCheck:
        if self.integration_discoverer(self.codex_home):
            return self._check("codex_integration", "healthy", "installed")
        return self._check(
            "codex_integration", "warning", "not_installed", "retro integrate codex"
        )

    def _codex_override(self) -> DoctorCheck:
        override = self.codex_home / "AGENTS.override.md"
        if override.exists() or override.is_symlink():
            return self._check(
                "codex_override",
                "error",
                "override_present",
                "remove or reconcile the Codex override",
            )
        return self._check("codex_override", "healthy", "clear")

    def _console_encoding(self) -> DoctorCheck:
        try:
            encoding = (self.console_encoding() or "").lower()
        except Exception:
            encoding = ""
        if encoding.replace("_", "-") in {
            "utf-8",
            "utf8",
            "gbk",
            "cp936",
            "gb18030",
        }:
            return self._check("console_encoding", "healthy", "configured")
        return self._check(
            "console_encoding", "warning", "unknown", "configure a UTF-8 or GBK console"
        )


def _has_symlink_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _safe_identity(value: object) -> str:
    text = str(value)
    if text and all(character.isalnum() or character in "-_.:" for character in text):
        return text
    return "redacted-run-id"
