"""Previewed, hash-bound integration with canonical Codex guidance."""

from __future__ import annotations

import codecs
import difflib
import hashlib
import locale
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


MANAGED_START = "<!-- agentretro:codex:start version=1 -->"
MANAGED_BODY = (
    "When a task depends on prior decisions, project history, user preferences, "
    "or current task state, run `retro brief` for that task and project. Do not "
    "scan the whole vault for self-contained tasks."
)
MANAGED_END = "<!-- agentretro:codex:end -->"
_START_PREFIX = "<!-- agentretro:codex:start"
_END_PREFIX = "<!-- agentretro:codex:end"


class GuidanceError(RuntimeError):
    """Base class for redaction-safe guidance diagnostics."""


class GuidancePathError(GuidanceError):
    def __init__(self) -> None:
        self.reason = "unsafe_guidance_path"
        super().__init__("canonical Codex guidance path is unsafe")


class GuidanceEncodingError(GuidanceError):
    def __init__(self) -> None:
        self.reason = "guidance_encoding_unsupported"
        super().__init__("canonical Codex guidance encoding is unsupported")


class GuidanceManagedBlockConflict(GuidanceError):
    def __init__(self) -> None:
        self.reason = "managed_block_conflict"
        super().__init__("managed guidance markers are malformed or manually edited")


class GuidanceOverrideConflict(GuidanceError):
    def __init__(self) -> None:
        self.reason = "codex_override_present"
        super().__init__("AGENTS.override.md shadows canonical guidance")


class GuidanceStalePreview(GuidanceError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        message = (
            "guidance target hash changed; create a new preview"
            if reason == "target_hash_changed"
            else "guidance preview is not current; create a new preview"
        )
        super().__init__(message)


class GuidanceWriteError(GuidanceError):
    def __init__(self, reason: str, backup_path: Path | None = None) -> None:
        self.reason = reason
        self.backup_path = backup_path
        super().__init__(f"Codex guidance write failed: {reason}")


class GuidanceRollbackRequired(GuidanceWriteError):
    def __init__(self, backup_path: Path | None) -> None:
        super().__init__("rollback_required", backup_path)


@dataclass(frozen=True)
class GuidancePreview:
    id: str
    action: str
    target: Path
    target_missing: bool
    target_hash: str | None
    managed_hash: str | None
    planned_hash: str | None
    diff: str
    backup_path: Path
    changed: bool
    _planned_bytes: bytes = field(repr=False)
    _planned_exists: bool = field(repr=False)


@dataclass(frozen=True)
class GuidanceResult:
    preview_id: str
    action: str
    status: str
    changed: bool
    target_hash: str | None
    backup_path: Path | None


@dataclass(frozen=True)
class _Decoded:
    raw: bytes
    text: str
    codec: str
    bom: bytes
    newline: str

    def encode(self, text: str) -> bytes:
        try:
            return text.encode(self.codec, errors="strict")
        except (LookupError, UnicodeEncodeError) as exc:
            raise GuidanceEncodingError() from exc

    def byte_offset(self, character_offset: int) -> int:
        return len(self.bom) + len(self.encode(self.text[:character_offset]))


@dataclass(frozen=True)
class _ManagedBlock:
    present: bool
    start: int = 0
    end: int = 0
    managed_hash: str | None = None


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _default_backup_writer(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=False)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != content:
        raise OSError("backup readback mismatch")


class CodexGuidance:
    """Modify only ``<effective-codex-home>/AGENTS.md`` after preview."""

    def __init__(
        self,
        codex_home: Path,
        backup_root: Path,
        *,
        preferred_encoding: Callable[[], str] = lambda: locale.getpreferredencoding(
            False
        ),
        replace: Callable[[Path, Path], None] = os.replace,
        readback: Callable[[Path], bytes] = Path.read_bytes,
        backup_writer: Callable[[Path, bytes], None] = _default_backup_writer,
    ) -> None:
        self._home_input = Path(codex_home).expanduser().absolute()
        self._backup_input = Path(backup_root).expanduser().absolute()
        self.preferred_encoding = preferred_encoding
        self.replace = replace
        self.readback = readback
        self.backup_writer = backup_writer
        self._generation = 0
        self._current_preview: GuidancePreview | None = None

    def preview(self) -> GuidancePreview:
        return self._preview("apply")

    def preview_remove(self) -> GuidancePreview:
        return self._preview("remove")

    def apply(self, preview_id: str) -> GuidanceResult:
        return self._execute(preview_id, "apply")

    def remove(self, preview_id: str) -> GuidanceResult:
        return self._execute(preview_id, "remove")

    def _preview(self, action: str) -> GuidancePreview:
        home, target, backup_root = self._canonical_paths()
        target_exists = target.exists()
        current = target.read_bytes() if target_exists else b""
        decoded = self._decode(current)
        block = self._managed_block(decoded)
        if action == "apply":
            planned, planned_exists = self._plan_apply(decoded, block)
        else:
            planned, planned_exists = self._plan_remove(decoded, block, target_exists)
        current_hash = _sha256(current) if target_exists else None
        planned_hash = _sha256(planned) if planned_exists else None
        changed = target_exists != planned_exists or current != planned
        self._generation += 1
        identity = "\0".join(
            (
                action,
                current_hash or "missing",
                planned_hash or "missing",
                str(self._generation),
                uuid.uuid4().hex,
            )
        ).encode("utf-8")
        preview_id = "guidance-" + _sha256(identity)[:24]
        backup_path = backup_root / preview_id / "AGENTS.md"
        preview = GuidancePreview(
            id=preview_id,
            action=action,
            target=target,
            target_missing=not target_exists,
            target_hash=current_hash,
            managed_hash=block.managed_hash,
            planned_hash=planned_hash,
            diff=self._diff(decoded, planned, planned_exists),
            backup_path=backup_path,
            changed=changed,
            _planned_bytes=planned,
            _planned_exists=planned_exists,
        )
        self._current_preview = preview
        return preview

    def _execute(self, preview_id: str, action: str) -> GuidanceResult:
        preview = self._current_preview
        if preview is None or preview.id != preview_id or preview.action != action:
            raise GuidanceStalePreview("preview_not_current")
        _, target, _ = self._canonical_paths()
        override = target.with_name("AGENTS.override.md")
        if override.exists() or override.is_symlink():
            raise GuidanceOverrideConflict()
        target_exists = target.exists()
        current = target.read_bytes() if target_exists else b""
        current_hash = _sha256(current) if target_exists else None
        if (
            target_exists == preview.target_missing
            or current_hash != preview.target_hash
        ):
            raise GuidanceStalePreview("target_hash_changed")
        decoded = self._decode(current)
        block = self._managed_block(decoded)
        if block.managed_hash != preview.managed_hash:
            raise GuidanceStalePreview("target_hash_changed")
        if not preview.changed:
            self._current_preview = None
            return GuidanceResult(
                preview_id=preview.id,
                action=action,
                status="unchanged",
                changed=False,
                target_hash=current_hash,
                backup_path=None,
            )

        backup_path: Path | None = None
        if target_exists:
            backup_path = preview.backup_path
            try:
                self.backup_writer(backup_path, current)
            except Exception as exc:
                try:
                    backup_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise GuidanceWriteError("backup_failed") from exc

        replaced = False
        try:
            if preview._planned_exists:
                self._atomic_replace(target, preview._planned_bytes)
            else:
                target.unlink()
            replaced = True
            actual = self.readback(target) if preview._planned_exists else b""
            if (preview._planned_exists and actual != preview._planned_bytes) or (
                not preview._planned_exists and target.exists()
            ):
                raise OSError("readback mismatch")
            if preview._planned_exists:
                verified = self._managed_block(self._decode(actual)).present
                if action == "apply" and not verified:
                    raise OSError("managed block readback mismatch")
                if action == "remove" and verified:
                    raise OSError("managed block removal mismatch")
        except Exception as exc:
            reason = "readback_failed" if replaced else "replace_failed"
            if replaced:
                try:
                    self._restore(target, current, target_exists)
                except Exception as restore_exc:
                    raise GuidanceRollbackRequired(backup_path) from restore_exc
            raise GuidanceWriteError(reason, backup_path) from exc

        self._current_preview = None
        return GuidanceResult(
            preview_id=preview.id,
            action=action,
            status="applied" if action == "apply" else "removed",
            changed=True,
            target_hash=(
                _sha256(preview._planned_bytes) if preview._planned_exists else None
            ),
            backup_path=backup_path,
        )

    def _canonical_paths(self) -> tuple[Path, Path, Path]:
        if (
            not self._home_input.exists()
            or not self._home_input.is_dir()
            or _has_symlink_component(self._home_input)
            or _has_symlink_component(self._backup_input)
        ):
            raise GuidancePathError()
        home = self._home_input.resolve(strict=True)
        target_input = self._home_input / "AGENTS.md"
        if target_input.is_symlink() or (
            target_input.exists() and not target_input.is_file()
        ):
            raise GuidancePathError()
        target = target_input.resolve(strict=False)
        try:
            target.relative_to(home)
        except ValueError as exc:
            raise GuidancePathError() from exc
        if target.parent != home or target.name != "AGENTS.md":
            raise GuidancePathError()
        backup_root = self._backup_input.resolve(strict=False)
        return home, target, backup_root

    def _decode(self, raw: bytes) -> _Decoded:
        bom = b""
        codec = "utf-8"
        payload = raw
        if raw.startswith(codecs.BOM_UTF8):
            bom = codecs.BOM_UTF8
            payload = raw[len(bom) :]
        elif raw.startswith(codecs.BOM_UTF16_LE):
            bom = codecs.BOM_UTF16_LE
            codec = "utf-16-le"
            payload = raw[len(bom) :]
        elif raw.startswith(codecs.BOM_UTF16_BE):
            bom = codecs.BOM_UTF16_BE
            codec = "utf-16-be"
            payload = raw[len(bom) :]
        else:
            try:
                text = payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                try:
                    codec = self.preferred_encoding()
                    text = payload.decode(codec, errors="strict")
                except (LookupError, UnicodeDecodeError) as exc:
                    raise GuidanceEncodingError() from exc
            return _Decoded(raw, text, codec, bom, _newline(text))
        try:
            text = payload.decode(codec, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            raise GuidanceEncodingError() from exc
        return _Decoded(raw, text, codec, bom, _newline(text))

    def _managed_block(self, decoded: _Decoded) -> _ManagedBlock:
        text = decoded.text
        prefix_starts = text.count(_START_PREFIX)
        prefix_ends = text.count(_END_PREFIX)
        exact_starts = text.count(MANAGED_START)
        exact_ends = text.count(MANAGED_END)
        if prefix_starts == prefix_ends == exact_starts == exact_ends == 0:
            return _ManagedBlock(False)
        if (
            prefix_starts != 1
            or prefix_ends != 1
            or exact_starts != 1
            or exact_ends != 1
        ):
            raise GuidanceManagedBlockConflict()
        start = text.index(MANAGED_START)
        marker_end = text.index(MANAGED_END) + len(MANAGED_END)
        if marker_end <= start:
            raise GuidanceManagedBlockConflict()
        starts_on_line = start == 0 or text[start - 1] in {"\r", "\n"}
        ends_on_line = marker_end == len(text) or text[marker_end] in {"\r", "\n"}
        if not starts_on_line or not ends_on_line:
            raise GuidanceManagedBlockConflict()
        expected = _managed_text(decoded.newline)
        if text[start:marker_end] != expected:
            raise GuidanceManagedBlockConflict()
        end = marker_end
        if text.startswith(decoded.newline, end):
            end += len(decoded.newline)
        raw_start = decoded.byte_offset(start)
        raw_end = decoded.byte_offset(end)
        return _ManagedBlock(
            True,
            start=raw_start,
            end=raw_end,
            managed_hash=_sha256(decoded.raw[raw_start:raw_end]),
        )

    def _plan_apply(
        self, decoded: _Decoded, block: _ManagedBlock
    ) -> tuple[bytes, bool]:
        if block.present:
            return decoded.raw, True
        addition = decoded.encode(_managed_text(decoded.newline) + decoded.newline)
        if not decoded.raw:
            return decoded.bom + addition, True
        newline_index = decoded.text.find(decoded.newline)
        if newline_index >= 0:
            insertion_character = newline_index + len(decoded.newline)
            insertion = decoded.byte_offset(insertion_character)
            return decoded.raw[:insertion] + addition + decoded.raw[insertion:], True
        insertion = len(decoded.bom)
        return decoded.raw[:insertion] + addition + decoded.raw[insertion:], True

    @staticmethod
    def _plan_remove(
        decoded: _Decoded, block: _ManagedBlock, target_exists: bool
    ) -> tuple[bytes, bool]:
        if not block.present:
            return decoded.raw, target_exists
        planned = decoded.raw[: block.start] + decoded.raw[block.end :]
        return planned, bool(planned)

    def _diff(self, current: _Decoded, planned: bytes, planned_exists: bool) -> str:
        if current.raw == planned and planned_exists == bool(
            current.raw or current.text
        ):
            return ""
        planned_text = self._decode(planned).text if planned_exists else ""
        return "".join(
            difflib.unified_diff(
                current.text.splitlines(keepends=True),
                planned_text.splitlines(keepends=True),
                fromfile="AGENTS.md (current)",
                tofile="AGENTS.md (planned)",
                lineterm="\n",
            )
        )

    def _atomic_replace(self, target: Path, content: bytes) -> None:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".agentretro-", suffix=".tmp", dir=target.parent
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

    def _restore(self, target: Path, original: bytes, existed: bool) -> None:
        if existed:
            self._atomic_replace(target, original)
            if target.read_bytes() != original:
                raise OSError("restore readback mismatch")
            return
        target.unlink(missing_ok=True)
        if target.exists():
            raise OSError("created target removal failed")


def discover_managed_instruction(codex_home: Path) -> bool:
    """Read only canonical ``AGENTS.md`` and recognize one exact v1 block."""

    home_input = Path(codex_home).expanduser().absolute()
    try:
        if not home_input.is_dir() or home_input.is_symlink():
            return False
        home = home_input.resolve(strict=True)
        target_input = home_input / "AGENTS.md"
        if target_input.is_symlink():
            return False
        target = target_input.resolve(strict=False)
        if target.parent != home or not target.is_file():
            return False
        raw = target.read_bytes()
        helper = CodexGuidance(home, home / ".unused-agentretro-backups")
        return helper._managed_block(helper._decode(raw)).present
    except (GuidanceError, OSError):
        return False


def _managed_text(newline: str) -> str:
    return newline.join((MANAGED_START, MANAGED_BODY, MANAGED_END))


def _newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    if "\r" in text:
        return "\r"
    return "\n"


def _has_symlink_component(path: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent
