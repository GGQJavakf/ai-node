"""Deterministic purge manifest, containment, and recovery mechanics."""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from agent_retro.domain.models import ProjectionStatus, PurgeStatus


@dataclass(frozen=True)
class ManifestCopy:
    location_kind: str
    locator: str
    content: bytes
    path: Path | None = None

    @property
    def expected_hash(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def contains_any(content: bytes, markers: Sequence[bytes]) -> bool:
    return any(marker in content for marker in markers)


def has_sha256_window(content: bytes, expected_hash: str, length: int) -> bool:
    if length <= 0 or len(expected_hash) != 64 or len(content) < length:
        return False
    return any(
        hashlib.sha256(content[offset : offset + length]).hexdigest() == expected_hash
        for offset in range(len(content) - length + 1)
    )


def has_any_fingerprint(
    content: bytes, fingerprints: Sequence[tuple[str, int]]
) -> bool:
    return any(
        has_sha256_window(content, marker_hash, length)
        for marker_hash, length in fingerprints
    )


def file_manifest(copies: Sequence[ManifestCopy]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (copy.location_kind, copy.locator, copy.expected_hash)
            for copy in copies
            if copy.path is not None
        )
    )


def purge_plan_id(knowledge_id: str, copies: Sequence[ManifestCopy]) -> str:
    manifest = [
        [item.location_kind, item.locator, item.expected_hash] for item in copies
    ]
    identity = json.dumps(
        [knowledge_id, manifest],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = (
        urlsafe_b64encode(knowledge_id.encode("utf-8")).decode("ascii").rstrip("=")
    )
    return "purge-v1-" + encoded + "-" + hashlib.sha256(identity).hexdigest()


def knowledge_id_from_plan(plan_id: str) -> str:
    if not plan_id.startswith("purge-v1-"):
        raise ValueError("purge plan identity is malformed")
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
        raise ValueError("purge plan identity is malformed") from exc
    if not knowledge_id:
        raise ValueError("purge plan identity is malformed")
    return knowledge_id


def build_purge_operations(
    plan_id: str,
    copies: Sequence[ManifestCopy],
    operation_factory: Callable[..., Any],
) -> tuple[Any, ...]:
    counts: dict[str, int] = {}
    operations = []
    for item in copies:
        ordinal = counts.get(item.location_kind, 0) + 1
        counts[item.location_kind] = ordinal
        location = f"{item.location_kind}:{ordinal}"
        operation_id = hashlib.sha256(
            (plan_id + item.location_kind + location + item.expected_hash).encode("utf-8")
        ).hexdigest()
        operations.append(
            operation_factory(
                id=operation_id,
                location_kind=item.location_kind,
                location=location,
                expected_hash=item.expected_hash,
            )
        )
    return tuple(operations)


def operation_kind_counts(operations: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations:
        counts[operation.location_kind] = counts.get(operation.location_kind, 0) + 1
    return counts


def recovery_operation_class(operation: Any) -> str:
    """Classify one journal row without performing a recovery effect."""

    if operation.status == "completed":
        return "completed"
    if operation.location_kind.startswith("sqlite_"):
        return "database_residual"
    return "file_recovery"


def terminal_purge_status(residual_kinds: Sequence[str]) -> PurgeStatus:
    """Select the only legal terminal transition after residual verification."""

    if residual_kinds:
        return PurgeStatus.PURGE_INCOMPLETE
    return PurgeStatus.PURGED


def removal_ranges(content: bytes, markers: Sequence[bytes]) -> list[list[int]]:
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


def remove_ranges(content: bytes, ranges: Sequence[Sequence[int]]) -> bytes:
    cursor = 0
    chunks: list[bytes] = []
    for start, length in ranges:
        chunks.append(content[cursor:start])
        cursor = start + length
    chunks.append(content[cursor:])
    return b"".join(chunks)


def recovery_payload(copy: ManifestCopy, markers: Sequence[bytes]) -> str:
    ranges = removal_ranges(copy.content, markers)
    after = remove_ranges(copy.content, ranges)
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


def parse_recovery_payload(value: str) -> tuple[str, str, tuple[tuple[int, int], ...]]:
    try:
        payload = json.loads(value)
        action = str(payload["action"])
        after_hash = str(payload["after_hash"])
        ranges = tuple(
            (int(item[0]), int(item[1])) for item in payload.get("ranges", ())
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("purge recovery payload is invalid") from exc
    if action not in {"delete", "remove_ranges"} or len(after_hash) != 64:
        raise ValueError("purge recovery payload is invalid")
    return action, after_hash, ranges


def recovered_bytes(
    before: bytes,
    ranges: Sequence[tuple[int, int]],
    expected_after_hash: str,
) -> bytes:
    cursor = 0
    chunks: list[bytes] = []
    for start, length in ranges:
        if start < cursor or length <= 0 or start + length > len(before):
            raise ValueError("purge recovery ranges are invalid")
        chunks.append(before[cursor:start])
        cursor = start + length
    chunks.append(before[cursor:])
    after = b"".join(chunks)
    if hashlib.sha256(after).hexdigest() != expected_after_hash:
        raise ValueError("purge recovery result is invalid")
    return after


def cleaned_file_action(
    copy: ManifestCopy,
    before: bytes,
    expected_hash: str,
    markers: Sequence[bytes],
) -> tuple[str, bytes]:
    if not contains_any(before, markers):
        return "none", before
    if hashlib.sha256(before).hexdigest() != expected_hash:
        raise ValueError("registered purge copy changed after preflight")
    after = before
    for marker in markers:
        after = after.replace(marker, b"")
    if copy.location_kind.endswith("_backup") or not after:
        return "delete", b""
    return "replace", after


def updated_tombstone(
    tombstone_json: str,
    status: PurgeStatus,
    residual_count: int,
    updated_at: str,
) -> str:
    payload = json.loads(tombstone_json)
    payload["updated_at"] = updated_at
    payload["status"] = status.value
    payload["residual_count"] = residual_count
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def is_registered_identity(locator: str) -> bool:
    digest = locator.removeprefix("registered-")
    return (
        locator.startswith("registered-")
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def validated_root(
    root_value: Path, label: str, error_type: type[Exception]
) -> Path:
    root = Path(root_value)
    if root.is_symlink():
        raise error_type(f"{label} root must not be a symlink")
    if not root.exists():
        return root.resolve()
    if not root.is_dir():
        raise error_type(f"{label} root must be a directory")
    return root.resolve(strict=True)


def configured_explicit_root(
    configured: Path | None,
    paths: Sequence[Path],
    error_type: type[Exception],
) -> Path | None:
    if configured is not None:
        root = Path(configured)
    elif not paths:
        return None
    else:
        parents = {Path(path).parent.resolve() for path in paths}
        if len(parents) != 1:
            raise error_type("registered purge paths require one explicit root")
        root = parents.pop()
    resolved_root = root.resolve()
    for path in paths:
        try:
            Path(path).resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise error_type(
                "registered purge path escapes its configured root"
            ) from exc
    return root


def validated_child(
    root: Path, target: Path, label: str, error_type: type[Exception]
) -> Path:
    current = target
    while current != root and current != current.parent:
        if current.is_symlink():
            raise error_type(f"{label} registration contains a symlink")
        current = current.parent
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise error_type(f"{label} registration escapes its configured root") from exc
    if not resolved.is_file():
        raise error_type(f"{label} registration must be a file")
    return resolved


def validate_absent_child(
    root: Path, target: Path, label: str, error_type: type[Exception]
) -> None:
    try:
        parent = target.parent.resolve(strict=True)
        parent.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise error_type(f"{label} registration escapes its configured root") from exc
    current = target.parent
    while current != root and current != current.parent:
        if current.is_symlink():
            raise error_type(f"{label} registration contains a symlink")
        current = current.parent


def registered_identity(
    kind: str,
    root_value: Path,
    target: Path,
    error_type: type[Exception],
) -> str:
    root = validated_root(root_value, kind, error_type)
    resolved = validated_child(root, target, kind, error_type)
    normalized = unicodedata.normalize("NFC", resolved.relative_to(root).as_posix())
    if os.name == "nt":
        normalized = normalized.casefold()
    digest = hashlib.sha256((kind + "\0" + normalized).encode("utf-8")).hexdigest()
    return "registered-" + digest


def safe_projection_token(value: object) -> str:
    token = str(value)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if 0 < len(token) <= 128 and all(character in allowed for character in token):
        return token
    return ""


def safe_projection_warning(value: object) -> str:
    warning = str(value)
    if warning in {"", "RETRO_SYNC_PENDING", "RETRO_ROLLBACK_REQUIRED"}:
        return warning
    return "RETRO_SYNC_PENDING"


def safe_projection_command(value: object, status: ProjectionStatus) -> str:
    command = str(value)
    if command == "retro doctor --repair-sync":
        return command
    prefix = "retro sync retry "
    if command.startswith(prefix) and safe_projection_token(command[len(prefix) :]):
        return command
    return "" if status is ProjectionStatus.SYNCED else "retro doctor --repair-sync"


def safe_projection_reason(value: object, status: ProjectionStatus) -> str:
    reason = str(value)
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"
    if not reason:
        return ""
    if len(reason) <= 64 and all(character in allowed for character in reason):
        return reason
    return "" if status is ProjectionStatus.SYNCED else "projection_pending"
