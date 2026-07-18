"""Recoverable Obsidian synchronization after committed knowledge changes."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import ProjectionEvent, ProjectionStatus, SyncJob
from agent_retro.domain.projection import ProjectionFenceError, projection_input_hash
from agent_retro.infrastructure.obsidian import (
    BoundaryError,
    ObsidianProjection,
    SyncPlan,
    UnsafeVaultPathError,
    VaultNotConfiguredError,
    managed_block_hash,
    sha256_bytes,
)


@dataclass(frozen=True)
class ProjectionResult:
    event_id: str
    status: ProjectionStatus
    warning: str = ""
    recovery_command: str = ""
    reason: str = ""


class ProjectionLockBusy(RuntimeError):
    """A project projection is already active in another thread/process."""


class ProjectionPersistenceError(RuntimeError):
    """A sanitized synchronization-state persistence failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.recovery_command = "retro doctor --repair-sync"


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class SyncService:
    """Preflight, journal, atomically replace, verify, and compensate a plan."""

    def __init__(
        self,
        repository: RetroRepository,
        vault_root: Path | None,
        backup_root: Path,
        *,
        replace: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        self.repository = repository
        self.vault_root = None if vault_root is None else Path(vault_root)
        self.backup_root = Path(backup_root)
        self.replace = replace

    def apply(self, plan: SyncPlan, *, event_id: str) -> ProjectionResult:
        event = self.repository.get_projection_event(event_id)
        if event is None:
            raise ProjectionPersistenceError("projection_event_not_found")
        if (
            plan.event_id != event_id
            or plan.project_id != event.project_id
            or plan.input_hash != event.input_hash
        ):
            return self._finish(
                event_id,
                ProjectionStatus.SYNC_PENDING,
                "projection_identity_mismatch",
            )
        canonical = self._canonical_automatic_plan(event)
        if canonical is None or plan != canonical:
            return self._finish(
                event_id,
                ProjectionStatus.SYNC_PENDING,
                "projection_identity_mismatch",
            )
        try:
            with self._project_lock(plan.project_id):
                current_event = self.repository.get_projection_event(event_id)
                if current_event is None:
                    raise ProjectionPersistenceError("projection_event_not_found")
                canonical = self._canonical_automatic_plan(current_event)
                if canonical is None:
                    return self._finish(
                        event_id,
                        ProjectionStatus.SYNC_PENDING,
                        "projection_superseded",
                    )
                if plan != canonical:
                    return self._finish(
                        event_id,
                        ProjectionStatus.SYNC_PENDING,
                        "projection_identity_mismatch",
                    )
                return self._apply_locked(
                    plan, event_id, current_event.input_hash
                )
        except ProjectionLockBusy:
            return self._finish(
                event_id, ProjectionStatus.SYNC_PENDING, "sync_lock_busy"
            )

    def _canonical_automatic_plan(
        self, event: ProjectionEvent
    ) -> SyncPlan | None:
        """Rebuild the only plan accepted by the automatic projection path."""

        try:
            knowledge = self.repository.list_project_knowledge(event.project_id)
            if projection_input_hash(knowledge) != event.input_hash:
                return None
            return ObsidianProjection(self.vault_root, self.backup_root).plan(
                event.project_id,
                knowledge,
                event_id=event.id,
                input_hash=event.input_hash,
            )
        except (
            BoundaryError,
            OSError,
            RuntimeError,
            ValueError,
            VaultNotConfiguredError,
        ):
            return None

    def synchronize(
        self, event_id: str, projection: ObsidianProjection
    ) -> ProjectionResult:
        event = self.repository.get_projection_event(event_id)
        if event is None:
            raise KeyError(f"projection event not found: {event_id}")
        try:
            with self._project_lock(event.project_id):
                event = self.repository.get_projection_event(event_id)
                knowledge = self.repository.list_project_knowledge(event.project_id)
                if projection_input_hash(knowledge) != event.input_hash:
                    return self._finish(
                        event_id,
                        ProjectionStatus.SYNC_PENDING,
                        "projection_superseded",
                    )
                try:
                    plan = projection.plan(
                        event.project_id,
                        knowledge,
                        event_id=event.id,
                        input_hash=event.input_hash,
                    )
                except VaultNotConfiguredError:
                    return self._finish(
                        event_id,
                        ProjectionStatus.SYNC_PENDING,
                        "vault_not_configured",
                    )
                except (BoundaryError, OSError, RuntimeError, ValueError):
                    return self._finish(
                        event_id, ProjectionStatus.SYNC_PENDING, "planning_failed"
                    )
                return self._apply_locked(plan, event_id, event.input_hash)
        except ProjectionLockBusy:
            return self._finish(
                event_id, ProjectionStatus.SYNC_PENDING, "sync_lock_busy"
            )

    def _apply_locked(
        self, plan: SyncPlan, event_id: str, expected_input_hash: str
    ) -> ProjectionResult:
        if self.repository.has_rollback_required_sync():
            return self._finish(
                event_id,
                ProjectionStatus.ROLLBACK_REQUIRED,
                "rollback_blocked",
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
        try:
            self.repository.begin_sync(job)
        except sqlite3.Error as exc:
            try:
                return self._finish(
                    event_id,
                    ProjectionStatus.SYNC_PENDING,
                    "journal_start_failed",
                )
            except ProjectionPersistenceError:
                raise ProjectionPersistenceError("journal_start_failed") from exc
        try:
            for write in plan.writes:
                try:
                    current = self.repository.projection_fence_matches(
                        event_id, expected_input_hash
                    )
                except sqlite3.Error as exc:
                    raise ProjectionFenceError("projection_fence_failed") from exc
                if not current:
                    raise ProjectionFenceError("projection_superseded")
                self._atomic_replace(write.target, write.after_bytes)
                if write.target.read_bytes() != write.after_bytes:
                    raise OSError(f"post-write readback mismatch: {write.target}")
        except ProjectionFenceError as exc:
            rollback_error = self._restore(plan, snapshots)
            status = (
                ProjectionStatus.ROLLBACK_REQUIRED
                if rollback_error
                else ProjectionStatus.SYNC_PENDING
            )
            error = "rollback_failed" if rollback_error else exc.reason
            return self._finish_after_rollback(event_id, status, error)
        except (OSError, RuntimeError):
            rollback_error = self._restore(plan, snapshots)
            status = (
                ProjectionStatus.ROLLBACK_REQUIRED
                if rollback_error
                else ProjectionStatus.SYNC_PENDING
            )
            error = "write_failed" if not rollback_error else "rollback_failed"
            return self._finish_after_rollback(event_id, status, error)

        states = [
            (
                write.target,
                write.after_managed_hash or sha256_bytes(write.after_bytes),
                sha256_bytes(write.after_bytes),
            )
            for write in plan.writes
        ]
        try:
            self.repository.complete_sync(
                event_id, plan.project_id, states, expected_input_hash
            )
        except ProjectionFenceError as exc:
            rollback_error = self._restore(plan, snapshots)
            status = (
                ProjectionStatus.ROLLBACK_REQUIRED
                if rollback_error
                else ProjectionStatus.SYNC_PENDING
            )
            error = "rollback_failed" if rollback_error else exc.reason
            return self._finish_after_rollback(event_id, status, error)
        except sqlite3.Error:
            rollback_error = self._restore(plan, snapshots)
            status = (
                ProjectionStatus.ROLLBACK_REQUIRED
                if rollback_error
                else ProjectionStatus.SYNC_PENDING
            )
            error = "rollback_failed" if rollback_error else "journal_update_failed"
            return self._finish_after_rollback(event_id, status, error)
        except (OSError, RuntimeError, ValueError):
            rollback_error = self._restore(plan, snapshots)
            status = (
                ProjectionStatus.ROLLBACK_REQUIRED
                if rollback_error
                else ProjectionStatus.SYNC_PENDING
            )
            error = "rollback_failed" if rollback_error else "journal_finalize_failed"
            return self._finish_after_rollback(event_id, status, error)
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
        if self.vault_root is None:
            raise ValueError("vault is disabled")
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
        if self.vault_root is None:
            raise ValueError("vault is disabled")
        return backup_dir / target.relative_to(self.vault_root)

    @staticmethod
    def _plan_json(plan: SyncPlan) -> str:
        return json.dumps(
            {
                "id": plan.id,
                "project_id": plan.project_id,
                "event_id": plan.event_id,
                "input_hash": plan.input_hash,
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
        try:
            self.repository.finish_projection_event(event_id, status, error)
        except sqlite3.Error as exc:
            raise ProjectionPersistenceError(error or "journal_update_failed") from exc
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
        return ProjectionResult(event_id, status, warning, command, error)

    def _finish_after_rollback(
        self, event_id: str, status: ProjectionStatus, reason: str
    ) -> ProjectionResult:
        try:
            self.repository.finish_sync(event_id, status.value, reason)
        except sqlite3.Error:
            reason = "journal_update_failed"
        return self._finish(event_id, status, reason)

    @contextmanager
    def _project_lock(self, project_id: str):
        """Combine a thread lock with an OS-released file-region lock."""

        key = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        deadline = time.monotonic() + 5.0
        with _THREAD_LOCKS_GUARD:
            thread_lock = _THREAD_LOCKS.setdefault(key, threading.Lock())
        if not thread_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise ProjectionLockBusy("thread lock timeout")
        handle = None
        locked = False
        try:
            lock_root = self.backup_root.parent / ".projection-locks"
            if lock_root.is_symlink() or self.backup_root.parent.is_symlink():
                raise ProjectionLockBusy("unsafe lock root")
            try:
                lock_root.mkdir(parents=True, exist_ok=True)
                lock_path = lock_root / f"{key}.lock"
                handle = lock_path.open("a+b")
            except OSError as exc:
                raise ProjectionLockBusy("lock file unavailable") from exc
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            while not locked:
                try:
                    _lock_file(handle)
                    locked = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ProjectionLockBusy("file lock timeout")
                    time.sleep(0.02)
            yield
        finally:
            if locked and handle is not None:
                try:
                    _unlock_file(handle)
                except OSError:
                    pass
            if handle is not None:
                handle.close()
            thread_lock.release()


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
        try:
            event_id = self.repository.save_current_projection_event(
                project_id, cause, entity_id
            )
        except sqlite3.Error as exc:
            raise ProjectionPersistenceError("projection_event_failed") from exc
        existing = self.repository.get_projection_event(event_id)
        if existing is not None and existing.status is ProjectionStatus.SYNCED:
            return ProjectionResult(event_id, ProjectionStatus.SYNCED)
        return self.sync.synchronize(event_id, self.projection)

    def retry(self, event_id: str) -> ProjectionResult:
        event = self.repository.get_projection_event(event_id)
        if event is None:
            raise KeyError(f"projection event not found: {event_id}")
        if event.status is ProjectionStatus.ROLLBACK_REQUIRED:
            return ProjectionResult(
                event_id=event.id,
                status=event.status,
                warning="RETRO_ROLLBACK_REQUIRED",
                recovery_command="retro doctor --repair-sync",
                reason=event.error or "rollback_failed",
            )
        return self.sync.synchronize(event.id, self.projection)


def _lock_file(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
