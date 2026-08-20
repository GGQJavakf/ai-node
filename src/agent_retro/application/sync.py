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
from typing import Any, Callable, cast

from agent_retro.application._sync_operations import (
    apply_confirmed_merge_writes,
    apply_projection_writes,
    backup_projection_snapshots,
    managed_file_updates,
    merge_expected_inputs,
    projection_plan_json,
    rollback_outcome,
    validate_confirmed_operations,
)
from agent_retro.application.ports import RetroRepository
from agent_retro.application.purge import require_no_active_purge
from agent_retro.domain.models import (
    ProjectionEvent,
    ProjectionStatus,
    SyncJob,
)
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


@dataclass(frozen=True)
class _MergeSnapshot:
    exists: bool
    kind: str
    content: bytes


class ProjectionLockBusy(RuntimeError):
    """A project projection is already active in another thread/process."""


class ProjectionPersistenceError(RuntimeError):
    """A sanitized synchronization-state persistence failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.recovery_command = "retro doctor --repair-sync"


class ExternalEditConflict(ValueError):
    """A managed target differs from its last published managed hash."""


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
        require_no_active_purge(self.repository, project_id=event.project_id)
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
                return self._apply_locked(plan, event_id, current_event.input_hash)
        except ProjectionLockBusy:
            return self._finish(
                event_id, ProjectionStatus.SYNC_PENDING, "sync_lock_busy"
            )

    def _canonical_automatic_plan(self, event: ProjectionEvent) -> SyncPlan | None:
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
        require_no_active_purge(self.repository, project_id=event.project_id)
        try:
            with self._project_lock(event.project_id):
                event = cast(
                    ProjectionEvent, self.repository.get_projection_event(event_id)
                )
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

    def apply_confirmed_merge(
        self,
        plan_id: str,
        *,
        confirmed_operations: tuple[str, ...] = (),
        actor: str = "user",
    ) -> ProjectionResult:
        """Apply a separately confirmed deep-merge plan through the journal.

        This deliberately does not call or relax ``apply``: automatic projection
        accepts only its freshly rebuilt canonical plan, while this entry point
        independently revalidates every confirmed merge input under the same
        project lock.
        """

        if actor != "user":
            raise ValueError("merge_actor_must_be_user")
        _, initial_plan = self._load_confirmed_merge_plan(plan_id)
        require_no_active_purge(self.repository, project_id=initial_plan.project_id)
        try:
            with self._project_lock(initial_plan.project_id):
                job, plan = self._load_confirmed_merge_plan(plan_id)
                if plan.project_id != initial_plan.project_id:
                    raise ValueError("merge_plan_changed")
                from agent_retro.application.merge import required_merge_operation_ids

                validate_confirmed_operations(
                    required_merge_operation_ids(plan), confirmed_operations
                )
                return self._apply_confirmed_merge_locked(job, plan)
        except ProjectionLockBusy:
            return self._finish_merge(
                plan_id, ProjectionStatus.SYNC_PENDING, "sync_lock_busy"
            )

    def _load_confirmed_merge_plan(self, plan_id: str) -> tuple[SyncJob, Any]:
        from agent_retro.application.merge import load_persisted_merge_plan

        try:
            job = self.repository.get_sync_job(plan_id)
        except sqlite3.Error as exc:
            raise ProjectionPersistenceError("merge_state_unavailable") from exc
        if job is None:
            raise ProjectionPersistenceError("merge_plan_not_found")
        try:
            plan = load_persisted_merge_plan(job, plan_id)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("merge_plan_invalid") from exc
        return job, plan

    def _apply_confirmed_merge_locked(
        self, job: SyncJob, plan: Any
    ) -> ProjectionResult:
        if job.status == ProjectionStatus.SYNCED.value:
            return ProjectionResult(
                plan.id, ProjectionStatus.SYNCED, reason="already_applied"
            )
        if self.repository.has_rollback_required_sync():
            return self._finish_merge(
                plan.id, ProjectionStatus.ROLLBACK_REQUIRED, "rollback_blocked"
            )
        try:
            snapshots = self._preflight_merge(plan)
        except (BoundaryError, OSError, RuntimeError, ValueError):
            raise ValueError("merge_plan_stale")
        backup_dir = self.backup_root / plan.id
        try:
            self._backup_snapshots(backup_dir, snapshots)
            self._assert_merge_inputs(plan)
            self.repository.begin_sync(
                SyncJob(
                    id=plan.id,
                    project_id=plan.project_id,
                    status=ProjectionStatus.SYNC_PENDING.value,
                    plan_json=job.plan_json,
                    backup_path=backup_dir,
                )
            )
        except sqlite3.Error as exc:
            raise ProjectionPersistenceError("journal_start_failed") from exc
        except ValueError as exc:
            raise ValueError("merge_plan_stale") from exc
        except OSError:
            return self._finish_merge(
                plan.id, ProjectionStatus.SYNC_PENDING, "backup_failed"
            )
        return self._write_confirmed_merge(plan, snapshots)

    def _write_confirmed_merge(
        self, plan: Any, snapshots: dict[Path, _MergeSnapshot]
    ) -> ProjectionResult:
        if self.vault_root is None:
            raise ValueError("vault is disabled")
        changed_paths: set[Path] = set()
        try:
            self._assert_merge_inputs(plan)
            apply_confirmed_merge_writes(
                plan,
                self.vault_root,
                changed_paths,
                assert_inputs=self._assert_merge_inputs,
                atomic_replace=self._atomic_replace,
                replace=self.replace,
            )
            self.repository.finish_sync(plan.id, ProjectionStatus.SYNCED.value)
        except sqlite3.Error:
            return self._finish_merge_after_rollback(
                plan.id, snapshots, changed_paths, "journal_update_failed"
            )
        except ValueError:
            return self._finish_merge_after_rollback(
                plan.id, snapshots, changed_paths, "merge_plan_stale"
            )
        except (OSError, RuntimeError):
            return self._finish_merge_after_rollback(
                plan.id, snapshots, changed_paths, "write_failed"
            )
        return ProjectionResult(plan.id, ProjectionStatus.SYNCED)

    def _finish_merge_after_rollback(
        self,
        plan_id: str,
        snapshots: dict[Path, _MergeSnapshot],
        changed_paths: set[Path],
        failure_reason: str,
    ) -> ProjectionResult:
        status, reason = rollback_outcome(
            self._restore_snapshots(snapshots, changed_paths), failure_reason
        )
        return self._finish_merge(plan_id, status, reason)

    def _preflight_merge(
        self, plan, *, exclude: set[Path] | None = None
    ) -> dict[Path, _MergeSnapshot]:
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
            raise ValueError("project mapping changed")
        if (
            projection_input_hash(
                self.repository.list_project_knowledge(plan.project_id)
            )
            != plan.authority_hash
        ):
            raise ValueError("authoritative knowledge changed after planning")
        self._validate_backup_dir(self.backup_root / plan.id)
        snapshots: dict[Path, _MergeSnapshot] = {}
        excluded = exclude or set()
        for target, expected_exists, expected_kind, expected_hash in merge_expected_inputs(
            plan, self.vault_root
        ):
            if target in excluded:
                continue
            self._validate_merge_target(target)
            snapshot = self._merge_snapshot(target)
            if (
                snapshot.exists != expected_exists
                or snapshot.kind != expected_kind
                or sha256_bytes(snapshot.content) != expected_hash
            ):
                raise ValueError("merge target changed after planning")
            snapshots[target] = snapshot
        return snapshots

    def _assert_merge_inputs(self, plan, *, exclude: set[Path] | None = None) -> None:
        self._preflight_merge(plan, exclude=exclude)

    @staticmethod
    def _merge_snapshot(target: Path) -> _MergeSnapshot:
        if not target.exists():
            return _MergeSnapshot(False, "missing", b"")
        if not target.is_file():
            kind = "directory" if target.is_dir() else "other"
            return _MergeSnapshot(True, kind, b"")
        return _MergeSnapshot(True, "file", target.read_bytes())

    def _validate_merge_target(self, target: Path) -> None:
        if self.vault_root is None:
            raise ValueError("vault is disabled")
        root = self.vault_root.resolve(strict=True)
        try:
            relative = target.relative_to(self.vault_root)
            target.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise UnsafeVaultPathError("merge target escapes vault") from exc
        current = self.vault_root
        for part in relative.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise UnsafeVaultPathError("merge target contains a symlink")

    def _backup_snapshots(
        self, backup_dir: Path, snapshots: dict[Path, _MergeSnapshot]
    ) -> None:
        self._validate_backup_dir(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        for target, snapshot in snapshots.items():
            if not snapshot.exists or snapshot.kind != "file":
                continue
            before = snapshot.content
            backup = self._backup_path(backup_dir, target)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(before)
            if backup.read_bytes() != before:
                raise OSError("merge backup readback failed")

    def _restore_snapshots(
        self, snapshots: dict[Path, _MergeSnapshot], changed_paths: set[Path]
    ) -> str:
        errors = []
        for target in changed_paths:
            snapshot = snapshots[target]
            try:
                if not snapshot.exists:
                    target.unlink(missing_ok=True)
                elif snapshot.kind == "file":
                    self._atomic_replace(target, snapshot.content)
                else:
                    raise OSError("unsupported merge rollback kind")
                restored = self._merge_snapshot(target)
                if (
                    restored.exists != snapshot.exists
                    or restored.kind != snapshot.kind
                    or sha256_bytes(restored.content) != sha256_bytes(snapshot.content)
                ):
                    raise OSError("merge rollback readback failed")
            except OSError:
                errors.append("rollback_failed")
        return ";".join(errors)

    def _finish_merge(
        self, plan_id: str, status: ProjectionStatus, reason: str
    ) -> ProjectionResult:
        try:
            self.repository.finish_sync(plan_id, status.value, reason)
        except sqlite3.Error as exc:
            raise ProjectionPersistenceError("journal_update_failed") from exc
        warning = (
            "RETRO_ROLLBACK_REQUIRED"
            if status is ProjectionStatus.ROLLBACK_REQUIRED
            else "RETRO_SYNC_PENDING"
        )
        command = (
            "retro doctor --repair-sync"
            if status is ProjectionStatus.ROLLBACK_REQUIRED
            else f"retro merge apply {plan_id}"
        )
        return ProjectionResult(plan_id, status, warning, command, reason)

    def _apply_locked(
        self, plan: SyncPlan, event_id: str, expected_input_hash: str
    ) -> ProjectionResult:
        if self.repository.has_rollback_required_sync():
            return self._finish(
                event_id,
                ProjectionStatus.ROLLBACK_REQUIRED,
                "rollback_blocked",
            )
        prepared = self._prepare_projection(plan, event_id)
        if isinstance(prepared, ProjectionResult):
            return prepared
        snapshots = prepared
        result = self._start_projection_journal(plan, event_id)
        if result is not None:
            return result
        result = self._write_projection(plan, event_id, expected_input_hash, snapshots)
        if result is not None:
            return result
        return self._complete_projection(
            plan, event_id, expected_input_hash, snapshots
        )

    def _prepare_projection(
        self, plan: SyncPlan, event_id: str
    ) -> dict[Path, bytes | None] | ProjectionResult:
        try:
            snapshots = self._preflight(plan)
        except ExternalEditConflict:
            return self._finish(
                event_id,
                ProjectionStatus.SYNC_PENDING,
                "external_edit_conflict",
            )
        except (BoundaryError, OSError, RuntimeError, ValueError):
            return self._finish(
                event_id, ProjectionStatus.SYNC_PENDING, "preflight_failed"
            )
        backup_dir = plan.backup_dir
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_projection_snapshots(
                snapshots, lambda target: self._backup_path(backup_dir, target)
            )
        except OSError:
            return self._finish(
                event_id, ProjectionStatus.SYNC_PENDING, "backup_failed"
            )
        return snapshots

    def _start_projection_journal(
        self, plan: SyncPlan, event_id: str
    ) -> ProjectionResult | None:
        job = SyncJob(
            id=event_id,
            project_id=plan.project_id,
            status=ProjectionStatus.SYNC_PENDING.value,
            plan_json=self._plan_json(plan),
            backup_path=plan.backup_dir,
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
        return None

    def _write_projection(
        self,
        plan: SyncPlan,
        event_id: str,
        expected_input_hash: str,
        snapshots: dict[Path, bytes | None],
    ) -> ProjectionResult | None:
        try:
            apply_projection_writes(
                plan,
                event_id,
                expected_input_hash,
                fence_matches=self.repository.projection_fence_matches,
                atomic_replace=self._atomic_replace,
            )
        except ProjectionFenceError as exc:
            return self._rollback_projection(plan, event_id, snapshots, exc.reason)
        except (OSError, RuntimeError):
            return self._rollback_projection(
                plan, event_id, snapshots, "write_failed"
            )
        return None

    def _complete_projection(
        self,
        plan: SyncPlan,
        event_id: str,
        expected_input_hash: str,
        snapshots: dict[Path, bytes | None],
    ) -> ProjectionResult:
        try:
            self.repository.complete_sync(
                event_id,
                plan.project_id,
                managed_file_updates(plan, event_id),
                expected_input_hash,
            )
        except ProjectionFenceError as exc:
            return self._rollback_projection(plan, event_id, snapshots, exc.reason)
        except sqlite3.Error:
            return self._rollback_projection(
                plan, event_id, snapshots, "journal_update_failed"
            )
        except (OSError, RuntimeError, ValueError):
            return self._rollback_projection(
                plan, event_id, snapshots, "journal_finalize_failed"
            )
        return ProjectionResult(event_id, ProjectionStatus.SYNCED)

    def _rollback_projection(
        self,
        plan: SyncPlan,
        event_id: str,
        snapshots: dict[Path, bytes | None],
        failure_reason: str,
    ) -> ProjectionResult:
        status, reason = rollback_outcome(
            self._restore(plan, snapshots), failure_reason
        )
        return self._finish_after_rollback(event_id, status, reason)

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
            target.resolve(strict=True).relative_to(
                self.backup_root.resolve(strict=True)
            )
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
                current_managed = self._current_managed_hash(
                    write.target, before or b""
                )
                if state.managed_hash != current_managed:
                    raise ExternalEditConflict("managed content changed externally")
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

    def _restore(self, plan: SyncPlan, snapshots: dict[Path, bytes | None]) -> str:
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
        return projection_plan_json(plan)

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
    def project_lock(self, project_id: str):
        """Expose the shared project lock to other bounded vault writers."""

        with self._project_lock(project_id):
            yield

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
        require_no_active_purge(self.repository, project_id=project_id)
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
        require_no_active_purge(self.repository, project_id=event.project_id)
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

        getattr(fcntl, "flock")(
            handle.fileno(), getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB")
        )


def _unlock_file(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        getattr(fcntl, "flock")(handle.fileno(), getattr(fcntl, "LOCK_UN"))
