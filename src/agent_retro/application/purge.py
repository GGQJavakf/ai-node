"""Explicit, read-only sensitive-purge impact planning."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import PurgeOperation, PurgePlan, PurgeStatus


class PurgeError(RuntimeError):
    """Base class for typed purge failures."""


class PurgeKnowledgeNotFound(PurgeError):
    """The requested knowledge identity does not exist."""


class KnowledgeAlreadyPurged(PurgeError):
    """The requested knowledge identity has a completed purge tombstone."""


class KnowledgeSyncPending(PurgeError):
    """A pending projection makes the current manifest unstable."""


class UnsafePurgeRegistration(PurgeError):
    """A registered path escapes or aliases an allowed local root."""


class IncompletePurgeConfirmation(PurgeError):
    """Apply requires exactly every operation ID and no other value."""


class StalePurgePlan(PurgeError):
    """The current registered manifest no longer matches the supplied plan."""


class UnknownPurgePlan(PurgeError):
    """The supplied plan identity is malformed or cannot be resolved."""


@dataclass(frozen=True)
class _ManifestCopy:
    location_kind: str
    locator: str
    content: bytes
    path: Path | None = None

    @property
    def expected_hash(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


class PurgeService:
    """Build deterministic purge plans without changing files or database rows."""

    def __init__(
        self,
        repository: RetroRepository,
        *,
        vault_root: Path | None = None,
        backup_roots: Mapping[str, Path] | None = None,
        log_paths: Sequence[Path] = (),
        trace_paths: Sequence[Path] = (),
        replace: Callable[[Path, Path], object] = os.replace,
    ) -> None:
        self.repository = repository
        self.vault_root = None if vault_root is None else Path(vault_root)
        self.backup_roots = {
            str(kind): Path(root) for kind, root in (backup_roots or {}).items()
        }
        self.log_paths = tuple(Path(path) for path in log_paths)
        self.trace_paths = tuple(Path(path) for path in trace_paths)
        self._replace = replace

    def plan(self, knowledge_id: str) -> PurgePlan:
        plan, _, _, _ = self._current_manifest(knowledge_id)
        return plan

    def apply(
        self,
        plan_id: str,
        confirmed_operation_ids: frozenset[str],
        actor: str = "user",
    ) -> PurgeStatus:
        knowledge_id = self._knowledge_id_from_plan(plan_id)
        try:
            current, copies, marker, project_id = self._current_manifest(knowledge_id)
        except (
            PurgeKnowledgeNotFound,
            KnowledgeAlreadyPurged,
            KnowledgeSyncPending,
        ) as exc:
            raise StalePurgePlan("purge plan no longer matches current state") from exc
        if current.id != plan_id:
            raise StalePurgePlan("purge plan no longer matches current state")
        expected = frozenset(operation.id for operation in current.operations)
        if confirmed_operation_ids != expected:
            raise IncompletePurgeConfirmation(
                "every purge operation must be confirmed exactly"
            )

        now = datetime.now(timezone.utc).isoformat()
        tombstone = json.dumps(
            {
                "knowledge_id": knowledge_id,
                "actor": actor,
                "started_at": now,
                "updated_at": now,
                "status": PurgeStatus.PURGE_IN_PROGRESS.value,
                "operation_count": len(current.operations),
                "residual_count": 0,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        journal_locations = {
            operation.id: copy.locator
            for operation, copy in zip(current.operations, copies, strict=True)
        }
        database_expected = {
            copy.locator: copy.expected_hash
            for copy in copies
            if copy.location_kind.startswith("sqlite_")
        }
        self.repository.begin_purge(
            current,
            plan_hash=hashlib.sha256(current.id.encode("utf-8")).hexdigest(),
            actor=actor,
            marker=marker,
            journal_locations=journal_locations,
            database_expected_hashes=database_expected,
            tombstone_json=tombstone,
        )
        failed_kinds: list[str] = []
        for operation, copy in zip(current.operations, copies, strict=True):
            if copy.path is None:
                continue
            try:
                self._clean_registered_file(copy, operation.expected_hash, marker)
            except (OSError, ValueError):
                failed_kinds.append(copy.location_kind)
                self.repository.mark_purge_operation(
                    operation.id, "failed", "cleanup_failed"
                )
            else:
                self.repository.mark_purge_operation(operation.id, "completed")

        return self._finish_file_stage(
            current,
            copies,
            marker,
            project_id,
            tombstone,
            actor,
            failed_kinds,
        )

    def _current_manifest(
        self, knowledge_id: str
    ) -> tuple[PurgePlan, tuple[_ManifestCopy, ...], bytes, str]:
        inspection = self.repository.inspect_purge_database(knowledge_id)
        if inspection.already_purged:
            raise KnowledgeAlreadyPurged("knowledge is already purged")
        if inspection.knowledge is None:
            raise PurgeKnowledgeNotFound("knowledge was not found")
        if inspection.sync_pending:
            raise KnowledgeSyncPending("knowledge projection is sync_pending")

        marker = inspection.knowledge.text.encode("utf-8")
        copies = [
            _ManifestCopy(item.location_kind, item.locator, item.content)
            for item in inspection.copies
            if marker in item.content
        ]
        copies.extend(
            self._managed_vault_copies(inspection.knowledge.project_id, marker)
        )
        copies.extend(self._registered_file_copies(marker))
        copies.sort(key=lambda item: (item.location_kind, item.locator))

        normalized_manifest = [
            [item.location_kind, item.locator, item.expected_hash] for item in copies
        ]
        identity = json.dumps(
            [knowledge_id, normalized_manifest],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        encoded_knowledge = (
            urlsafe_b64encode(knowledge_id.encode("utf-8")).decode("ascii").rstrip("=")
        )
        plan_id = (
            "purge-v1-" + encoded_knowledge + "-" + hashlib.sha256(identity).hexdigest()
        )

        counts: dict[str, int] = {}
        operations: list[PurgeOperation] = []
        for item in copies:
            ordinal = counts.get(item.location_kind, 0) + 1
            counts[item.location_kind] = ordinal
            location = f"{item.location_kind}:{ordinal}"
            operation_id = hashlib.sha256(
                (plan_id + item.location_kind + location + item.expected_hash).encode(
                    "utf-8"
                )
            ).hexdigest()
            operations.append(
                PurgeOperation(
                    id=operation_id,
                    location_kind=item.location_kind,
                    location=location,
                    expected_hash=item.expected_hash,
                )
            )
        return (
            PurgePlan(
                id=plan_id,
                knowledge_id=knowledge_id,
                operations=tuple(operations),
                status=PurgeStatus.PLANNED,
            ),
            tuple(copies),
            marker,
            inspection.knowledge.project_id,
        )

    def _finish_file_stage(
        self,
        plan: PurgePlan,
        planned_copies: tuple[_ManifestCopy, ...],
        marker: bytes,
        project_id: str,
        tombstone_json: str,
        actor: str,
        failed_kinds: list[str],
    ) -> PurgeStatus:
        residual_copies: list[_ManifestCopy] = []
        residual_kinds = list(failed_kinds)
        try:
            residual_kinds.extend(self.repository.purge_database_residual_kinds(marker))
            residual_copies.extend(self._managed_vault_copies(project_id, marker))
            residual_copies.extend(self._registered_file_copies(marker))
        except (OSError, ValueError):
            residual_kinds.append("verification")

        residual_kinds.extend(copy.location_kind for copy in residual_copies)
        if residual_kinds:
            existing = {(copy.location_kind, copy.locator) for copy in planned_copies}
            kind_ordinals: dict[str, int] = {}
            for operation in plan.operations:
                kind_ordinals[operation.location_kind] = (
                    kind_ordinals.get(operation.location_kind, 0) + 1
                )
            additions: list[tuple[PurgeOperation, str]] = []
            for copy in sorted(
                residual_copies, key=lambda item: (item.location_kind, item.locator)
            ):
                if (copy.location_kind, copy.locator) in existing:
                    continue
                ordinal = kind_ordinals.get(copy.location_kind, 0) + 1
                kind_ordinals[copy.location_kind] = ordinal
                label = f"{copy.location_kind}:residual:{ordinal}"
                operation_id = hashlib.sha256(
                    (plan.id + copy.location_kind + label + copy.expected_hash).encode(
                        "utf-8"
                    )
                ).hexdigest()
                additions.append(
                    (
                        PurgeOperation(
                            operation_id,
                            copy.location_kind,
                            label,
                            copy.expected_hash,
                        ),
                        copy.locator,
                    )
                )
            self.repository.finish_purge_incomplete(
                plan.id,
                tombstone_json=self._updated_tombstone(
                    tombstone_json,
                    PurgeStatus.PURGE_INCOMPLETE,
                    len(residual_copies) + len(failed_kinds),
                ),
                residual_kinds=tuple(sorted(set(residual_kinds))),
                residual_operations=tuple(additions),
                actor=actor,
            )
            return PurgeStatus.PURGE_INCOMPLETE

        counts: dict[str, int] = {}
        for operation in plan.operations:
            counts[operation.location_kind] = counts.get(operation.location_kind, 0) + 1
        self.repository.complete_purge(
            plan.id,
            tombstone_json=self._updated_tombstone(
                tombstone_json, PurgeStatus.PURGED, 0
            ),
            kind_counts=counts,
            actor=actor,
        )
        return PurgeStatus.PURGED

    @staticmethod
    def _updated_tombstone(
        tombstone_json: str, status: PurgeStatus, residual_count: int
    ) -> str:
        payload = json.loads(tombstone_json)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload["status"] = status.value
        payload["residual_count"] = residual_count
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _clean_registered_file(
        self, copy: _ManifestCopy, expected_hash: str, marker: bytes
    ) -> None:
        target = self._runtime_target(copy)
        if not target.exists():
            return
        before = target.read_bytes()
        if marker not in before:
            return
        if hashlib.sha256(before).hexdigest() != expected_hash:
            raise ValueError("registered purge copy changed after preflight")
        if copy.location_kind.endswith("_backup"):
            target.unlink()
            if target.exists() or target.is_symlink():
                raise OSError("purge backup delete readback failed")
            return
        after = before.replace(marker, b"")
        if not after:
            target.unlink()
            if target.exists() or target.is_symlink():
                raise OSError("purge delete readback failed")
            return

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".agentretro-purge-", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, target.stat().st_mode)
            self._replace(temporary, target)
            if target.read_bytes() != after or marker in target.read_bytes():
                raise OSError("purge replace readback failed")
        finally:
            if temporary.exists():
                temporary.unlink()

    def _runtime_target(self, copy: _ManifestCopy) -> Path:
        assert copy.path is not None
        target = copy.path
        if target.is_symlink():
            raise UnsafePurgeRegistration("registered purge path became a symlink")
        if not target.exists():
            return target
        if copy.location_kind == "managed_vault":
            if self.vault_root is None:
                raise UnsafePurgeRegistration("managed vault is unavailable")
            return self._validated_child(
                self._validated_root(self.vault_root, "managed vault"),
                target,
                "managed vault",
            )
        if copy.location_kind in self.backup_roots:
            return self._validated_child(
                self._validated_root(
                    self.backup_roots[copy.location_kind], copy.location_kind
                ),
                target,
                copy.location_kind,
            )
        allowed = {
            path.resolve(strict=True)
            for path in self.log_paths + self.trace_paths
            if path.exists() and not path.is_symlink()
        }
        resolved = target.resolve(strict=True)
        if resolved not in allowed:
            raise UnsafePurgeRegistration("registered purge file identity changed")
        return resolved

    @staticmethod
    def _knowledge_id_from_plan(plan_id: str) -> str:
        if not plan_id.startswith("purge-v1-"):
            raise UnknownPurgePlan("purge plan identity is malformed")
        encoded_and_digest = plan_id.removeprefix("purge-v1-")
        try:
            encoded, digest = encoded_and_digest.rsplit("-", 1)
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError
            padding = "=" * (-len(encoded) % 4)
            knowledge_id = urlsafe_b64decode(encoded + padding).decode("utf-8")
        except (Base64Error, UnicodeDecodeError, ValueError) as exc:
            raise UnknownPurgePlan("purge plan identity is malformed") from exc
        if not knowledge_id:
            raise UnknownPurgePlan("purge plan identity is malformed")
        return knowledge_id

    def _managed_vault_copies(
        self, project_id: str, marker: bytes
    ) -> list[_ManifestCopy]:
        if self.vault_root is None:
            return []
        root = self._validated_root(self.vault_root, "managed vault")
        copies: list[_ManifestCopy] = []
        for state in self.repository.list_managed_file_states(project_id):
            target = Path(state.path)
            if not target.exists() and not target.is_symlink():
                self._validate_absent_child(root, target, "managed vault")
                continue
            resolved = self._validated_child(root, target, "managed vault")
            content = resolved.read_bytes()
            if marker in content:
                relative = resolved.relative_to(root).as_posix()
                copies.append(
                    _ManifestCopy("managed_vault", relative, content, resolved)
                )
        return copies

    def _registered_file_copies(self, marker: bytes) -> list[_ManifestCopy]:
        copies: list[_ManifestCopy] = []
        seen: set[Path] = set()
        for kind, root_value in sorted(self.backup_roots.items()):
            root = self._validated_root(root_value, kind)
            if not root.exists():
                continue
            for directory, dirnames, filenames in os.walk(root, followlinks=False):
                directory_path = Path(directory)
                for name in dirnames:
                    if (directory_path / name).is_symlink():
                        raise UnsafePurgeRegistration(
                            f"{kind} registration contains a symlink"
                        )
                dirnames[:] = sorted(dirnames)
                for name in sorted(filenames):
                    candidate = directory_path / name
                    if candidate.is_symlink():
                        raise UnsafePurgeRegistration(
                            f"{kind} registration contains a symlink"
                        )
                    resolved = self._validated_child(root, candidate, kind)
                    content = resolved.read_bytes()
                    if marker in content and resolved not in seen:
                        seen.add(resolved)
                        copies.append(
                            _ManifestCopy(
                                kind,
                                resolved.relative_to(root).as_posix(),
                                content,
                                resolved,
                            )
                        )

        explicit = (
            ("agentretro_log", self.log_paths),
            ("model_trace", self.trace_paths),
        )
        for kind, paths in explicit:
            for index, path in enumerate(sorted(paths, key=str), start=1):
                if path.is_symlink():
                    raise UnsafePurgeRegistration(f"{kind} path must not be a symlink")
                if not path.exists():
                    continue
                resolved = path.resolve(strict=True)
                if resolved in seen:
                    continue
                content = resolved.read_bytes()
                if marker in content:
                    seen.add(resolved)
                    copies.append(
                        _ManifestCopy(kind, f"registered-{index}", content, resolved)
                    )
        return copies

    @staticmethod
    def _validated_root(root_value: Path, label: str) -> Path:
        root = Path(root_value)
        if root.is_symlink():
            raise UnsafePurgeRegistration(f"{label} root must not be a symlink")
        if not root.exists():
            return root.resolve()
        if not root.is_dir():
            raise UnsafePurgeRegistration(f"{label} root must be a directory")
        return root.resolve(strict=True)

    @staticmethod
    def _validated_child(root: Path, target: Path, label: str) -> Path:
        current = target
        while current != root and current != current.parent:
            if current.is_symlink():
                raise UnsafePurgeRegistration(
                    f"{label} registration contains a symlink"
                )
            current = current.parent
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError) as exc:
            raise UnsafePurgeRegistration(
                f"{label} registration escapes its configured root"
            ) from exc
        if not resolved.is_file():
            raise UnsafePurgeRegistration(f"{label} registration must be a file")
        return resolved

    @staticmethod
    def _validate_absent_child(root: Path, target: Path, label: str) -> None:
        try:
            parent = target.parent.resolve(strict=True)
            parent.relative_to(root)
        except (FileNotFoundError, ValueError) as exc:
            raise UnsafePurgeRegistration(
                f"{label} registration escapes its configured root"
            ) from exc
        current = target.parent
        while current != root and current != current.parent:
            if current.is_symlink():
                raise UnsafePurgeRegistration(
                    f"{label} registration contains a symlink"
                )
            current = current.parent
