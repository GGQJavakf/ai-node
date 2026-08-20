from __future__ import annotations

from ai_todo_assistant.domain.workflow import WorkItem, WorkItemStatus
from ai_todo_assistant.presentation.cli import TodoCLI, _work_item_triage_reason


def test_list_selection_only_resolves_the_selected_manager_method() -> None:
    cli = object.__new__(TodoCLI)

    class AllOnlyManager:
        def get_all(self):
            return ["only"]

    cli.manager = AllOnlyManager()

    assert cli._select_list_todos("all") == (["only"], "📋 所有任务")


def test_work_item_triage_reason_preserves_overlapping_condition_precedence() -> None:
    done_with_conflict = WorkItem(
        title="Redmine validation",
        status=WorkItemStatus.DONE.value,
        merge_conflicts=["MR conflict"],
    )
    blocked_redmine_and_mr = WorkItem(
        title="Redmine MR GitLab",
        status=WorkItemStatus.BLOCKED.value,
    )
    active_conflict_with_closeout_text = WorkItem(
        title="MR merged but Redmine not closed",
        merge_conflicts=["manual resolution"],
    )
    validation_before_codex = WorkItem(
        title="validation required",
        source="codex",
        source_ref="thread-1",
    )

    assert _work_item_triage_reason(done_with_conflict) == "recently completed"
    assert _work_item_triage_reason(blocked_redmine_and_mr) == "blocked by Redmine"
    assert _work_item_triage_reason(active_conflict_with_closeout_text) == "merge conflict needs manual resolution"
    assert _work_item_triage_reason(validation_before_codex) == "needs validation"
