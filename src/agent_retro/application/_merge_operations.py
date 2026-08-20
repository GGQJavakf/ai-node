"""Pure semantic-merge mechanics used by :class:`MergeService`."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def decode_bytes(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("invalid base64 value")
    return base64.b64decode(value.encode("ascii"), validate=True)


def serialize_merge_plan(plan: Any) -> str:
    """Serialize the stable, hash-bound merge-plan journal representation."""

    return json_text(
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
                    "output_base64": encode_bytes(item.output_bytes),
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


def deserialize_merge_plan(
    data: object,
    *,
    plan_factory: Callable[..., Any],
    target_factory: Callable[..., Any],
    delete_factory: Callable[..., Any],
    rename_factory: Callable[..., Any],
    conflict_factory: Callable[..., Any],
) -> Any:
    """Decode a plan through caller-supplied public model constructors."""

    if not isinstance(data, dict) or data.get("kind") != "merge":
        raise ValueError("not a merge plan")
    return plan_factory(
        id=str(data["id"]),
        project_id=str(data["project_id"]),
        authority_hash=str(data["authority_hash"]),
        targets=tuple(
            target_factory(
                Path(item["path"]),
                str(item["path_identity"]),
                bool(item["input_exists"]),
                str(item["input_kind"]),
                str(item["input_hash"]),
                decode_bytes(item["output_base64"]),
                str(item["unified_diff"]),
            )
            for item in data["targets"]
        ),
        deletes=tuple(
            delete_factory(
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
            rename_factory(
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
            conflict_factory(str(item["operation_id"]), str(item["description"]))
            for item in data["conflicts"]
        ),
    )


def all_plan_paths(plan: Any) -> tuple[Path, ...]:
    values = [target.path for target in plan.targets]
    values.extend(item.path for item in plan.deletes)
    for item in plan.renames:
        values.extend((item.source, item.target))
    return tuple(values)


def required_operation_ids(plan: Any) -> frozenset[str]:
    required = {item.operation_id for item in plan.deletes}
    required.update(item.operation_id for item in plan.renames)
    required.update(item.operation_id for item in plan.conflicts)
    return frozenset(required)


def diagnostic_reason(conflict_id: str) -> str:
    for reason in (
        "managed_snapshot_unavailable",
        "managed_snapshot_invalid",
        "managed_snapshot_sensitive",
        "managed_boundary_invalid",
    ):
        if conflict_id.startswith(f"reconcile-diagnostic-{reason}-"):
            return reason
    return ""


def parse_reconciliation_payload(plan_json: str, conflict_id: str) -> dict[str, Any]:
    """Parse and authenticate the canonical reconciliation journal envelope."""

    try:
        payload = json.loads(plan_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("reconciliation_plan_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "reconciliation"
        or payload.get("id") != conflict_id
        or json_text(payload) != plan_json
    ):
        raise ValueError("reconciliation_plan_invalid")
    return payload


@dataclass(frozen=True)
class ReconciliationInputs:
    project_id: str
    relative: Path
    target: Path
    database_bytes: bytes
    vault_owned_bytes: bytes
    snapshot_kind: str
    vault_full_hash: str
    vault_owned_hash: str
    authority_hash: str
    recorded_hash: str
    vault_hash: str
    sensitive_blocker: str


def reconciliation_inputs(
    payload: dict[str, Any],
    *,
    safe_relative: Callable[[str, Path], Path],
    vault_root: Path,
) -> ReconciliationInputs:
    project_id = str(payload["project_id"])
    relative = safe_relative(project_id, Path(payload["path"]))
    return ReconciliationInputs(
        project_id=project_id,
        relative=relative,
        target=vault_root / relative,
        database_bytes=decode_bytes(payload["database_base64"]),
        vault_owned_bytes=decode_bytes(payload["vault_base64"]),
        snapshot_kind=str(payload["snapshot_kind"]),
        vault_full_hash=str(payload["vault_full_hash"]),
        vault_owned_hash=str(payload["vault_owned_hash"]),
        authority_hash=str(payload["authority_hash"]),
        recorded_hash=str(payload["recorded_hash"]),
        vault_hash=str(payload["vault_hash"]),
        sensitive_blocker=str(payload.get("sensitive_blocker", "")),
    )


def changed_managed_entry(
    database_entries: dict[str, str], vault_entries: dict[str, str]
) -> str:
    changed = [
        identifier
        for identifier in sorted(set(database_entries) | set(vault_entries))
        if database_entries.get(identifier) != vault_entries.get(identifier)
    ]
    if len(changed) != 1 or changed[0] not in vault_entries:
        raise ValueError("vault_edit_requires_one_changed_managed_entry")
    return changed[0]


def vault_candidate_id(
    conflict_id: str, identifier: str, proposed_text: str
) -> str:
    identity = [
        conflict_id,
        identifier,
        hashlib.sha256(proposed_text.encode("utf-8")).hexdigest(),
    ]
    return "candidate-vault-" + hashlib.sha256(
        json_text(identity).encode("utf-8")
    ).hexdigest()[:24]
