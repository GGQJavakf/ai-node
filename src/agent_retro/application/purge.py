"""Explicit, read-only sensitive-purge impact planning."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import (
    ProjectionStatus,
    PurgeJournal,
    PurgeJournalOperation,
    PurgeOperation,
    PurgePlan,
    PurgeStatus,
)


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


class PurgeBlockedError(PurgeError):
    """Projection and briefing are blocked by an active purge journal."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status
        self.recovery_command = "retro knowledge purge <id> --recover"


class PurgeRecoveryNotFound(PurgeError):
    """No purge journal exists for the requested identity."""


class PurgeAlreadyComplete(PurgeError):
    """The requested purge journal is already complete."""


class PurgeRecoveryNotIncomplete(PurgeError):
    """Only an incomplete purge journal can be recovered."""


@dataclass(frozen=True)
class PurgeProjectionResult:
    """Path-free projection result retained by the initiating purge command."""

    event_id: str
    status: ProjectionStatus
    warning: str = ""
    recovery_command: str = ""
    reason: str = ""


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
        log_root: Path | None = None,
        trace_root: Path | None = None,
        replace: Callable[[Path, Path], object] = os.replace,
        completed_projection: Callable[[str, str, str], object] | None = None,
    ) -> None:
        self.repository = repository
        self.vault_root = None if vault_root is None else Path(vault_root)
        self.backup_roots = {
            str(kind): Path(root) for kind, root in (backup_roots or {}).items()
        }
        self.log_paths = tuple(Path(path) for path in log_paths)
        self.trace_paths = tuple(Path(path) for path in trace_paths)
        self.log_root = self._configured_explicit_root(log_root, self.log_paths)
        self.trace_root = self._configured_explicit_root(trace_root, self.trace_paths)
        self._replace = replace
        self._completed_projection = completed_projection
        self.projection_result: PurgeProjectionResult | None = None

    def plan(self, knowledge_id: str) -> PurgePlan:
        plan, _, _, _ = self._current_manifest(knowledge_id)
        return plan

    def apply(
        self,
        plan_id: str,
        confirmed_operation_ids: frozenset[str],
        actor: str = "user",
    ) -> PurgeStatus:
        self.projection_result = None
        knowledge_id = self._knowledge_id_from_plan(plan_id)
        try:
            current, copies, markers, project_id = self._current_manifest(knowledge_id)
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
        recovery_payloads = {
            operation.id: self._recovery_payload(copy, markers)
            for operation, copy in zip(current.operations, copies, strict=True)
            if copy.path is not None
        }
        planned_file_manifest = self._file_manifest(copies)
        self.repository.begin_purge(
            current,
            plan_hash=json.dumps(
                {
                    "manifest_hash": hashlib.sha256(
                        current.id.encode("utf-8")
                    ).hexdigest(),
                    "marker_hash": hashlib.sha256(markers[0]).hexdigest(),
                    "marker_length": len(markers[0]),
                    "marker_fingerprints": [
                        {
                            "hash": hashlib.sha256(marker).hexdigest(),
                            "length": len(marker),
                        }
                        for marker in markers
                    ],
                    "project_id": project_id,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            actor=actor,
            markers=markers,
            journal_locations=journal_locations,
            database_expected_hashes=database_expected,
            recovery_payloads=recovery_payloads,
            tombstone_json=tombstone,
            precommit_guard=lambda: self._guard_file_manifest(
                planned_file_manifest, copies, markers
            ),
        )
        failed_kinds: list[str] = []
        for operation, copy in zip(current.operations, copies, strict=True):
            if copy.path is None:
                continue
            try:
                self._clean_registered_file(copy, operation.expected_hash, markers)
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
            markers,
            project_id,
            tombstone,
            actor,
            failed_kinds,
        )

    def recover(self, knowledge_id: str, actor: str = "user") -> PurgeStatus:
        self.projection_result = None
        journal = self.repository.get_purge_journal(knowledge_id)
        if journal is None:
            raise PurgeRecoveryNotFound("purge recovery journal was not found")
        if journal.status is PurgeStatus.PURGED:
            raise PurgeAlreadyComplete("purge is already complete")
        if journal.status is not PurgeStatus.PURGE_INCOMPLETE:
            raise PurgeRecoveryNotIncomplete(
                "purge recovery requires purge_incomplete state"
            )

        failed_kinds: list[str] = []
        for operation in journal.operations:
            if operation.status == "completed":
                continue
            if operation.location_kind.startswith("sqlite_"):
                failed_kinds.append(operation.location_kind)
                continue
            try:
                self._recover_operation(operation)
            except (OSError, ValueError):
                failed_kinds.append(operation.location_kind)
                self.repository.mark_purge_operation(
                    operation.id, "failed", "recovery_failed"
                )
            else:
                self.repository.mark_purge_operation(operation.id, "completed")

        residual_kinds = list(failed_kinds)
        if any(
            self.repository.purge_database_has_fingerprint(marker_hash, length)
            for marker_hash, length in journal.marker_fingerprints
        ):
            residual_kinds.append("sqlite")
        try:
            residual_kinds.extend(self._fingerprint_residual_kinds(journal))
        except (OSError, ValueError):
            residual_kinds.append("verification")

        if residual_kinds:
            self.repository.finish_purge_incomplete(
                journal.id,
                tombstone_json=self._updated_tombstone(
                    journal.tombstone_json,
                    PurgeStatus.PURGE_INCOMPLETE,
                    len(residual_kinds),
                ),
                residual_kinds=tuple(sorted(set(residual_kinds))),
                residual_operations=(),
                actor=actor,
            )
            return PurgeStatus.PURGE_INCOMPLETE

        counts: dict[str, int] = {}
        for operation in journal.operations:
            counts[operation.location_kind] = counts.get(operation.location_kind, 0) + 1
        self.repository.complete_purge(
            journal.id,
            tombstone_json=self._updated_tombstone(
                journal.tombstone_json, PurgeStatus.PURGED, 0
            ),
            kind_counts=counts,
            actor=actor,
        )
        self._project_completed(journal.knowledge_id, journal.project_id)
        return PurgeStatus.PURGED

    def _project_completed(self, knowledge_id: str, project_id: str) -> None:
        if self._completed_projection is None:
            return
        try:
            result = self._completed_projection(
                "sensitive_purge", knowledge_id, project_id
            )
            status = getattr(result, "status")
            if not isinstance(status, ProjectionStatus):
                status = ProjectionStatus(str(status))
            self.projection_result = PurgeProjectionResult(
                event_id=_safe_projection_token(getattr(result, "event_id", "")),
                status=status,
                warning=_safe_projection_warning(getattr(result, "warning", "")),
                recovery_command=_safe_projection_command(
                    getattr(result, "recovery_command", ""), status
                ),
                reason=_safe_projection_reason(getattr(result, "reason", ""), status),
            )
        except Exception:
            self.projection_result = PurgeProjectionResult(
                event_id="",
                status=ProjectionStatus.SYNC_PENDING,
                recovery_command="retro doctor --repair-sync",
                reason="projection_failed",
            )

    def _recover_operation(self, operation: PurgeJournalOperation) -> None:
        try:
            payload = json.loads(operation.recovery_json)
            action = str(payload["action"])
            after_hash = str(payload["after_hash"])
            ranges = tuple(
                (int(item[0]), int(item[1])) for item in payload.get("ranges", ())
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("purge recovery payload is invalid") from exc
        if action not in {"delete", "remove_ranges"} or len(after_hash) != 64:
            raise ValueError("purge recovery payload is invalid")

        target = self._journal_target(operation)
        if target is None:
            return
        if not target.exists():
            return
        before = target.read_bytes()
        current_hash = hashlib.sha256(before).hexdigest()
        if current_hash == after_hash:
            return
        if current_hash != operation.expected_hash:
            raise ValueError("purge recovery target changed")
        if action == "delete":
            target.unlink()
            if target.exists() or target.is_symlink():
                raise OSError("purge recovery delete readback failed")
            return

        cursor = 0
        chunks: list[bytes] = []
        for start, length in ranges:
            if start < cursor or length <= 0 or start + length > len(before):
                raise ValueError("purge recovery ranges are invalid")
            chunks.append(before[cursor:start])
            cursor = start + length
        chunks.append(before[cursor:])
        after = b"".join(chunks)
        if hashlib.sha256(after).hexdigest() != after_hash:
            raise ValueError("purge recovery result is invalid")
        self._atomic_write(target, after)

    def _journal_target(self, operation: PurgeJournalOperation) -> Path | None:
        relative = Path(operation.locator)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("purge recovery locator is invalid")
        if operation.location_kind == "managed_vault":
            if self.vault_root is None:
                raise ValueError("managed vault is unavailable")
            root = self._validated_root(self.vault_root, "managed vault")
            target = root / relative
        elif operation.location_kind in self.backup_roots:
            root = self._validated_root(
                self.backup_roots[operation.location_kind], operation.location_kind
            )
            target = root / relative
        elif operation.location_kind in {"agentretro_log", "model_trace"}:
            if not _is_registered_identity(operation.locator):
                raise ValueError("purge recovery locator is invalid")
            return self._registered_identity_map(operation.location_kind).get(
                operation.locator
            )
        else:
            raise ValueError("purge recovery kind is invalid")

        if target.is_symlink():
            raise ValueError("purge recovery target is a symlink")
        if target.exists():
            return self._validated_child(root, target, operation.location_kind)
        self._validate_absent_child(root, target, operation.location_kind)
        return target

    def _atomic_write(self, target: Path, after: bytes) -> None:
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
            if target.read_bytes() != after:
                raise OSError("purge recovery readback failed")
        finally:
            if temporary.exists():
                temporary.unlink()

    def _fingerprint_residual_kinds(self, journal: PurgeJournal) -> tuple[str, ...]:
        kinds: set[str] = set()
        if self.vault_root is not None:
            root = self._validated_root(self.vault_root, "managed vault")
            for state in self.repository.list_managed_file_states(journal.project_id):
                target = Path(state.path)
                if not target.exists() and not target.is_symlink():
                    self._validate_absent_child(root, target, "managed vault")
                    continue
                resolved = self._validated_child(root, target, "managed vault")
                if _has_any_fingerprint(
                    resolved.read_bytes(), journal.marker_fingerprints
                ):
                    kinds.add("managed_vault")

        for kind, root_value in sorted(self.backup_roots.items()):
            root = self._validated_root(root_value, kind)
            if not root.exists():
                continue
            for directory, dirnames, filenames in os.walk(root, followlinks=False):
                directory_path = Path(directory)
                if any((directory_path / name).is_symlink() for name in dirnames):
                    raise ValueError("registered recovery root contains a symlink")
                for name in filenames:
                    target = directory_path / name
                    if target.is_symlink():
                        raise ValueError("registered recovery root contains a symlink")
                    if _has_any_fingerprint(
                        target.read_bytes(), journal.marker_fingerprints
                    ):
                        kinds.add(kind)
        for kind in ("agentretro_log", "model_trace"):
            for target in self._registered_files(kind):
                if _has_any_fingerprint(
                    target.read_bytes(), journal.marker_fingerprints
                ):
                    kinds.add(kind)
        return tuple(sorted(kinds))

    def _current_manifest(
        self, knowledge_id: str
    ) -> tuple[PurgePlan, tuple[_ManifestCopy, ...], tuple[bytes, ...], str]:
        inspection = self.repository.inspect_purge_database(knowledge_id)
        if inspection.already_purged:
            raise KnowledgeAlreadyPurged("knowledge is already purged")
        if inspection.knowledge is None:
            raise PurgeKnowledgeNotFound("knowledge was not found")
        if inspection.sync_pending:
            raise KnowledgeSyncPending("knowledge projection is sync_pending")

        markers = inspection.markers
        if not markers:
            raise PurgeKnowledgeNotFound("knowledge has no purgeable content")
        copies = [
            _ManifestCopy(item.location_kind, item.locator, item.content)
            for item in inspection.copies
        ]
        copies.extend(
            self._managed_vault_copies(inspection.knowledge.project_id, markers)
        )
        copies.extend(self._registered_file_copies(markers))
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
            markers,
            inspection.knowledge.project_id,
        )

    @staticmethod
    def _file_manifest(
        copies: Sequence[_ManifestCopy],
    ) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            sorted(
                (
                    copy.location_kind,
                    copy.locator,
                    copy.expected_hash,
                )
                for copy in copies
                if copy.path is not None
            )
        )

    def _guard_file_manifest(
        self,
        planned_manifest: tuple[tuple[str, str, str], ...],
        planned_copies: Sequence[_ManifestCopy],
        markers: Sequence[bytes],
    ) -> None:
        current: dict[tuple[str, str], _ManifestCopy] = {}
        for copy in planned_copies:
            if copy.path is None or copy.location_kind != "managed_vault":
                continue
            target = self._runtime_target(copy)
            if not target.exists():
                continue
            content = target.read_bytes()
            if _contains_any(content, markers):
                current[(copy.location_kind, copy.locator)] = _ManifestCopy(
                    copy.location_kind, copy.locator, content, target
                )
        for copy in self._registered_file_copies(markers):
            current[(copy.location_kind, copy.locator)] = copy
        if self._file_manifest(tuple(current.values())) != planned_manifest:
            raise StalePurgePlan("purge plan no longer matches current state")

    def _finish_file_stage(
        self,
        plan: PurgePlan,
        planned_copies: tuple[_ManifestCopy, ...],
        markers: tuple[bytes, ...],
        project_id: str,
        tombstone_json: str,
        actor: str,
        failed_kinds: list[str],
    ) -> PurgeStatus:
        residual_copies: list[_ManifestCopy] = []
        residual_kinds = list(failed_kinds)
        try:
            residual_kinds.extend(
                self.repository.purge_database_residual_kinds(
                    markers,
                    tuple(copy.locator for copy in planned_copies if copy.path is None),
                )
            )
            residual_copies.extend(self._managed_vault_copies(project_id, markers))
            residual_copies.extend(self._registered_file_copies(markers))
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
            additions: list[tuple[PurgeOperation, str, str]] = []
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
                        self._recovery_payload(copy, markers),
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
        self._project_completed(plan.knowledge_id, project_id)
        return PurgeStatus.PURGED

    @staticmethod
    def _recovery_payload(copy: _ManifestCopy, markers: Sequence[bytes]) -> str:
        ranges = _removal_ranges(copy.content, markers)
        after = _remove_ranges(copy.content, ranges)
        action = (
            "delete"
            if copy.location_kind.endswith("_backup") or not after
            else "remove_ranges"
        )
        return json.dumps(
            {
                "action": action,
                "after_hash": hashlib.sha256(after).hexdigest(),
                "ranges": ranges,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

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
        self, copy: _ManifestCopy, expected_hash: str, markers: Sequence[bytes]
    ) -> None:
        target = self._runtime_target(copy)
        if not target.exists():
            return
        before = target.read_bytes()
        if not _contains_any(before, markers):
            return
        if hashlib.sha256(before).hexdigest() != expected_hash:
            raise ValueError("registered purge copy changed after preflight")
        if copy.location_kind.endswith("_backup"):
            target.unlink()
            if target.exists() or target.is_symlink():
                raise OSError("purge backup delete readback failed")
            return
        after = _remove_markers(before, markers)
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
            if target.read_bytes() != after or _contains_any(
                target.read_bytes(), markers
            ):
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
        if copy.location_kind in {"agentretro_log", "model_trace"}:
            root = self._explicit_root(copy.location_kind)
            if root is None:
                raise UnsafePurgeRegistration("registered purge root is unavailable")
            resolved = self._validated_child(
                self._validated_root(root, copy.location_kind),
                target,
                copy.location_kind,
            )
            if (
                self._registered_identity(copy.location_kind, root, resolved)
                != copy.locator
            ):
                raise UnsafePurgeRegistration("registered purge file identity changed")
            return resolved
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
        self, project_id: str, markers: Sequence[bytes]
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
            if _contains_any(content, markers):
                relative = resolved.relative_to(root).as_posix()
                copies.append(
                    _ManifestCopy("managed_vault", relative, content, resolved)
                )
        return copies

    def _registered_file_copies(self, markers: Sequence[bytes]) -> list[_ManifestCopy]:
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
                    if _contains_any(content, markers) and resolved not in seen:
                        seen.add(resolved)
                        copies.append(
                            _ManifestCopy(
                                kind,
                                resolved.relative_to(root).as_posix(),
                                content,
                                resolved,
                            )
                        )

        for kind in ("agentretro_log", "model_trace"):
            root = self._explicit_root(kind)
            if root is None:
                continue
            for resolved in self._registered_files(kind):
                if resolved in seen:
                    continue
                content = resolved.read_bytes()
                if _contains_any(content, markers):
                    seen.add(resolved)
                    copies.append(
                        _ManifestCopy(
                            kind,
                            self._registered_identity(kind, root, resolved),
                            content,
                            resolved,
                        )
                    )
        return copies

    @staticmethod
    def _configured_explicit_root(
        configured: Path | None, paths: Sequence[Path]
    ) -> Path | None:
        if configured is not None:
            root = Path(configured)
        elif not paths:
            return None
        else:
            parents = {Path(path).parent.resolve() for path in paths}
            if len(parents) != 1:
                raise UnsafePurgeRegistration(
                    "registered purge paths require one explicit root"
                )
            root = parents.pop()
        resolved_root = root.resolve()
        for path in paths:
            try:
                Path(path).resolve().relative_to(resolved_root)
            except ValueError as exc:
                raise UnsafePurgeRegistration(
                    "registered purge path escapes its configured root"
                ) from exc
        return root

    def _explicit_root(self, kind: str) -> Path | None:
        return self.log_root if kind == "agentretro_log" else self.trace_root

    def _registered_files(self, kind: str) -> tuple[Path, ...]:
        root_value = self._explicit_root(kind)
        if root_value is None:
            return ()
        root = self._validated_root(root_value, kind)
        if not root.exists():
            return ()
        files: list[Path] = []
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            for name in dirnames:
                if (directory_path / name).is_symlink():
                    raise UnsafePurgeRegistration(
                        f"{kind} registration contains a symlink"
                    )
            dirnames[:] = sorted(dirnames)
            for name in sorted(filenames):
                target = directory_path / name
                if target.is_symlink():
                    raise UnsafePurgeRegistration(
                        f"{kind} registration contains a symlink"
                    )
                files.append(self._validated_child(root, target, kind))
        return tuple(files)

    def _registered_identity_map(self, kind: str) -> dict[str, Path]:
        root = self._explicit_root(kind)
        if root is None:
            return {}
        identities: dict[str, Path] = {}
        for target in self._registered_files(kind):
            identity = self._registered_identity(kind, root, target)
            if identity in identities:
                raise UnsafePurgeRegistration("registered purge identity collision")
            identities[identity] = target
        return identities

    def _registered_identity(self, kind: str, root_value: Path, target: Path) -> str:
        root = self._validated_root(root_value, kind)
        resolved = self._validated_child(root, target, kind)
        relative = resolved.relative_to(root).as_posix()
        normalized = unicodedata.normalize("NFC", relative)
        if os.name == "nt":
            normalized = normalized.casefold()
        digest = hashlib.sha256((kind + "\0" + normalized).encode("utf-8")).hexdigest()
        return "registered-" + digest

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


def require_no_active_purge(
    repository: RetroRepository,
    *,
    project_id: str | None = None,
    knowledge_id: str | None = None,
) -> None:
    checker = getattr(repository, "active_purge_block", None)
    if checker is None:
        return
    status = checker(project_id=project_id, knowledge_id=knowledge_id)
    if status is not None:
        raise PurgeBlockedError(status)


def _has_sha256_window(content: bytes, expected_hash: str, length: int) -> bool:
    if length <= 0 or len(expected_hash) != 64 or len(content) < length:
        return False
    return any(
        hashlib.sha256(content[offset : offset + length]).hexdigest() == expected_hash
        for offset in range(len(content) - length + 1)
    )


def _has_any_fingerprint(
    content: bytes, fingerprints: Sequence[tuple[str, int]]
) -> bool:
    return any(
        _has_sha256_window(content, marker_hash, length)
        for marker_hash, length in fingerprints
    )


def _contains_any(content: bytes, markers: Sequence[bytes]) -> bool:
    return any(marker in content for marker in markers)


def _is_registered_identity(locator: str) -> bool:
    digest = locator.removeprefix("registered-")
    return (
        locator.startswith("registered-")
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _remove_markers(content: bytes, markers: Sequence[bytes]) -> bytes:
    result = content
    for marker in markers:
        result = result.replace(marker, b"")
    return result


def _removal_ranges(content: bytes, markers: Sequence[bytes]) -> list[list[int]]:
    intervals: list[tuple[int, int]] = []
    for marker in markers:
        offset = 0
        while True:
            found = content.find(marker, offset)
            if found < 0:
                break
            intervals.append((found, found + len(marker)))
            offset = found + len(marker)
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][0] + merged[-1][1]:
            previous_end = merged[-1][0] + merged[-1][1]
            merged[-1][1] = max(previous_end, end) - merged[-1][0]
        else:
            merged.append([start, end - start])
    return merged


def _remove_ranges(content: bytes, ranges: Sequence[Sequence[int]]) -> bytes:
    cursor = 0
    chunks: list[bytes] = []
    for start, length in ranges:
        chunks.append(content[cursor:start])
        cursor = start + length
    chunks.append(content[cursor:])
    return b"".join(chunks)


def _safe_projection_token(value: object) -> str:
    token = str(value)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if 0 < len(token) <= 128 and all(character in allowed for character in token):
        return token
    return ""


def _safe_projection_warning(value: object) -> str:
    warning = str(value)
    return (
        warning
        if warning in {"", "RETRO_SYNC_PENDING", "RETRO_ROLLBACK_REQUIRED"}
        else "RETRO_SYNC_PENDING"
    )


def _safe_projection_command(value: object, status: ProjectionStatus) -> str:
    command = str(value)
    if command == "retro doctor --repair-sync":
        return command
    prefix = "retro sync retry "
    if command.startswith(prefix) and _safe_projection_token(command[len(prefix) :]):
        return command
    return "" if status is ProjectionStatus.SYNCED else "retro doctor --repair-sync"


def _safe_projection_reason(value: object, status: ProjectionStatus) -> str:
    reason = str(value)
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"
    if not reason:
        return ""
    if len(reason) <= 64 and all(character in allowed for character in reason):
        return reason
    return "" if status is ProjectionStatus.SYNCED else "projection_pending"
