from __future__ import annotations

import inspect
from pathlib import Path

from ai_todo_assistant.application.workflow.codex_resume import CodexResumeService
from ai_todo_assistant.application.workflow.services import WorkItemService
from ai_todo_assistant.presentation import cli
from scripts import check_ai_todo_complexity


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "ai_todo_complexity_targets.txt"
EXPECTED_MODULES = {
    "ai_todo_assistant.application.workflow.codex_resume",
    "ai_todo_assistant.application.workflow.services",
    "ai_todo_assistant.presentation.cli",
}
EXPECTED_CLI_OWNERS = {
    "_slash_handler_name",
    "_select_list_todos",
    "_build_list_rows",
    "_work_handler_name",
    "_daily_triage_evidence",
    "_format_codex_report",
    "_resolve_codex_resume_option_index",
}
EXPECTED_RESUME_OWNERS = {
    "_select_unfinished_entries",
    "_select_bucket_skips",
}
EXPECTED_WORKFLOW_OWNERS = {
    "_prepare_codex_entry",
    "_resolve_codex_entry",
    "_record_codex_identity_merge",
}


def test_ai_todo_refactor_entry_points_stay_compatible() -> None:
    assert tuple(inspect.signature(cli.TodoCLI).parameters) == ()
    assert tuple(inspect.signature(cli.TodoCLI._handle_slash_command).parameters) == (
        "self",
        "command",
    )
    assert tuple(inspect.signature(cli.TodoCLI._handle_list_command).parameters) == (
        "self",
        "subcmd",
        "args",
    )
    assert tuple(inspect.signature(cli.TodoCLI._handle_work_command).parameters) == (
        "self",
        "subcmd",
        "args",
    )
    assert tuple(inspect.signature(cli._work_item_triage_reason).parameters) == (
        "item",
        "evidence",
    )
    assert tuple(inspect.signature(CodexResumeService).parameters) == (
        "repository",
        "client",
        "exclusion_store",
    )


def test_ai_todo_manifest_and_private_owners_cover_the_refactor() -> None:
    values = {
        line.strip()
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    modules = {
        value.removeprefix("src/").removesuffix(".py").replace("/", ".")
        for value in values
    }
    assert modules == EXPECTED_MODULES
    assert EXPECTED_CLI_OWNERS <= set(vars(cli.TodoCLI))
    assert EXPECTED_RESUME_OWNERS <= set(vars(CodexResumeService))
    assert EXPECTED_WORKFLOW_OWNERS <= set(vars(WorkItemService))


def test_ai_todo_complexity_gate_cannot_be_suppressed_with_noqa(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "src" / "ai_todo_assistant"
    source_root.mkdir(parents=True)
    target = source_root / "hotspot.py"
    branches = "\n".join(f"    if value == {index}:\n        return {index}" for index in range(16))
    target.write_text(
        f"def too_complex(value):  # noqa: C901\n{branches}\n    return -1\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "config" / "ai_todo_complexity_targets.txt"
    manifest.parent.mkdir()
    manifest.write_text("src/ai_todo_assistant/hotspot.py\n", encoding="utf-8")
    monkeypatch.setattr(check_ai_todo_complexity, "ROOT", tmp_path)
    monkeypatch.setattr(check_ai_todo_complexity, "MANIFEST", manifest)
    monkeypatch.setattr(check_ai_todo_complexity, "SOURCE_ROOT", source_root)

    assert check_ai_todo_complexity.main() == 1


def test_ai_todo_complexity_gate_uses_stricter_manifest_ceiling(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "src" / "ai_todo_assistant"
    source_root.mkdir(parents=True)
    target = source_root / "target.py"
    branches = "\n".join(f"    if value == {index}:\n        return {index}" for index in range(11))
    target.write_text(f"def target_hotspot(value):\n{branches}\n    return -1\n", encoding="utf-8")
    manifest = tmp_path / "config" / "ai_todo_complexity_targets.txt"
    manifest.parent.mkdir()
    manifest.write_text("src/ai_todo_assistant/target.py\n", encoding="utf-8")
    monkeypatch.setattr(check_ai_todo_complexity, "ROOT", tmp_path)
    monkeypatch.setattr(check_ai_todo_complexity, "MANIFEST", manifest)
    monkeypatch.setattr(check_ai_todo_complexity, "SOURCE_ROOT", source_root)

    assert check_ai_todo_complexity.main() == 1


def test_ai_todo_complexity_gate_retains_package_ceiling(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "src" / "ai_todo_assistant"
    source_root.mkdir(parents=True)
    target = source_root / "target.py"
    target.write_text("def target(value):\n    return value\n", encoding="utf-8")
    branches = "\n".join(f"    if value == {index}:\n        return {index}" for index in range(11))
    (source_root / "package_hotspot.py").write_text(
        f"def package_hotspot(value):\n{branches}\n    return -1\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "config" / "ai_todo_complexity_targets.txt"
    manifest.parent.mkdir()
    manifest.write_text("src/ai_todo_assistant/target.py\n", encoding="utf-8")
    monkeypatch.setattr(check_ai_todo_complexity, "ROOT", tmp_path)
    monkeypatch.setattr(check_ai_todo_complexity, "MANIFEST", manifest)
    monkeypatch.setattr(check_ai_todo_complexity, "SOURCE_ROOT", source_root)

    assert check_ai_todo_complexity.main() == 0
