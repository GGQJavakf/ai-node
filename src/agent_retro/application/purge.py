"""Explicit, read-only sensitive-purge impact planning."""

from __future__ import annotations

import hashlib
import json
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

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
    ) -> None:
        self.repository = repository
        self.vault_root = None if vault_root is None else Path(vault_root)
        self.backup_roots = {
            str(kind): Path(root) for kind, root in (backup_roots or {}).items()
        }
        self.log_paths = tuple(Path(path) for path in log_paths)
        self.trace_paths = tuple(Path(path) for path in trace_paths)

    def plan(self, knowledge_id: str) -> PurgePlan:
        plan, _, _ = self._current_manifest(knowledge_id)
        return plan

    def apply(
        self,
        plan_id: str,
        confirmed_operation_ids: frozenset[str],
        actor: str = "user",
    ) -> PurgeStatus:
        knowledge_id = self._knowledge_id_from_plan(plan_id)
        try:
            current, copies, marker = self._current_manifest(knowledge_id)
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
        return PurgeStatus.PURGE_IN_PROGRESS

    def _current_manifest(
        self, knowledge_id: str
    ) -> tuple[PurgePlan, tuple[_ManifestCopy, ...], bytes]:
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
        )

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
            resolved = self._validated_child(root, target, "managed vault")
            if not resolved.exists():
                continue
            content = resolved.read_bytes()
            if marker in content:
                relative = resolved.relative_to(root).as_posix()
                copies.append(_ManifestCopy("managed_vault", relative, content))
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
                dirnames[:] = sorted(
                    name
                    for name in dirnames
                    if not (directory_path / name).is_symlink()
                )
                for name in sorted(filenames):
                    candidate = directory_path / name
                    if candidate.is_symlink():
                        continue
                    resolved = self._validated_child(root, candidate, kind)
                    content = resolved.read_bytes()
                    if marker in content and resolved not in seen:
                        seen.add(resolved)
                        copies.append(
                            _ManifestCopy(
                                kind,
                                resolved.relative_to(root).as_posix(),
                                content,
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
                    copies.append(_ManifestCopy(kind, f"registered-{index}", content))
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
