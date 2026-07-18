"""Explicit reconciliation and hash-bound deep Obsidian merge plans."""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from agent_retro.application.ports import RetroRepository
from agent_retro.application.sync import ProjectionPersistenceError, SyncService
from agent_retro.domain.models import (
    Candidate,
    CandidateStatus,
    Knowledge,
    KnowledgeType,
    SyncJob,
    VaultAdoption,
)
from agent_retro.domain.projection import projection_input_hash
from agent_retro.infrastructure.obsidian import (
    BoundaryError,
    managed_block_hash,
    managed_block_bytes,
    parse_aggregate_entries,
    replace_managed_block_bytes,
    sha256_bytes,
)
from agent_retro.infrastructure.redaction import Redactor


class MergeIntegrityError(ValueError):
    """A persisted plan or caller-supplied identity was modified."""


class StalePlanError(ValueError):
    """The vault no longer matches the immutable plan inputs."""


class ConfirmationRequiredError(ValueError):
    """General apply or exact destructive confirmation is missing."""

    def __init__(self, missing_operation_ids: Sequence[str] = ()) -> None:
        self.missing_operation_ids = tuple(sorted(missing_operation_ids))
        reason = (
            "merge_apply_confirmation_required"
            if not self.missing_operation_ids
            else "merge_operation_confirmation_required"
        )
        super().__init__(reason)


class SensitiveMergeContentError(ValueError):
    """A merge plan would persist or expose a credential-shaped value."""


@dataclass(frozen=True)
class MergeTarget:
    path: Path
    path_identity: str
    input_exists: bool
    input_kind: str
    input_hash: str
    output_bytes: bytes
    unified_diff: str


@dataclass(frozen=True)
class MergeDelete:
    operation_id: str
    path: Path
    path_identity: str
    input_exists: bool
    input_kind: str
    input_hash: str


@dataclass(frozen=True)
class MergeRename:
    operation_id: str
    source: Path
    target: Path
    source_identity: str
    target_identity: str
    source_exists: bool
    source_kind: str
    target_exists: bool
    target_kind: str
    source_hash: str
    target_hash: str


@dataclass(frozen=True)
class MergeConflict:
    operation_id: str
    description: str


@dataclass(frozen=True)
class MergePlan:
    id: str
    project_id: str
    authority_hash: str
    targets: tuple[MergeTarget, ...]
    deletes: tuple[MergeDelete, ...]
    renames: tuple[MergeRename, ...]
    conflicts: tuple[MergeConflict, ...]


@dataclass(frozen=True)
class MergeApplyResult:
    plan_id: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class ReconciliationConflict:
    id: str
    project_id: str
    path: Path
    recorded_hash: str
    vault_hash: str
    status: str = "external_edit_conflict"


@dataclass(frozen=True)
class ReconciliationResult:
    conflict_id: str
    status: str
    candidate_id: str = ""
    plan_id: str = ""


class MergeService:
    """Persist previews and apply only current, fully confirmed plans."""

    def __init__(
        self,
        repository: RetroRepository,
        vault_root: Path | None,
        backup_root: Path,
        *,
        sync: SyncService | None = None,
    ) -> None:
        if vault_root is None:
            raise ValueError("vault_not_configured")
        self.repository = repository
        self.vault_root = Path(vault_root)
        self.backup_root = Path(backup_root)
        self.sync = sync or SyncService(repository, self.vault_root, self.backup_root)

    def create_plan(
        self,
        project_id: str,
        *,
        replacements: Mapping[Path, bytes],
        deletes: Sequence[Path] = (),
        renames: Sequence[tuple[Path, Path]] = (),
        conflicts: Sequence[str] = (),
    ) -> MergePlan:
        self._validate_sensitive_plan_inputs(
            project_id, replacements, deletes, renames, conflicts
        )
        self._require_mapping(project_id)
        target_values = []
        for relative, output in sorted(
            (
                (self._safe_relative(project_id, path), output)
                for path, output in replacements.items()
            ),
            key=lambda item: item[0].as_posix(),
        ):
            exists, kind, before = self._read_state(relative)
            if kind not in ("missing", "file"):
                raise StalePlanError("merge_target_not_file")
            self._validate_existing_merge_bytes(before)
            target_values.append(
                MergeTarget(
                    path=relative,
                    path_identity=_windows_path_identity(relative),
                    input_exists=exists,
                    input_kind=kind,
                    input_hash=sha256_bytes(before),
                    output_bytes=bytes(output),
                    unified_diff=_unified_diff(relative, before, bytes(output)),
                )
            )
        targets = tuple(target_values)
        delete_values = []
        for path in sorted(deletes, key=lambda item: item.as_posix()):
            relative = self._safe_relative(project_id, path)
            exists, kind, before = self._read_state(relative)
            if not exists:
                raise StalePlanError("merge_delete_source_missing")
            if kind != "file":
                raise StalePlanError("merge_delete_source_not_file")
            self._validate_existing_merge_bytes(before)
            path_identity = _windows_path_identity(relative)
            identity = ["delete", path_identity, exists, kind, sha256_bytes(before)]
            delete_values.append(
                MergeDelete(
                    _operation_id(identity),
                    relative,
                    path_identity,
                    exists,
                    kind,
                    sha256_bytes(before),
                )
            )
        rename_values = []
        for source, target in sorted(
            renames, key=lambda item: (item[0].as_posix(), item[1].as_posix())
        ):
            source_relative = self._safe_relative(project_id, source)
            target_relative = self._safe_relative(project_id, target)
            source_exists, source_kind, source_bytes = self._read_state(source_relative)
            target_exists, target_kind, target_bytes = self._read_state(target_relative)
            if not source_exists:
                raise StalePlanError("merge_rename_source_missing")
            if source_kind != "file" or target_kind not in ("missing", "file"):
                raise StalePlanError("merge_rename_target_not_file")
            self._validate_existing_merge_bytes(source_bytes)
            self._validate_existing_merge_bytes(target_bytes)
            source_hash = sha256_bytes(source_bytes)
            target_hash = sha256_bytes(target_bytes)
            source_identity = _windows_path_identity(source_relative)
            target_identity = _windows_path_identity(target_relative)
            identity = [
                "rename",
                source_identity,
                target_identity,
                source_exists,
                source_kind,
                target_exists,
                target_kind,
                source_hash,
                target_hash,
            ]
            rename_values.append(
                MergeRename(
                    _operation_id(identity),
                    source_relative,
                    target_relative,
                    source_identity,
                    target_identity,
                    source_exists,
                    source_kind,
                    target_exists,
                    target_kind,
                    source_hash,
                    target_hash,
                )
            )
        conflict_values = tuple(
            MergeConflict(_operation_id(["conflict", description]), description)
            for description in sorted(conflicts)
        )
        plan = MergePlan(
            id="",
            project_id=project_id,
            authority_hash=projection_input_hash(
                self.repository.list_project_knowledge(project_id)
            ),
            targets=targets,
            deletes=tuple(delete_values),
            renames=tuple(rename_values),
            conflicts=conflict_values,
        )
        self._validate_unique_paths(plan)
        plan_json = _plan_json(plan)
        plan = MergePlan(
            id="merge-" + hashlib.sha256(plan_json.encode("utf-8")).hexdigest()[:24],
            project_id=plan.project_id,
            authority_hash=plan.authority_hash,
            targets=plan.targets,
            deletes=plan.deletes,
            renames=plan.renames,
            conflicts=plan.conflicts,
        )
        plan_json = _plan_json(plan)
        self.repository.begin_sync(
            SyncJob(
                id=plan.id,
                project_id=project_id,
                status="planned",
                plan_json=plan_json,
                backup_path=self.backup_root / plan.id,
            )
        )
        return plan

    def preview(self, plan_id: str) -> MergePlan:
        return self._load_plan(plan_id)

    def apply(
        self,
        plan_id: str,
        *,
        confirmed: bool,
        confirmed_operations: Sequence[str] = (),
    ) -> MergeApplyResult:
        if not confirmed:
            raise ConfirmationRequiredError()
        try:
            plan = self._load_plan(plan_id)
        except MergeIntegrityError:
            raise
        except ValueError as exc:
            raise StalePlanError("merge_plan_stale") from exc
        job = self._get_job(plan_id)
        if job is None:
            raise KeyError("merge_plan_not_found")
        if job.status == "synced":
            return MergeApplyResult(plan.id, "already_applied")
        required = {
            item.operation_id
            for item in (*plan.deletes, *plan.renames, *plan.conflicts)
        }
        supplied = set(confirmed_operations)
        missing = required - supplied
        if missing:
            raise ConfirmationRequiredError(tuple(missing))
        if supplied - required:
            raise MergeIntegrityError("unknown_merge_operation_confirmation")
        try:
            result = self.sync.apply_confirmed_merge(
                plan.id,
                confirmed_operations=tuple(sorted(supplied)),
                actor="user",
            )
        except ValueError as exc:
            if str(exc) == "merge_plan_stale":
                raise StalePlanError("merge_plan_stale") from exc
            raise
        status = (
            "already_applied"
            if result.reason == "already_applied"
            else result.status.value
        )
        return MergeApplyResult(plan.id, status, result.reason)

    def find_external_edits(
        self, project_id: str
    ) -> tuple[ReconciliationConflict, ...]:
        self._require_mapping(project_id)
        knowledge = self.repository.list_project_knowledge(project_id)
        authority_hash = projection_input_hash(knowledge)
        conflicts = []
        for state in self.repository.list_managed_file_states(project_id):
            target = self._absolute_from_state(project_id, state.path)
            current = target.read_bytes() if target.exists() else b""
            try:
                current_managed_hash = (
                    managed_block_hash(current)
                    if target.name.startswith("项目_") or target.name == "项目索引.md"
                    else sha256_bytes(current)
                )
            except BoundaryError:
                current_managed_hash = sha256_bytes(current)
            if current_managed_hash == state.managed_hash:
                continue
            relative = target.relative_to(self.vault_root)
            snapshot = self.repository.get_managed_file_snapshot(target)
            if snapshot is None:
                conflicts.append(
                    ReconciliationConflict(
                        _diagnostic_id(
                            project_id, relative, "managed_snapshot_unavailable"
                        ),
                        project_id,
                        relative,
                        state.managed_hash,
                        current_managed_hash,
                        "managed_snapshot_unavailable",
                    )
                )
                continue
            if (
                snapshot.project_id != project_id
                or snapshot.managed_hash != state.managed_hash
                or snapshot.snapshot_kind not in ("full", "managed_block")
            ):
                conflicts.append(
                    ReconciliationConflict(
                        _diagnostic_id(
                            project_id, relative, "managed_snapshot_invalid"
                        ),
                        project_id,
                        relative,
                        state.managed_hash,
                        current_managed_hash,
                        "managed_snapshot_invalid",
                    )
                )
                continue
            try:
                vault_owned_bytes = (
                    managed_block_bytes(current)
                    if snapshot.snapshot_kind == "managed_block"
                    else current
                )
            except BoundaryError:
                conflicts.append(
                    ReconciliationConflict(
                        _diagnostic_id(
                            project_id, relative, "managed_boundary_invalid"
                        ),
                        project_id,
                        relative,
                        state.managed_hash,
                        current_managed_hash,
                        "managed_boundary_invalid",
                    )
                )
                continue
            database_bytes = snapshot.owned_bytes
            try:
                database_text = database_bytes.decode("utf-8", errors="strict")
                vault_owned_text = vault_owned_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                conflicts.append(
                    ReconciliationConflict(
                        _diagnostic_id(
                            project_id, relative, "managed_snapshot_invalid"
                        ),
                        project_id,
                        relative,
                        state.managed_hash,
                        current_managed_hash,
                        "managed_snapshot_invalid",
                    )
                )
                continue
            redactor = Redactor()
            if redactor.contains_sensitive_value(database_text):
                conflicts.append(
                    ReconciliationConflict(
                        _diagnostic_id(
                            project_id, relative, "managed_snapshot_sensitive"
                        ),
                        project_id,
                        relative,
                        state.managed_hash,
                        current_managed_hash,
                        "managed_snapshot_sensitive",
                    )
                )
                continue
            redacted_vault_bytes = redactor.redact(vault_owned_text).encode("utf-8")
            vault_owned_hash = sha256_bytes(vault_owned_bytes)
            sensitive_blocker = redacted_vault_bytes != vault_owned_bytes
            current_full_hash = sha256_bytes(current)
            conflict_id = _reconciliation_id(
                project_id,
                relative,
                state.managed_hash,
                current_managed_hash,
                authority_hash,
                database_bytes,
                snapshot.snapshot_kind,
                current_full_hash,
                vault_owned_hash,
            )
            payload = _json(
                {
                    "kind": "reconciliation",
                    "id": conflict_id,
                    "project_id": project_id,
                    "path": relative.as_posix(),
                    "recorded_hash": state.managed_hash,
                    "vault_hash": current_managed_hash,
                    "authority_hash": authority_hash,
                    "snapshot_kind": snapshot.snapshot_kind,
                    "vault_full_hash": current_full_hash,
                    "vault_owned_hash": vault_owned_hash,
                    "sensitive_blocker": (
                        "sensitive_value_redacted" if sensitive_blocker else ""
                    ),
                    "database_base64": _b64(database_bytes),
                    "vault_base64": _b64(redacted_vault_bytes),
                }
            )
            existing = self._get_job(conflict_id)
            if existing is None:
                self.repository.begin_sync(
                    SyncJob(
                        id=conflict_id,
                        project_id=project_id,
                        status="external_edit_conflict",
                        plan_json=payload,
                        backup_path=self.backup_root / conflict_id,
                    )
                )
            elif existing.plan_json != payload:
                raise MergeIntegrityError("reconciliation_state_changed")
            conflicts.append(
                ReconciliationConflict(
                    conflict_id,
                    project_id,
                    relative,
                    state.managed_hash,
                    current_managed_hash,
                )
            )
        return tuple(conflicts)

    def reconcile(
        self, conflict_id: str, action: str, *, actor: str
    ) -> ReconciliationResult:
        if actor != "user":
            raise ValueError("reconciliation_actor_must_be_user")
        for diagnostic in (
            "managed_snapshot_unavailable",
            "managed_snapshot_invalid",
            "managed_snapshot_sensitive",
            "managed_boundary_invalid",
        ):
            if conflict_id.startswith(f"reconcile-diagnostic-{diagnostic}-"):
                raise ValueError(diagnostic)
        job = self._get_job(conflict_id)
        if job is None:
            raise KeyError("reconciliation_conflict_not_found")
        try:
            payload = json.loads(job.plan_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise MergeIntegrityError("reconciliation_plan_invalid") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("kind") != "reconciliation"
            or payload.get("id") != conflict_id
            or _json(payload) != job.plan_json
        ):
            raise MergeIntegrityError("reconciliation_plan_invalid")
        project_id = str(payload["project_id"])
        relative = self._safe_relative(project_id, Path(payload["path"]))
        target = self.vault_root / relative
        vault_owned_bytes = _unb64(payload["vault_base64"])
        database_bytes = _unb64(payload["database_base64"])
        snapshot_kind = str(payload["snapshot_kind"])
        vault_full_hash = str(payload["vault_full_hash"])
        vault_owned_hash = str(payload["vault_owned_hash"])
        if (
            _reconciliation_id(
                project_id,
                relative,
                str(payload["recorded_hash"]),
                str(payload["vault_hash"]),
                str(payload["authority_hash"]),
                database_bytes,
                snapshot_kind,
                vault_full_hash,
                vault_owned_hash,
            )
            != conflict_id
        ):
            raise MergeIntegrityError("reconciliation_plan_integrity_mismatch")
        if projection_input_hash(
            self.repository.list_project_knowledge(project_id)
        ) != str(payload["authority_hash"]):
            raise StalePlanError("reconciliation_authority_changed")
        if not target.is_file():
            raise StalePlanError("reconciliation_target_changed")
        current_full = target.read_bytes()
        try:
            current_owned = (
                managed_block_bytes(current_full)
                if snapshot_kind == "managed_block"
                else current_full
            )
        except BoundaryError as exc:
            raise StalePlanError("reconciliation_target_changed") from exc
        if (
            sha256_bytes(current_owned) != vault_owned_hash
            or sha256_bytes(current_full) != vault_full_hash
        ):
            raise StalePlanError("reconciliation_target_changed")
        if action == "manual_edit":
            self.repository.finish_sync(conflict_id, "awaiting_user_input")
            return ReconciliationResult(conflict_id, "awaiting_user_input")
        if action == "keep_database":
            replacement = (
                replace_managed_block_bytes(current_full, project_id, database_bytes)
                if snapshot_kind == "managed_block"
                else database_bytes
            )
            plan = self.create_plan(project_id, replacements={relative: replacement})
            return ReconciliationResult(
                conflict_id, "preview_required", plan_id=plan.id
            )
        if action != "adopt_vault":
            raise ValueError("unsupported_reconciliation_action")
        if snapshot_kind != "full" or relative.name not in {
            "规则.md",
            "经验.md",
            "任务状态.md",
        }:
            raise ValueError("vault_adoption_unsupported_target")
        database_entries = parse_aggregate_entries(database_bytes)
        vault_entries = parse_aggregate_entries(vault_owned_bytes)
        changed = [
            identifier
            for identifier in sorted(set(database_entries) | set(vault_entries))
            if database_entries.get(identifier) != vault_entries.get(identifier)
        ]
        if len(changed) != 1 or changed[0] not in vault_entries:
            raise ValueError("vault_edit_requires_one_changed_managed_entry")
        identifier = changed[0]
        kind = _kind_from_name(relative.name)
        active_by_id = {
            item.id: item
            for item in self.repository.list_project_knowledge(project_id)
            if item.status == "active"
        }
        original = active_by_id.get(identifier)
        if (
            original is None
            or original.knowledge_type is not kind
            or original.text != database_entries.get(identifier)
        ):
            raise StalePlanError("vault_adoption_identity_changed")
        identity = [
            conflict_id,
            identifier,
            sha256_bytes(vault_entries[identifier].encode("utf-8")),
        ]
        candidate_id = (
            "candidate-vault-"
            + hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()[:24]
        )
        candidate = Candidate(
            id=candidate_id,
            knowledge_type=kind,
            project_id=project_id,
            scope="project",
            proposed_text=vault_entries[identifier],
            evidence_ids=(),
            status=CandidateStatus.PENDING_REVIEW,
            extraction_confidence=0.0,
        )
        self.repository.save_manual_edit_candidate(
            candidate,
            relative_path=relative,
            content_hash=vault_full_hash,
            adoption=VaultAdoption(
                candidate_id=candidate.id,
                project_id=project_id,
                knowledge_id=original.id,
                original_version=original.version,
                original_text_hash=sha256_bytes(original.text.encode("utf-8")),
                relative_path=relative,
                vault_managed_hash=vault_owned_hash,
                vault_full_hash=vault_full_hash,
                authority_hash=str(payload["authority_hash"]),
                blocker=str(payload.get("sensitive_blocker", "")),
            ),
        )
        self.repository.finish_sync(conflict_id, "pending_review")
        return ReconciliationResult(
            conflict_id, "pending_review", candidate_id=candidate_id
        )

    def is_vault_adoption(self, candidate_id: str) -> bool:
        return self.repository.get_vault_adoption(candidate_id) is not None

    def accept_vault_adoption(
        self,
        candidate_id: str,
        *,
        text: str,
        actor: str,
        confidence: float,
        candidate_status: CandidateStatus,
    ) -> Knowledge:
        if actor != "user":
            raise ValueError("vault_adoption_actor_must_be_user")
        adoption = self.repository.get_vault_adoption(candidate_id)
        if adoption is None:
            raise KeyError("vault_adoption_not_found")
        relative = self._safe_relative(adoption.project_id, adoption.relative_path)
        target = self.vault_root / relative
        if not target.is_file():
            raise StalePlanError("vault_adoption_target_changed")
        current = target.read_bytes()
        current_full_hash = sha256_bytes(current)
        if (
            current_full_hash != adoption.vault_full_hash
            or sha256_bytes(current) != adoption.vault_managed_hash
            or projection_input_hash(
                self.repository.list_project_knowledge(adoption.project_id)
            )
            != adoption.authority_hash
        ):
            raise StalePlanError("vault_adoption_state_changed")
        try:
            return self.repository.accept_vault_adoption(
                candidate_id,
                text,
                actor,
                confidence,
                candidate_status=candidate_status,
                expected_authority_hash=adoption.authority_hash,
                managed_path=target,
                vault_managed_hash=adoption.vault_managed_hash,
                vault_full_hash=adoption.vault_full_hash,
                snapshot_kind="full",
                snapshot_event_id=f"vault-adoption:{candidate_id}",
            )
        except ValueError as exc:
            if str(exc).startswith("vault_adoption_"):
                raise StalePlanError("vault_adoption_state_changed") from exc
            raise

    def _load_plan(self, plan_id: str) -> MergePlan:
        job = self._get_job(plan_id)
        if job is None:
            raise KeyError("merge_plan_not_found")
        try:
            plan = load_persisted_merge_plan(job, plan_id)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MergeIntegrityError("merge_plan_invalid") from exc
        self._validate_unique_paths(plan)
        for path in _all_plan_paths(plan):
            self._safe_relative(plan.project_id, path)
        return plan

    def _get_job(self, job_id: str) -> SyncJob | None:
        try:
            return self.repository.get_sync_job(job_id)
        except sqlite3.Error as exc:
            raise ProjectionPersistenceError("merge_state_unavailable") from exc

    def _require_mapping(self, project_id: str) -> None:
        mappings = [
            item
            for item in self.repository.list_project_mappings()
            if item.obsidian_project == project_id
        ]
        if len(mappings) != 1:
            raise ValueError("project_mapping_invalid")

    def _safe_relative(self, project_id: str, path: Path) -> Path:
        path = Path(path)
        if path.is_absolute():
            try:
                path = path.relative_to(self.vault_root)
            except ValueError as exc:
                raise ValueError("merge_target_outside_vault") from exc
        if not path.parts or ".." in path.parts:
            raise ValueError("merge_target_outside_vault")
        _windows_path_identity(path)
        if len(path.parts) >= 2 and path.parts[0] == "项目":
            if path.parts[1] not in (project_id, "项目索引.md"):
                raise ValueError("merge_target_cross_project")
        root = self.vault_root.resolve(strict=True)
        current = self.vault_root
        for part in path.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("merge_target_symlink")
        try:
            (self.vault_root / path).resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise ValueError("merge_target_outside_vault") from exc
        return path

    def _absolute_from_state(self, project_id: str, path: Path) -> Path:
        relative = self._safe_relative(project_id, path)
        return self.vault_root / relative

    def _read(self, relative: Path) -> bytes:
        target = self.vault_root / relative
        return target.read_bytes() if target.exists() else b""

    def _read_state(self, relative: Path) -> tuple[bool, str, bytes]:
        target = self.vault_root / relative
        if not target.exists():
            return False, "missing", b""
        if not target.is_file():
            return True, "directory" if target.is_dir() else "other", b""
        return True, "file", target.read_bytes()

    @staticmethod
    def _validate_sensitive_plan_inputs(
        project_id: str,
        replacements: Mapping[Path, bytes],
        deletes: Sequence[Path],
        renames: Sequence[tuple[Path, Path]],
        conflicts: Sequence[str],
    ) -> None:
        redactor = Redactor()
        text_values = [project_id, *(str(item) for item in deletes), *conflicts]
        text_values.extend(str(path) for path in replacements)
        for source, target in renames:
            text_values.extend((str(source), str(target)))
        if any(redactor.contains_sensitive_value(value) for value in text_values):
            raise SensitiveMergeContentError("sensitive_merge_content")
        for content in replacements.values():
            try:
                text = bytes(content).decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise SensitiveMergeContentError("sensitive_merge_content") from exc
            if redactor.contains_sensitive_value(text):
                raise SensitiveMergeContentError("sensitive_merge_content")

    @staticmethod
    def _validate_existing_merge_bytes(content: bytes) -> None:
        if not content:
            return
        try:
            text = bytes(content).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise SensitiveMergeContentError("sensitive_merge_content") from None
        if Redactor().contains_sensitive_value(text):
            raise SensitiveMergeContentError("sensitive_merge_content")

    @staticmethod
    def _validate_unique_paths(plan: MergePlan) -> None:
        paths = [target.path_identity for target in plan.targets]
        paths.extend(item.path_identity for item in plan.deletes)
        for item in plan.renames:
            paths.extend((item.source_identity, item.target_identity))
        if len(paths) != len(set(paths)):
            raise MergeIntegrityError("merge_plan_paths_overlap")


def _kind_from_name(name: str) -> KnowledgeType:
    mapping = {
        "规则.md": KnowledgeType.RULE,
        "经验.md": KnowledgeType.LESSON,
        "任务状态.md": KnowledgeType.TASK_STATE,
    }
    try:
        return mapping[name]
    except KeyError as exc:
        raise ValueError("vault_adoption_requires_aggregate_entry") from exc


def _unified_diff(path: Path, before: bytes, after: bytes) -> str:
    return "".join(
        difflib.unified_diff(
            before.decode("utf-8", errors="replace").splitlines(keepends=True),
            after.decode("utf-8", errors="replace").splitlines(keepends=True),
            fromfile=path.as_posix(),
            tofile=path.as_posix(),
        )
    )


def _operation_id(identity: object) -> str:
    return (
        "merge-op-" + hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()[:24]
    )


def _windows_path_identity(path: Path) -> str:
    """Return the identity Windows would use, rejecting unsafe aliases."""

    reserved = {"con", "prn", "aux", "nul"}
    reserved.update(f"com{number}" for number in range(1, 10))
    reserved.update(f"lpt{number}" for number in range(1, 10))
    identities = []
    for raw_part in Path(path).parts:
        part = unicodedata.normalize("NFKC", raw_part)
        folded = part.casefold()
        stem = folded.split(".", 1)[0]
        if (
            not part
            or part.endswith((".", " "))
            or ":" in part
            or any(character in part for character in '<>"|?*')
            or stem in reserved
        ):
            raise ValueError("merge_target_windows_incompatible")
        identities.append(folded)
    if not identities:
        raise ValueError("merge_target_windows_incompatible")
    return "/".join(identities)


def canonical_merge_path_identity(path: Path) -> str:
    """Return the Windows-compatible identity used by persisted merge plans."""

    return _windows_path_identity(Path(path))


def _reconciliation_id(
    project_id: str,
    relative: Path,
    recorded_hash: str,
    vault_hash: str,
    authority_hash: str,
    database_bytes: bytes,
    snapshot_kind: str,
    vault_full_hash: str,
    vault_owned_hash: str,
) -> str:
    identity = [
        project_id,
        relative.as_posix(),
        recorded_hash,
        vault_hash,
        authority_hash,
        sha256_bytes(database_bytes),
        snapshot_kind,
        vault_full_hash,
        vault_owned_hash,
    ]
    return (
        "reconcile-" + hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()[:24]
    )


def _diagnostic_id(project_id: str, relative: Path, status: str) -> str:
    identity = [project_id, relative.as_posix(), status]
    return (
        f"reconcile-diagnostic-{status}-"
        + hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()[:24]
    )


def _all_plan_paths(plan: MergePlan) -> tuple[Path, ...]:
    values = [target.path for target in plan.targets]
    values.extend(item.path for item in plan.deletes)
    for item in plan.renames:
        values.extend((item.source, item.target))
    return tuple(values)


def _plan_json(plan: MergePlan) -> str:
    return _json(
        {
            "id": plan.id,
            "kind": "merge",
            "project_id": plan.project_id,
            "authority_hash": plan.authority_hash,
            "targets": [
                {
                    "path": item.path.as_posix(),
                    "path_identity": item.path_identity,
                    "input_exists": item.input_exists,
                    "input_kind": item.input_kind,
                    "input_hash": item.input_hash,
                    "output_base64": _b64(item.output_bytes),
                    "unified_diff": item.unified_diff,
                }
                for item in plan.targets
            ],
            "deletes": [
                {
                    "operation_id": item.operation_id,
                    "path": item.path.as_posix(),
                    "path_identity": item.path_identity,
                    "input_exists": item.input_exists,
                    "input_kind": item.input_kind,
                    "input_hash": item.input_hash,
                }
                for item in plan.deletes
            ],
            "renames": [
                {
                    "operation_id": item.operation_id,
                    "source": item.source.as_posix(),
                    "target": item.target.as_posix(),
                    "source_identity": item.source_identity,
                    "target_identity": item.target_identity,
                    "source_exists": item.source_exists,
                    "source_kind": item.source_kind,
                    "target_exists": item.target_exists,
                    "target_kind": item.target_kind,
                    "source_hash": item.source_hash,
                    "target_hash": item.target_hash,
                }
                for item in plan.renames
            ],
            "conflicts": [
                {
                    "operation_id": item.operation_id,
                    "description": item.description,
                }
                for item in plan.conflicts
            ],
        }
    )


def _plan_from_data(data: object) -> MergePlan:
    if not isinstance(data, dict) or data.get("kind") != "merge":
        raise ValueError("not a merge plan")
    return MergePlan(
        id=str(data["id"]),
        project_id=str(data["project_id"]),
        authority_hash=str(data["authority_hash"]),
        targets=tuple(
            MergeTarget(
                Path(item["path"]),
                str(item["path_identity"]),
                bool(item["input_exists"]),
                str(item["input_kind"]),
                str(item["input_hash"]),
                _unb64(item["output_base64"]),
                str(item["unified_diff"]),
            )
            for item in data["targets"]
        ),
        deletes=tuple(
            MergeDelete(
                str(item["operation_id"]),
                Path(item["path"]),
                str(item["path_identity"]),
                bool(item["input_exists"]),
                str(item["input_kind"]),
                str(item["input_hash"]),
            )
            for item in data["deletes"]
        ),
        renames=tuple(
            MergeRename(
                str(item["operation_id"]),
                Path(item["source"]),
                Path(item["target"]),
                str(item["source_identity"]),
                str(item["target_identity"]),
                bool(item["source_exists"]),
                str(item["source_kind"]),
                bool(item["target_exists"]),
                str(item["target_kind"]),
                str(item["source_hash"]),
                str(item["target_hash"]),
            )
            for item in data["renames"]
        ),
        conflicts=tuple(
            MergeConflict(str(item["operation_id"]), str(item["description"]))
            for item in data["conflicts"]
        ),
    )


def required_merge_operation_ids(plan: MergePlan) -> frozenset[str]:
    return frozenset(
        item.operation_id for item in (*plan.deletes, *plan.renames, *plan.conflicts)
    )


def load_persisted_merge_plan(job: SyncJob, plan_id: str) -> MergePlan:
    """Reload and fully authenticate the canonical plan stored in SQLite."""

    data = json.loads(job.plan_json)
    plan = _plan_from_data(data)
    if plan.id != plan_id or job.id != plan_id or job.project_id != plan.project_id:
        raise MergeIntegrityError("merge_plan_identity_mismatch")
    without_id = MergePlan(
        "",
        plan.project_id,
        plan.authority_hash,
        plan.targets,
        plan.deletes,
        plan.renames,
        plan.conflicts,
    )
    expected = (
        "merge-"
        + hashlib.sha256(_plan_json(without_id).encode("utf-8")).hexdigest()[:24]
    )
    if expected != plan.id or _plan_json(plan) != job.plan_json:
        raise MergeIntegrityError("merge_plan_integrity_mismatch")
    for target in plan.targets:
        if target.path_identity != _windows_path_identity(target.path):
            raise MergeIntegrityError("merge_plan_path_identity_mismatch")
    for item in plan.deletes:
        identity = [
            "delete",
            item.path_identity,
            item.input_exists,
            item.input_kind,
            item.input_hash,
        ]
        if item.path_identity != _windows_path_identity(
            item.path
        ) or item.operation_id != _operation_id(identity):
            raise MergeIntegrityError("merge_operation_identity_mismatch")
    for item in plan.renames:
        identity = [
            "rename",
            item.source_identity,
            item.target_identity,
            item.source_exists,
            item.source_kind,
            item.target_exists,
            item.target_kind,
            item.source_hash,
            item.target_hash,
        ]
        if (
            item.source_identity != _windows_path_identity(item.source)
            or item.target_identity != _windows_path_identity(item.target)
            or item.operation_id != _operation_id(identity)
        ):
            raise MergeIntegrityError("merge_operation_identity_mismatch")
    for item in plan.conflicts:
        if item.operation_id != _operation_id(["conflict", item.description]):
            raise MergeIntegrityError("merge_operation_identity_mismatch")
    identities = [target.path_identity for target in plan.targets]
    identities.extend(item.path_identity for item in plan.deletes)
    for item in plan.renames:
        identities.extend((item.source_identity, item.target_identity))
    if len(identities) != len(set(identities)):
        raise MergeIntegrityError("merge_plan_paths_overlap")
    return plan


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("invalid base64 value")
    return base64.b64decode(value.encode("ascii"), validate=True)
