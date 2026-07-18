"""Recoverable Obsidian synchronization after committed knowledge changes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import ProjectionStatus, SyncJob
from agent_retro.infrastructure.obsidian import (
    BoundaryError,
    ObsidianProjection,
    SyncPlan,
    UnsafeVaultPathError,
    managed_block_hash,
    sha256_bytes,
)


@dataclass(frozen=True)
class ProjectionResult:
    event_id: str
    status: ProjectionStatus
    warning: str = ""
    recovery_command: str = ""


class SyncService:
    """Preflight, journal, atomically replace, verify, and compensate a plan."""

    def __init__(
        self,
        repository: RetroRepository,
        vault_root: Path,
        backup_root: Path,
        *,
        replace: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        self.repository = repository
        self.vault_root = Path(vault_root)
        self.backup_root = Path(backup_root)
        self.replace = replace

    def apply(self, plan: SyncPlan, *, event_id: str) -> ProjectionResult:
        if self.repository.has_rollback_required_sync():
            return self._finish(
                event_id,
                ProjectionStatus.ROLLBACK_REQUIRED,
                "previous synchronization requires rollback recovery",
            )
        try:
            snapshots = self._preflight(plan)
        except (BoundaryError, OSError, RuntimeError, ValueError):
            return self._finish(event_id, ProjectionStatus.SYNC_PENDING, "preflight_failed")

        backup_dir = plan.backup_dir
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            for target, before in snapshots.items():
                if before is None:
                    continue
                backup = self._backup_path(backup_dir, target)
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(before)
        except OSError:
            return self._finish(event_id, ProjectionStatus.SYNC_PENDING, "backup_failed")

        job = SyncJob(
            id=event_id,
            project_id=plan.project_id,
            status=ProjectionStatus.SYNC_PENDING.value,
            plan_json=self._plan_json(plan),
            backup_path=backup_dir,
        )
        self.repository.begin_sync(job)
        try:
            for write in plan.writes:
                self._atomic_replace(write.target, write.after_bytes)
                if write.target.read_bytes() != write.after_bytes:
                    raise OSError(f"post-write readback mismatch: {write.target}")
        except (OSError, RuntimeError):
            rollback_error = self._restore(plan, snapshots)
            status = (
                ProjectionStatus.ROLLBACK_REQUIRED
                if rollback_error
                else ProjectionStatus.SYNC_PENDING
            )
            error = "write_failed" if not rollback_error else "rollback_failed"
            self.repository.finish_sync(event_id, status.value, error)
            return self._finish(event_id, status, error)

        states = [
            (
                write.target,
                write.after_managed_hash or sha256_bytes(write.after_bytes),
                sha256_bytes(write.after_bytes),
            )
            for write in plan.writes
        ]
        try:
            self.repository.complete_sync(event_id, plan.project_id, states)
        except (OSError, RuntimeError, ValueError):
            rollback_error = self._restore(plan, snapshots)
            status = (
                ProjectionStatus.ROLLBACK_REQUIRED
                if rollback_error
                else ProjectionStatus.SYNC_PENDING
            )
            error = "rollback_failed" if rollback_error else "journal_finalize_failed"
            self.repository.finish_sync(event_id, status.value, error)
            return self._finish(event_id, status, error)
        return ProjectionResult(event_id, ProjectionStatus.SYNCED)

    def enumerate_backups_containing(self, content_hash: str) -> tuple[Path, ...]:
        found = []
        if not self.backup_root.exists():
            return ()
        for path in sorted(self.backup_root.rglob("*"), key=lambda item: str(item)):
            if path.is_symlink() or not path.is_file():
                continue
            if sha256_bytes(path.read_bytes()) == content_hash:
                found.append(path)
        return tuple(found)

    def remove_confirmed_backup_copy(self, path: Path, expected_hash: str) -> None:
        target = Path(path)
        try:
            target.resolve(strict=True).relative_to(self.backup_root.resolve(strict=True))
        except (FileNotFoundError, ValueError) as exc:
            raise ValueError("backup copy is outside configured backup root") from exc
        if target.is_symlink() or sha256_bytes(target.read_bytes()) != expected_hash:
            raise ValueError("backup copy hash does not match confirmed content")
        target.unlink()
        if target.exists():
            raise OSError(f"backup copy could not be removed: {target}")

    def _preflight(self, plan: SyncPlan) -> dict[Path, bytes | None]:
        if not self.vault_root.exists() or not self.vault_root.is_dir():
            raise OSError("configured Obsidian vault is unavailable")
        mappings = [
            item
            for item in self.repository.list_project_mappings()
            if item.obsidian_project == plan.project_id
        ]
        if len(mappings) != 1:
            raise ValueError("project does not have exactly one active vault mapping")
        self._validate_backup_dir(plan.backup_dir)
        root = self.vault_root.resolve(strict=True)
        snapshots: dict[Path, bytes | None] = {}
        for write in plan.writes:
            try:
                write.target.resolve(strict=False).relative_to(root)
            except ValueError as exc:
                raise UnsafeVaultPathError("planned target escapes vault") from exc
            current = self.vault_root
            relative = write.target.relative_to(self.vault_root)
            for part in relative.parts:
                current = current / part
                if current.exists() and current.is_symlink():
                    raise UnsafeVaultPathError(f"unexpected symlink: {current}")
            before = write.target.read_bytes() if write.target.exists() else None
            if sha256_bytes(before or b"") != write.before_hash:
                raise ValueError(f"target changed after planning: {write.target}")
            state = self.repository.get_managed_file_state(write.target)
            if state is not None:
                current_managed = self._current_managed_hash(write.target, before or b"")
                if state.managed_hash != current_managed:
                    raise ValueError(f"managed content changed externally: {write.target}")
            snapshots[write.target] = before
        return snapshots

    def _validate_backup_dir(self, backup_dir: Path) -> None:
        if self.backup_root.is_symlink():
            raise ValueError("configured backup root must not be a symlink")
        try:
            relative = backup_dir.relative_to(self.backup_root)
        except ValueError as exc:
            raise ValueError("plan backup escapes configured backup root") from exc
        current = self.backup_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("plan backup contains an unexpected symlink")
        root = self.backup_root.resolve(strict=False)
        try:
            backup_dir.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise ValueError("plan backup escapes configured backup root") from exc

    @staticmethod
    def _current_managed_hash(target: Path, content: bytes) -> str:
        if target.name.startswith("项目_") or target.name == "项目索引.md":
            return managed_block_hash(content)
        return sha256_bytes(content)

    def _restore(
        self, plan: SyncPlan, snapshots: dict[Path, bytes | None]
    ) -> str:
        errors = []
        for target, before in snapshots.items():
            try:
                if before is None:
                    if target.exists():
                        target.unlink()
                else:
                    self._atomic_replace(target, before)
                restored = target.read_bytes() if target.exists() else b""
                if sha256_bytes(restored) != sha256_bytes(before or b""):
                    raise OSError(f"restored hash mismatch: {target}")
            except OSError as exc:
                errors.append(str(exc))
        return "; ".join(errors)

    def _atomic_replace(self, target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temp = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def _backup_path(self, backup_dir: Path, target: Path) -> Path:
        return backup_dir / target.relative_to(self.vault_root)

    @staticmethod
    def _plan_json(plan: SyncPlan) -> str:
        return json.dumps(
            {
                "id": plan.id,
                "project_id": plan.project_id,
                "writes": [
                    {
                        "target": str(write.target),
                        "before_hash": write.before_hash,
                        "after_hash": sha256_bytes(write.after_bytes),
                    }
                    for write in plan.writes
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _finish(
        self, event_id: str, status: ProjectionStatus, error: str
    ) -> ProjectionResult:
        self.repository.finish_projection_event(event_id, status, error)
        if status is ProjectionStatus.SYNCED:
            return ProjectionResult(event_id, status)
        command = (
            "retro doctor --repair-sync"
            if status is ProjectionStatus.ROLLBACK_REQUIRED
            else f"retro sync retry {event_id}"
        )
        warning = (
            "RETRO_ROLLBACK_REQUIRED"
            if status is ProjectionStatus.ROLLBACK_REQUIRED
            else "RETRO_SYNC_PENDING"
        )
        return ProjectionResult(event_id, status, warning, command)


class ProjectionCoordinator:
    """Create/reuse one event only after the authoritative transaction commits."""

    def __init__(
        self,
        repository: RetroRepository,
        projection: ObsidianProjection,
        sync: SyncService,
    ) -> None:
        self.repository = repository
        self.projection = projection
        self.sync = sync

    def after_commit(
        self, cause: str, entity_id: str, project_id: str
    ) -> ProjectionResult:
        knowledge = self.repository.list_project_knowledge(project_id)
        input_hash = _eligible_hash(knowledge)
        raw = json.dumps(
            [project_id, cause, entity_id, input_hash],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        event_id = "projection-" + hashlib.sha256(raw.encode()).hexdigest()[:24]
        event_id = self.repository.save_projection_event(
            event_id, project_id, cause, entity_id, input_hash
        )
        existing = self.repository.get_projection_event(event_id)
        if existing is not None and existing.status is ProjectionStatus.SYNCED:
            return ProjectionResult(event_id, ProjectionStatus.SYNCED)
        try:
            plan = self.projection.plan(project_id, knowledge, event_id=event_id)
        except (BoundaryError, OSError, ValueError) as exc:
            return self.sync._finish(event_id, ProjectionStatus.SYNC_PENDING, str(exc))
        return self.sync.apply(plan, event_id=event_id)

    def retry(self, event_id: str) -> ProjectionResult:
        event = self.repository.get_projection_event(event_id)
        if event is None:
            raise KeyError(f"projection event not found: {event_id}")
        if event.status is ProjectionStatus.ROLLBACK_REQUIRED:
            return ProjectionResult(
                event.id,
                event.status,
                event.error,
                "retro doctor --repair-sync",
            )
        knowledge = self.repository.list_project_knowledge(event.project_id)
        plan = self.projection.plan(event.project_id, knowledge, event_id=event.id)
        return self.sync.apply(plan, event_id=event.id)


def _eligible_hash(knowledge) -> str:
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
