from __future__ import annotations

import codecs
import os
from pathlib import Path

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.infrastructure.codex_guidance import (
    MANAGED_BODY,
    MANAGED_END,
    MANAGED_START,
    CodexGuidance,
    GuidanceEncodingError,
    GuidanceManagedBlockConflict,
    GuidanceOverrideConflict,
    GuidancePathError,
    GuidanceRollbackRequired,
    GuidanceStalePreview,
    GuidanceWriteError,
    discover_managed_instruction,
)


def _snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _home(tmp_path: Path) -> tuple[Path, Path, Path]:
    codex_home = tmp_path / ".codex"
    backup_root = tmp_path / "state" / "backups"
    codex_home.mkdir()
    return codex_home, backup_root, codex_home / "AGENTS.md"


def test_preview_existing_and_missing_is_complete_and_absolutely_non_writing(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    before = _snapshot(tmp_path)

    missing = CodexGuidance(codex_home, backup_root).preview()

    assert _snapshot(tmp_path) == before
    assert missing.target == target.resolve(strict=False)
    assert missing.target_missing is True
    assert missing.target_hash is None
    assert missing.action == "apply"
    assert missing.diff.startswith("--- AGENTS.md (current)\n+++ AGENTS.md (planned)\n")
    assert MANAGED_START in missing.diff and MANAGED_END in missing.diff
    assert missing.backup_path.is_relative_to(backup_root.resolve(strict=False))
    assert not backup_root.exists()

    target.write_text("user rules\n", encoding="utf-8")
    before_existing = _snapshot(tmp_path)
    existing = CodexGuidance(codex_home, backup_root).preview()

    assert _snapshot(tmp_path) == before_existing
    assert existing.target_missing is False
    assert len(existing.target_hash or "") == 64
    assert " user rules" in existing.diff
    assert not backup_root.exists()


def test_preview_remove_is_non_writing_and_no_block_is_stable(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_bytes(b"user rules\r\n")
    before = _snapshot(tmp_path)
    guidance = CodexGuidance(codex_home, backup_root)

    preview = guidance.preview_remove()
    result = guidance.remove(preview.id)

    assert preview.action == "remove"
    assert preview.changed is False
    assert preview.diff == ""
    assert result.changed is False
    assert result.status == "unchanged"
    assert _snapshot(tmp_path) == before
    assert not backup_root.exists()


def test_apply_and_remove_preserve_every_outside_byte_and_keep_backup(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    original = b"before\r\nafter\r\n"
    target.write_bytes(original)
    guidance = CodexGuidance(codex_home, backup_root)

    applied = guidance.apply(guidance.preview().id)
    after_apply = target.read_bytes()

    assert applied.status == "applied"
    assert applied.changed is True
    assert applied.backup_path is not None
    assert applied.backup_path.read_bytes() == original
    assert after_apply != original
    assert after_apply.startswith(b"before\r\n")
    assert after_apply.endswith(b"after\r\n")
    assert MANAGED_START.encode() in after_apply
    assert b"\r\n" in after_apply
    assert discover_managed_instruction(codex_home) is True

    removed = guidance.remove(guidance.preview_remove().id)

    assert removed.status == "removed"
    assert target.read_bytes() == original
    assert applied.backup_path.exists()
    assert removed.backup_path is not None and removed.backup_path.exists()
    assert removed.backup_path.read_bytes() == after_apply


def test_missing_file_is_created_only_by_matching_apply_and_remove_restores_absence(
    tmp_path,
):
    codex_home, backup_root, target = _home(tmp_path)
    guidance = CodexGuidance(codex_home, backup_root)
    preview = guidance.preview()

    assert not target.exists()
    result = guidance.apply(preview.id)

    assert result.status == "applied"
    assert target.exists()
    assert result.backup_path is None
    assert discover_managed_instruction(codex_home)

    guidance.remove(guidance.preview_remove().id)

    assert not target.exists()


def test_override_blocks_apply_and_remove_without_touching_either_file(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_text("user rules\n", encoding="utf-8")
    guidance = CodexGuidance(codex_home, backup_root)
    apply_preview = guidance.preview()
    override = codex_home / "AGENTS.override.md"
    override.write_text("shadow", encoding="utf-8")
    before = _snapshot(tmp_path)

    with pytest.raises(GuidanceOverrideConflict):
        guidance.apply(apply_preview.id)
    with pytest.raises(GuidanceOverrideConflict):
        guidance.remove(guidance.preview_remove().id)

    assert _snapshot(tmp_path) == before
    assert not backup_root.exists()


def test_preview_id_is_in_memory_current_and_hash_bound(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_text("one\n", encoding="utf-8")
    guidance = CodexGuidance(codex_home, backup_root)
    first = guidance.preview()
    second = guidance.preview()

    assert first.id != second.id
    with pytest.raises(GuidanceStalePreview, match="preview"):
        guidance.apply(first.id)

    target.write_text("two\n", encoding="utf-8")
    with pytest.raises(GuidanceStalePreview, match="hash"):
        guidance.apply(second.id)

    restarted = CodexGuidance(codex_home, backup_root)
    with pytest.raises(GuidanceStalePreview, match="preview"):
        restarted.apply(second.id)
    assert target.read_text(encoding="utf-8") == "two\n"
    assert not backup_root.exists()


def test_cross_process_apply_remove_reapply_uses_unique_retained_backups(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    original = b"user rules\n"
    target.write_bytes(original)

    first = CodexGuidance(codex_home, backup_root)
    first_preview = first.preview()
    first_result = first.apply(first_preview.id)

    second = CodexGuidance(codex_home, backup_root)
    remove_preview = second.preview_remove()
    second.remove(remove_preview.id)
    assert target.read_bytes() == original

    before_reapply_preview = _snapshot(tmp_path)
    third = CodexGuidance(codex_home, backup_root)
    third_preview = third.preview()
    assert _snapshot(tmp_path) == before_reapply_preview
    third_result = third.apply(third_preview.id)

    assert discover_managed_instruction(codex_home)
    assert first_result.backup_path is not None
    assert third_result.backup_path is not None
    assert first_result.backup_path != third_result.backup_path
    assert first_result.backup_path.read_bytes() == original
    assert third_result.backup_path.read_bytes() == original


@pytest.mark.parametrize(
    "content",
    [
        f"{MANAGED_START}\nchanged manually\n{MANAGED_END}\n",
        f"{MANAGED_START}\n{MANAGED_BODY}\n{MANAGED_START}\n{MANAGED_END}\n{MANAGED_END}\n",
        f"{MANAGED_START}\n{MANAGED_BODY}\n{MANAGED_END}\n{MANAGED_START}\n{MANAGED_BODY}\n{MANAGED_END}\n",
        f"{MANAGED_START}\n{MANAGED_BODY}\n",
        f"{MANAGED_BODY}\n{MANAGED_END}\n",
        f"inline {MANAGED_START}\n{MANAGED_BODY}\n{MANAGED_END}\n",
        f"{MANAGED_START}\n{MANAGED_BODY}\n{MANAGED_END} inline\n",
    ],
)
def test_manual_duplicate_nested_or_malformed_markers_fail_closed(tmp_path, content):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_text(content, encoding="utf-8")
    before = target.read_bytes()
    guidance = CodexGuidance(codex_home, backup_root)

    with pytest.raises(GuidanceManagedBlockConflict):
        guidance.preview()
    with pytest.raises(GuidanceManagedBlockConflict):
        guidance.preview_remove()

    assert target.read_bytes() == before
    assert not backup_root.exists()


def test_target_symlink_escape_is_rejected_before_read_or_write(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(GuidancePathError):
        CodexGuidance(codex_home, backup_root).preview()

    assert outside.read_text(encoding="utf-8") == "outside"
    assert not backup_root.exists()


def test_canonical_target_must_be_a_regular_file_or_missing(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.mkdir()

    with pytest.raises(GuidancePathError):
        CodexGuidance(codex_home, backup_root).preview()

    assert target.is_dir()
    assert not backup_root.exists()


def test_symlinked_codex_home_or_backup_parent_is_rejected(tmp_path):
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    linked_home = tmp_path / "linked-home"
    try:
        linked_home.symlink_to(real_home, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(GuidancePathError):
        CodexGuidance(linked_home, tmp_path / "backups").preview()

    codex_home = tmp_path / "safe-home"
    codex_home.mkdir()
    real_backups = tmp_path / "real-backups"
    real_backups.mkdir()
    linked_backups = tmp_path / "linked-backups"
    linked_backups.symlink_to(real_backups, target_is_directory=True)
    with pytest.raises(GuidancePathError):
        CodexGuidance(codex_home, linked_backups).preview()


def test_symlinked_parent_of_codex_home_is_rejected(tmp_path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    (real_parent / ".codex").mkdir()
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(GuidancePathError):
        CodexGuidance(linked_parent / ".codex", tmp_path / "backups").preview()


def test_concurrent_instance_preview_loses_hash_fence_after_first_apply(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_text("rules\n", encoding="utf-8")
    first = CodexGuidance(codex_home, backup_root / "first")
    second = CodexGuidance(codex_home, backup_root / "second")
    first_preview = first.preview()
    second_preview = second.preview()

    first.apply(first_preview.id)
    after_first = target.read_bytes()

    with pytest.raises(GuidanceStalePreview, match="hash"):
        second.apply(second_preview.id)
    assert target.read_bytes() == after_first


def test_fresh_repeated_apply_and_remove_are_idempotent_without_new_backup(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_text("rules\n", encoding="utf-8")
    guidance = CodexGuidance(codex_home, backup_root)
    guidance.apply(guidance.preview().id)
    backups_after_apply = _snapshot(backup_root)

    repeated_apply = guidance.apply(guidance.preview().id)

    assert repeated_apply.status == "unchanged"
    assert _snapshot(backup_root) == backups_after_apply

    guidance.remove(guidance.preview_remove().id)
    backups_after_remove = _snapshot(backup_root)
    repeated_remove = guidance.remove(guidance.preview_remove().id)

    assert repeated_remove.status == "unchanged"
    assert _snapshot(backup_root) == backups_after_remove


@pytest.mark.parametrize(
    ("original", "preferred"),
    [
        (codecs.BOM_UTF8 + "before\nafter\n".encode(), "utf-8"),
        (codecs.BOM_UTF16_LE + "before\r\nafter\r\n".encode("utf-16-le"), "utf-8"),
        (codecs.BOM_UTF16_BE + "before\r\nafter\r\n".encode("utf-16-be"), "utf-8"),
        ("before\nafter\n".encode(), "utf-8"),
        ("before café\r\nafter\r\n".encode("cp1252"), "cp1252"),
    ],
)
def test_encoding_newline_and_outside_bytes_round_trip(tmp_path, original, preferred):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_bytes(original)
    guidance = CodexGuidance(
        codex_home,
        backup_root,
        preferred_encoding=lambda: preferred,
    )

    guidance.apply(guidance.preview().id)
    guidance.remove(guidance.preview_remove().id)

    assert target.read_bytes() == original


def test_undecodable_target_fails_without_any_write(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_bytes(b"\xff\xfe\xfd")
    before = _snapshot(tmp_path)

    with pytest.raises(GuidanceEncodingError):
        CodexGuidance(
            codex_home, backup_root, preferred_encoding=lambda: "ascii"
        ).preview()

    assert _snapshot(tmp_path) == before


def test_backup_failure_leaves_target_unchanged_and_is_typed(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_bytes(b"original\n")
    guidance = CodexGuidance(
        codex_home,
        backup_root,
        backup_writer=lambda path, content: (_ for _ in ()).throw(
            OSError("secret backup failure")
        ),
    )
    preview = guidance.preview()

    with pytest.raises(GuidanceWriteError) as caught:
        guidance.apply(preview.id)

    assert caught.value.reason == "backup_failed"
    assert target.read_bytes() == b"original\n"


def test_replace_failure_leaves_target_unchanged_with_verified_backup(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_bytes(b"original\n")
    guidance = CodexGuidance(
        codex_home,
        backup_root,
        replace=lambda source, destination: (_ for _ in ()).throw(
            OSError("replace failure")
        ),
    )

    with pytest.raises(GuidanceWriteError) as caught:
        guidance.apply(guidance.preview().id)

    assert caught.value.reason == "replace_failed"
    assert target.read_bytes() == b"original\n"
    assert any(
        path.read_bytes() == b"original\n" for path in backup_root.rglob("AGENTS.md")
    )
    assert not list(codex_home.glob(".agentretro-*.tmp"))


def test_readback_failure_rolls_back_exact_original(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_bytes(b"original\n")
    guidance = CodexGuidance(
        codex_home,
        backup_root,
        readback=lambda path: (_ for _ in ()).throw(OSError("readback failure")),
    )

    with pytest.raises(GuidanceWriteError) as caught:
        guidance.apply(guidance.preview().id)

    assert caught.value.reason == "readback_failed"
    assert target.read_bytes() == b"original\n"


def test_failed_readback_and_failed_restore_enter_typed_rollback_required(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    target.write_bytes(b"original\n")
    calls = 0

    def replace_then_fail(source, destination):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("restore failure")
        os.replace(source, destination)

    guidance = CodexGuidance(
        codex_home,
        backup_root,
        replace=replace_then_fail,
        readback=lambda path: (_ for _ in ()).throw(OSError("readback failure")),
    )

    with pytest.raises(GuidanceRollbackRequired) as caught:
        guidance.apply(guidance.preview().id)

    assert caught.value.reason == "rollback_required"
    assert caught.value.backup_path is not None
    assert caught.value.backup_path.read_bytes() == b"original\n"


def test_discovery_reads_only_canonical_target_and_requires_one_exact_block(tmp_path):
    codex_home, backup_root, target = _home(tmp_path)
    guidance = CodexGuidance(codex_home, backup_root)
    guidance.apply(guidance.preview().id)
    (codex_home / "AGENTS.override.md").write_bytes(b"\xff\xfe unrelated")
    (codex_home / "memory.md").write_bytes(b"\xff\xfe native memory")
    before = _snapshot(tmp_path)

    assert discover_managed_instruction(codex_home) is True
    assert _snapshot(tmp_path) == before

    target.write_text(
        f"{MANAGED_START}\nmanual edit\n{MANAGED_END}\n", encoding="utf-8"
    )
    assert discover_managed_instruction(codex_home) is False
