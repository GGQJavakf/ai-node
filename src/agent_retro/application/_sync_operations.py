"""Projection synchronization mechanics used by :class:`SyncService`.

The public service retains lock, journal, and rollback ownership.  These helpers
make the deterministic validation, file-operation, and result-shaping steps
independently testable without introducing a second service facade.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from agent_retro.domain.models import ManagedFileUpdate, ProjectionStatus
from agent_retro.domain.projection import ProjectionFenceError
from agent_retro.infrastructure.obsidian import (
    SyncPlan,
    managed_block_bytes,
    sha256_bytes,
)


def validate_confirmed_operations(
    required: frozenset[str], confirmed: Iterable[str]
) -> None:
    """Require an exact destructive-operation confirmation set."""

    supplied = frozenset(confirmed)
    if required - supplied:
        raise ValueError("merge_operation_confirmation_required")
    if supplied - required:
        raise ValueError("unknown_merge_operation_confirmation")


def merge_expected_inputs(
    plan: Any, vault_root: Path
) -> tuple[tuple[Path, bool, str, str], ...]:
    """Expand a persisted merge plan into its authenticated filesystem inputs."""

    expected = [
        (
            vault_root / target.path,
            target.input_exists,
            target.input_kind,
            target.input_hash,
        )
        for target in plan.targets
    ]
    expected.extend(
        (
            vault_root / delete.path,
            delete.input_exists,
            delete.input_kind,
            delete.input_hash,
        )
        for delete in plan.deletes
    )
    for rename in plan.renames:
        expected.extend(
            (
                (
                    vault_root / rename.source,
                    rename.source_exists,
                    rename.source_kind,
                    rename.source_hash,
                ),
                (
                    vault_root / rename.target,
                    rename.target_exists,
                    rename.target_kind,
                    rename.target_hash,
                ),
            )
        )
    return tuple(expected)


def apply_confirmed_merge_writes(
    plan: Any,
    vault_root: Path,
    changed_paths: set[Path],
    *,
    assert_inputs: Callable[..., None],
    atomic_replace: Callable[[Path, bytes], None],
    replace: Callable[[Path, Path], None],
) -> None:
    """Apply authenticated merge writes while fencing every next operation."""

    for target in plan.targets:
        assert_inputs(plan, exclude=changed_paths)
        path = vault_root / target.path
        changed_paths.add(path)
        atomic_replace(path, target.output_bytes)
        if path.read_bytes() != target.output_bytes:
            raise OSError("merge_target_readback_failed")
    for delete in plan.deletes:
        assert_inputs(plan, exclude=changed_paths)
        path = vault_root / delete.path
        changed_paths.add(path)
        path.unlink()
        if path.exists():
            raise OSError("merge_delete_readback_failed")
    for rename in plan.renames:
        assert_inputs(plan, exclude=changed_paths)
        source = vault_root / rename.source
        target = vault_root / rename.target
        changed_paths.update((source, target))
        target.parent.mkdir(parents=True, exist_ok=True)
        replace(source, target)
        if source.exists() or not target.exists():
            raise OSError("merge_rename_readback_failed")
        if sha256_bytes(target.read_bytes()) != rename.source_hash:
            raise OSError("merge_rename_hash_failed")


def backup_projection_snapshots(
    snapshots: Mapping[Path, bytes | None],
    backup_path: Callable[[Path], Path],
) -> None:
    """Persist pre-write projection bytes using caller-owned safe paths."""

    for target, before in snapshots.items():
        if before is None:
            continue
        backup = backup_path(target)
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(before)


def apply_projection_writes(
    plan: SyncPlan,
    event_id: str,
    expected_input_hash: str,
    *,
    fence_matches: Callable[[str, str], bool],
    atomic_replace: Callable[[Path, bytes], None],
) -> None:
    """Fence, replace, and read back each automatic projection write."""

    for write in plan.writes:
        try:
            current = fence_matches(event_id, expected_input_hash)
        except sqlite3.Error as exc:
            raise ProjectionFenceError("projection_fence_failed") from exc
        if not current:
            raise ProjectionFenceError("projection_superseded")
        atomic_replace(write.target, write.after_bytes)
        if write.target.read_bytes() != write.after_bytes:
            raise OSError(f"post-write readback mismatch: {write.target}")


def managed_file_updates(
    plan: SyncPlan, event_id: str
) -> list[ManagedFileUpdate]:
    """Build the repository state written only after all file readbacks pass."""

    return [
        ManagedFileUpdate(
            path=write.target,
            managed_hash=write.after_managed_hash or sha256_bytes(write.after_bytes),
            full_hash=sha256_bytes(write.after_bytes),
            snapshot_kind=write.ownership_kind,
            owned_bytes=(
                managed_block_bytes(write.after_bytes)
                if write.ownership_kind == "managed_block"
                else write.after_bytes
            ),
            event_id=event_id,
        )
        for write in plan.writes
    ]


def rollback_outcome(
    rollback_error: str, failure_reason: str
) -> tuple[ProjectionStatus, str]:
    """Map compensation success/failure to the stable journal outcome."""

    if rollback_error:
        return ProjectionStatus.ROLLBACK_REQUIRED, "rollback_failed"
    return ProjectionStatus.SYNC_PENDING, failure_reason


def projection_plan_json(plan: SyncPlan) -> str:
    """Serialize the compatibility journal shape for an automatic plan."""

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
