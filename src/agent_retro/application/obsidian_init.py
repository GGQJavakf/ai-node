"""Previewed initialization for optional Obsidian managed boundaries."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Callable

from agent_retro.application.ports import RetroRepository
from agent_retro.application.sync import ProjectionLockBusy, SyncService
from agent_retro.domain.models import ProjectionStatus, SyncJob
from agent_retro.infrastructure.obsidian import (
    BoundaryError,
    ManagedBoundaryKind,
    initialize_managed_boundary,
    inspect_managed_boundary,
    sha256_bytes,
)


class BoundaryInitError(RuntimeError):
    """A redaction-safe managed-boundary initialization failure."""

    def __init__(self, reason: str, recovery_command: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.recovery_command = recovery_command


class BoundaryInitStalePlan(BoundaryInitError):
    def __init__(self) -> None:
        super().__init__("stale_plan", "retro sync init --project <project>")


@dataclass(frozen=True)
class BoundaryInitTarget:
    relative_path: Path
    kind: ManagedBoundaryKind
    before_hash: str
    after_hash: str
    diff: str
    backup_path: Path
    changed: bool
    _target: Path = field(repr=False)
    _before: bytes = field(repr=False)
    _after: bytes = field(repr=False)


@dataclass(frozen=True)
class BoundaryInitPlan:
    id: str
    project_id: str
    targets: tuple[BoundaryInitTarget, ...]
    backup_dir: Path

    @property
    def changed(self) -> bool:
        return any(target.changed for target in self.targets)


@dataclass(frozen=True)
class BoundaryInitResult:
    plan: BoundaryInitPlan
    status: ProjectionStatus
    changed: bool
    reason: str = ""
    recovery_command: str = ""


class ManagedBoundaryInitializer:
    """Plan and apply exact marker additions to existing optional vault pages."""

    def __init__(
        self,
        repository: RetroRepository,
        vault_root: Path | None,
        backup_root: Path,
        *,
        replace: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        self.repository = repository
        self.vault_root = None if vault_root is None else Path(vault_root).absolute()
        self.backup_root = Path(backup_root).absolute()
        self.replace = replace
        self._lock_service = SyncService(repository, self.vault_root, self.backup_root)

    def preview(self, project_id: str) -> BoundaryInitPlan:
        vault = self._validate_context(project_id)
        project_path = Path(project_id)
        planned: list[tuple[Path, ManagedBoundaryKind, bytes, bytes, str]] = []
        candidates: tuple[tuple[Path, ManagedBoundaryKind], ...] = (
            (
                Path("项目")
                / project_path
                / f"项目_{project_path.name}.md",
                "summary",
            ),
            (Path("项目") / "项目索引.md", "index"),
        )
        for relative, kind in candidates:
            target = self._safe_target(vault, relative)
            if target.is_symlink():
                raise BoundaryInitError("unsafe_target")
            if not target.exists():
                continue
            if not target.is_file():
                raise BoundaryInitError("target_not_regular_file")
            before = target.read_bytes()
            try:
                after = initialize_managed_boundary(before, project_id, kind)
            except BoundaryError as exc:
                raise BoundaryInitError("invalid_managed_boundary") from exc
            planned.append(
                (relative, kind, before, after, self._diff(relative, before, after))
            )

        identity = json.dumps(
            [
                project_id,
                [
                    [
                        relative.as_posix(),
                        kind,
                        sha256_bytes(before),
                        sha256_bytes(after),
                    ]
                    for relative, kind, before, after, _ in planned
                ],
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        plan_id = "obsidian-init-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        backup_dir = self.backup_root / plan_id
        targets = tuple(
            BoundaryInitTarget(
                relative_path=relative,
                kind=kind,
                before_hash=sha256_bytes(before),
                after_hash=sha256_bytes(after),
                diff=diff,
                backup_path=backup_dir / relative,
                changed=before != after,
                _target=vault / relative,
                _before=before,
                _after=after,
            )
            for relative, kind, before, after, diff in planned
        )
        return BoundaryInitPlan(plan_id, project_id, targets, backup_dir)

    def apply(self, project_id: str, confirmed_plan_id: str) -> BoundaryInitResult:
        self._validate_project_id(project_id)
        try:
            with self._lock_service.project_lock(project_id):
                plan = self.preview(project_id)
                if plan.id != confirmed_plan_id:
                    raise BoundaryInitStalePlan()
                if not plan.changed:
                    return BoundaryInitResult(plan, ProjectionStatus.SYNCED, False)
                if self.repository.has_rollback_required_sync():
                    raise BoundaryInitError(
                        "rollback_blocked", "retro doctor --repair-sync"
                    )
                self._assert_inputs(plan, set())
                self._create_backups(plan)
                try:
                    self.repository.begin_sync(
                        SyncJob(
                            id=plan.id,
                            project_id=project_id,
                            status=ProjectionStatus.SYNC_PENDING.value,
                            plan_json=self._plan_json(plan),
                            backup_path=plan.backup_dir,
                        )
                    )
                except sqlite3.Error as exc:
                    raise BoundaryInitError("journal_start_failed") from exc
                return self._apply_planned(plan)
        except ProjectionLockBusy as exc:
            raise BoundaryInitError("sync_lock_busy") from exc

    def _apply_planned(self, plan: BoundaryInitPlan) -> BoundaryInitResult:
        changed_paths: set[Path] = set()
        try:
            for target in plan.targets:
                if not target.changed:
                    continue
                self._assert_inputs(plan, changed_paths)
                changed_paths.add(target._target)
                self._atomic_replace(target._target, target._after)
                actual = target._target.read_bytes()
                if actual != target._after:
                    raise OSError("target_readback_failed")
                if not inspect_managed_boundary(actual, plan.project_id, target.kind):
                    raise OSError("managed_boundary_readback_failed")
            self._assert_inputs(plan, changed_paths)
            self.repository.finish_sync(plan.id, ProjectionStatus.SYNCED.value)
        except (BoundaryError, OSError, RuntimeError, ValueError, sqlite3.Error):
            rollback_failed = self._restore(plan, changed_paths)
            status = (
                ProjectionStatus.ROLLBACK_REQUIRED
                if rollback_failed
                else ProjectionStatus.SYNC_PENDING
            )
            reason = "rollback_failed" if rollback_failed else "write_failed"
            try:
                self.repository.finish_sync(plan.id, status.value, reason)
            except sqlite3.Error as exc:
                raise BoundaryInitError(
                    "journal_update_failed", "retro doctor --repair-sync"
                ) from exc
            command = (
                "retro doctor --repair-sync"
                if rollback_failed
                else f"retro sync init --project {plan.project_id}"
            )
            return BoundaryInitResult(plan, status, False, reason, command)
        return BoundaryInitResult(plan, ProjectionStatus.SYNCED, True)

    def _validate_context(self, project_id: str) -> Path:
        self._validate_project_id(project_id)
        if self.vault_root is None:
            raise BoundaryInitError("vault_not_configured")
        if self._has_symlink_component(self.vault_root):
            raise BoundaryInitError("unsafe_vault_root")
        if not self.vault_root.exists() or not self.vault_root.is_dir():
            raise BoundaryInitError("vault_unavailable")
        if self._has_symlink_component(self.backup_root):
            raise BoundaryInitError("unsafe_backup_root")
        mappings = [
            mapping
            for mapping in self.repository.list_project_mappings()
            if mapping.obsidian_project == project_id
        ]
        if len(mappings) != 1:
            raise BoundaryInitError("project_mapping_unavailable")
        return self.vault_root.resolve(strict=True)

    @staticmethod
    def _validate_project_id(project_id: str) -> None:
        candidate = Path(project_id)
        windows_candidate = PureWindowsPath(project_id)
        marker_unsafe = (
            "--" in project_id
            or "<" in project_id
            or ">" in project_id
            or any(ord(character) < 32 for character in project_id)
        )
        path_unsafe = (
            "\\" in project_id
            or any(character in ':"|?*' for character in project_id)
            or candidate.as_posix() != project_id
            or any(part in {"", ".", ".."} for part in candidate.parts)
        )
        if (
            not project_id
            or marker_unsafe
            or path_unsafe
            or candidate.is_absolute()
            or windows_candidate.is_absolute()
            or bool(windows_candidate.drive)
            or bool(windows_candidate.root)
        ):
            raise BoundaryInitError("invalid_project_id")

    @staticmethod
    def _safe_target(vault: Path, relative: Path) -> Path:
        target = vault / relative
        current = vault
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise BoundaryInitError("unsafe_target")
        try:
            target.resolve(strict=False).relative_to(vault)
        except ValueError as exc:
            raise BoundaryInitError("unsafe_target") from exc
        return target

    @staticmethod
    def _has_symlink_component(path: Path) -> bool:
        current = path.absolute()
        while True:
            if current.is_symlink():
                return True
            if current.parent == current:
                return False
            current = current.parent

    @staticmethod
    def _diff(relative: Path, before: bytes, after: bytes) -> str:
        if before == after:
            return ""
        current = before.decode("utf-8", errors="strict")
        planned = after.decode("utf-8", errors="strict")
        return "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                planned.splitlines(keepends=True),
                fromfile=f"{relative.as_posix()} (current)",
                tofile=f"{relative.as_posix()} (planned)",
                lineterm="\n",
            )
        )

    def _create_backups(self, plan: BoundaryInitPlan) -> None:
        if plan.backup_dir.is_symlink():
            raise BoundaryInitError("backup_conflict")
        if plan.backup_dir.exists():
            self._verify_existing_backups(plan)
            return
        temporary: Path | None = None
        try:
            self.backup_root.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{plan.id}.", dir=self.backup_root)
            )
            for target in plan.targets:
                backup = temporary / target.relative_path
                backup.parent.mkdir(parents=True, exist_ok=True)
                with backup.open("xb") as stream:
                    stream.write(target._before)
                    stream.flush()
                    os.fsync(stream.fileno())
                if backup.read_bytes() != target._before:
                    raise OSError("backup_readback_failed")
            os.replace(temporary, plan.backup_dir)
            temporary = None
        except OSError as exc:
            raise BoundaryInitError("backup_failed") from exc
        finally:
            if temporary is not None:
                shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _verify_existing_backups(plan: BoundaryInitPlan) -> None:
        if not plan.backup_dir.is_dir():
            raise BoundaryInitError("backup_conflict")
        expected = {target.backup_path for target in plan.targets}
        actual: set[Path] = set()
        for path in plan.backup_dir.rglob("*"):
            if path.is_symlink():
                raise BoundaryInitError("backup_conflict")
            if path.is_file():
                actual.add(path)
        if actual != expected:
            raise BoundaryInitError("backup_conflict")
        for target in plan.targets:
            if target.backup_path.read_bytes() != target._before:
                raise BoundaryInitError("backup_conflict")

    def _assert_inputs(self, plan: BoundaryInitPlan, changed_paths: set[Path]) -> None:
        vault = self._validate_context(plan.project_id)
        for target in plan.targets:
            current_target = self._safe_target(vault, target.relative_path)
            if (
                current_target != target._target
                or current_target.is_symlink()
                or not current_target.is_file()
            ):
                raise BoundaryInitStalePlan()
            actual = target._target.read_bytes()
            expected = (
                target._after if target._target in changed_paths else target._before
            )
            if actual != expected:
                raise BoundaryInitStalePlan()

    def _restore(self, plan: BoundaryInitPlan, changed_paths: set[Path]) -> bool:
        failed = False
        for target in plan.targets:
            if target._target not in changed_paths:
                continue
            try:
                self._atomic_replace(target._target, target._before)
                if target._target.read_bytes() != target._before:
                    raise OSError("rollback_readback_failed")
            except OSError:
                failed = True
        return failed

    def _atomic_replace(self, target: Path, content: bytes) -> None:
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

    @staticmethod
    def _plan_json(plan: BoundaryInitPlan) -> str:
        return json.dumps(
            {
                "id": plan.id,
                "kind": "obsidian_boundary_init",
                "project_id": plan.project_id,
                "targets": [
                    {
                        "path": target.relative_path.as_posix(),
                        "kind": target.kind,
                        "before_hash": target.before_hash,
                        "after_hash": target.after_hash,
                    }
                    for target in plan.targets
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
