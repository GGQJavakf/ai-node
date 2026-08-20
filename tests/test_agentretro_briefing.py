from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from _path import ROOT  # noqa: F401
from agent_retro.application.brief import (
    BriefBudgetError,
    BriefRequest,
    BriefService,
    BriefTimeoutError,
    estimate_tokens,
    tokenize,
)
from agent_retro.domain.models import (
    Knowledge,
    KnowledgeConflict,
    KnowledgeType,
    ProjectionEvent,
    ProjectionStatus,
)
from agent_retro.presentation.output import (
    brief_json_data,
    render_brief_markdown,
    render_brief_terminal,
)


NOW = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)


def _knowledge(
    item_id: str,
    kind: KnowledgeType,
    text: str,
    *,
    project_id: str = "NPKI",
    scope: str = "project",
    status: str = "active",
    updated_at: datetime = NOW,
    valid_until: datetime | None = None,
    evidence_ids: tuple[str, ...] = ("evidence-1",),
) -> Knowledge:
    return Knowledge(
        id=item_id,
        version=1,
        candidate_id=f"candidate-{item_id}",
        knowledge_type=kind,
        project_id=project_id,
        scope=scope,
        text=text,
        status=status,
        confidence=0.99,
        accepted_by="user",
        evidence_ids=evidence_ids,
        valid_until=valid_until,
        updated_at=updated_at,
    )


class BriefRepository:
    def __init__(
        self,
        knowledge: list[Knowledge],
        *,
        conflicts: list[KnowledgeConflict] | None = None,
        events: list[ProjectionEvent] | None = None,
        rollback_required: bool = False,
        purge_incomplete: bool = False,
    ) -> None:
        self.knowledge = knowledge
        self.conflicts = conflicts or []
        self.events = events or []
        self.rollback_required = rollback_required
        self.purge_incomplete = purge_incomplete

    def list_brief_knowledge(self, project_id, at):
        return list(self.knowledge)

    def list_open_conflicts(self, project_id):
        return list(self.conflicts)

    def list_projection_events(self, project_id):
        return list(self.events)

    def has_rollback_required_sync(self):
        return self.rollback_required

    def has_purge_incomplete(self):
        return self.purge_incomplete


def _service(repository, *, monotonic=lambda: 0.0, deadline=5.0):
    return BriefService(
        repository,
        now=lambda: NOW,
        monotonic=monotonic,
        timeout_seconds=deadline,
        default_max_tokens=6000,
    )


def test_brief_selects_only_active_accepted_knowledge_in_fixed_category_order():
    repository = BriefRepository(
        [
            _knowledge("lesson", KnowledgeType.LESSON, "NPKI rollback verified"),
            _knowledge(
                "task",
                KnowledgeType.TASK_STATE,
                "NPKI task",
                valid_until=NOW + timedelta(days=1),
            ),
            _knowledge(
                "global",
                KnowledgeType.RULE,
                "global rule",
                project_id="OTHER",
                scope="global",
            ),
            _knowledge("project", KnowledgeType.RULE, "project rule"),
            _knowledge("archived", KnowledgeType.RULE, "old", status="archived"),
            _knowledge("stale", KnowledgeType.TASK_STATE, "old task", status="stale"),
            _knowledge("expired", KnowledgeType.TASK_STATE, "expired", valid_until=NOW),
            _knowledge(
                "other", KnowledgeType.LESSON, "other project", project_id="OTHER"
            ),
        ]
    )

    result = _service(repository).build(
        BriefRequest(task="review NPKI rollback", project_id="NPKI")
    )

    assert [item.id for item in result.items] == ["project", "global", "task", "lesson"]
    assert [item.category for item in result.items] == [
        "project_rule",
        "global_rule",
        "task_state",
        "lesson",
    ]
    assert all(item.status == "active" for item in result.items)
    assert result.stale_ids == ("expired", "stale")
    omissions = {item.id: item.reason for item in result.omitted}
    assert omissions["archived"] == "archived"
    assert omissions["expired"] == "expired"
    assert omissions["stale"] == "stale"


def test_brief_includes_explicitly_global_task_state_and_relevant_lesson():
    repository = BriefRepository(
        [
            _knowledge(
                "global-task",
                KnowledgeType.TASK_STATE,
                "Shared release is blocked on review",
                project_id="OTHER",
                scope="global",
                valid_until=NOW + timedelta(days=1),
            ),
            _knowledge(
                "global-lesson",
                KnowledgeType.LESSON,
                "Shared rollback requires a verified backup",
                project_id="OTHER",
                scope="global",
            ),
            _knowledge(
                "other-project-lesson",
                KnowledgeType.LESSON,
                "Shared rollback without global promotion",
                project_id="OTHER",
            ),
        ]
    )

    result = _service(repository).build(
        BriefRequest(task="review shared rollback", project_id="NPKI")
    )

    assert [item.id for item in result.items] == ["global-task", "global-lesson"]
    assert [item.category for item in result.items] == ["task_state", "lesson"]
    assert "other-project-lesson" not in {item.id for item in result.items}


def test_brief_uses_nfkc_casefold_latin_and_cjk_fixed_scoring_and_id_tie_break():
    repository = BriefRepository(
        [
            _knowledge(
                "lesson-z",
                KnowledgeType.LESSON,
                "ＲＯＬＬＢＡＣＫ 回滚",
                updated_at=NOW - timedelta(days=1),
            ),
            _knowledge(
                "lesson-a",
                KnowledgeType.LESSON,
                "rollback 回滚",
                updated_at=NOW - timedelta(days=1),
            ),
            _knowledge(
                "lesson-old",
                KnowledgeType.LESSON,
                "rollback 回滚",
                updated_at=NOW - timedelta(days=31),
                evidence_ids=(),
            ),
        ]
    )

    result = _service(repository).build(
        BriefRequest(task="Rollback回滚", project_id="NPKI")
    )

    assert tokenize("ＲＯＬＬＢＡＣＫ回滚") == frozenset({"rollback", "回", "滚"})
    assert [item.id for item in result.items] == ["lesson-a", "lesson-z", "lesson-old"]
    assert result.items[0].relevance_score == result.items[1].relevance_score
    expected = 0.70 * 1.0 + 0.20 * (1.0 / (1.0 + 1.0 / 30.0)) + 0.10 * (1.0 / 3.0)
    assert result.items[0].relevance_score == pytest.approx(expected)


def test_mandatory_rules_over_budget_fail_without_partial_result():
    repository = BriefRepository(
        [
            _knowledge("project", KnowledgeType.RULE, "项目规则"),
            _knowledge(
                "global",
                KnowledgeType.RULE,
                "global rule",
                scope="global",
                project_id="OTHER",
            ),
        ]
    )
    required = sum(estimate_tokens(item.text) for item in repository.knowledge)

    with pytest.raises(BriefBudgetError) as caught:
        _service(repository).build(
            BriefRequest(task="NPKI", project_id="NPKI", max_tokens=required - 1)
        )

    assert caught.value.required_tokens > required
    assert caught.value.max_tokens == required - 1
    assert caught.value.reason == "mandatory_rules_over_budget"


def test_later_items_are_included_or_omitted_atomically_by_utf8_byte_budget():
    rule = _knowledge("rule", KnowledgeType.RULE, "rule")
    task = _knowledge(
        "task",
        KnowledgeType.TASK_STATE,
        "任务状态",
        valid_until=NOW + timedelta(days=1),
    )
    lesson = _knowledge("lesson", KnowledgeType.LESSON, "经验很长" * 300)
    budget = 400

    result = _service(BriefRepository([lesson, task, rule])).build(
        BriefRequest(task="任务经验", project_id="NPKI", max_tokens=budget)
    )

    assert [item.id for item in result.items] == ["rule", "task"]
    assert result.estimated_tokens <= budget
    assert [(item.id, item.reason) for item in result.omitted] == [("lesson", "budget")]
    assert result.omitted_count == 1
    assert estimate_tokens("abc中") == 2


def test_brief_reports_evidence_conflict_sync_rollback_and_purge_health():
    repository = BriefRepository(
        [_knowledge("rule", KnowledgeType.RULE, "rule", evidence_ids=("e2", "e1"))],
        conflicts=[
            KnowledgeConflict(
                "conflict-1", "rule", "candidate-2", "different", "merge", "open"
            )
        ],
        events=[
            ProjectionEvent(
                "event-1",
                "NPKI",
                "accept",
                "rule",
                "hash",
                ProjectionStatus.SYNC_PENDING,
                "vault_unavailable",
            )
        ],
        rollback_required=True,
        purge_incomplete=True,
    )

    result = _service(repository).build(BriefRequest(task="NPKI", project_id="NPKI"))

    assert result.items[0].evidence_refs == ("e1", "e2")
    assert result.conflict_ids == ("conflict-1",)
    assert result.warnings == (
        "sync_pending:event-1",
        "rollback_required",
        "purge_incomplete",
    )
    assert ("conflict-1", "conflict") in [
        (item.id, item.reason) for item in result.omitted
    ]


def test_deadline_failure_returns_no_partial_success():
    ticks = iter([0.0, 0.1, 0.2, 5.1])
    repository = BriefRepository(
        [
            _knowledge("rule", KnowledgeType.RULE, "rule"),
            _knowledge("lesson", KnowledgeType.LESSON, "lesson"),
        ]
    )

    with pytest.raises(BriefTimeoutError) as caught:
        _service(repository, monotonic=lambda: next(ticks)).build(
            BriefRequest(task="lesson", project_id="NPKI")
        )

    assert caught.value.reason == "brief_deadline_exceeded"


def test_terminal_markdown_and_json_are_stable_views_of_the_same_result():
    result = _service(
        BriefRepository([_knowledge("rule", KnowledgeType.RULE, "必须保留 rollback")])
    ).build(BriefRequest(task="rollback", project_id="NPKI"))

    terminal = render_brief_terminal(result)
    markdown = render_brief_markdown(result)
    data = brief_json_data(result)

    assert terminal == render_brief_terminal(result)
    assert markdown == render_brief_markdown(result)
    assert data == brief_json_data(result)
    assert "rule" in terminal and "必须保留 rollback" in terminal
    assert "rule" in markdown and "必须保留 rollback" in markdown
    assert data["items"][0]["id"] == "rule"
    assert json.dumps(data, sort_keys=True, ensure_ascii=False).find("\x1b") == -1


def test_brief_never_calls_model_vector_vault_or_native_memory():
    class SQLiteOnly(BriefRepository):
        def __getattr__(self, name):
            if any(token in name for token in ("model", "vector", "vault", "memory")):
                pytest.fail(f"forbidden integration called: {name}")
            raise AttributeError(name)

    result = _service(
        SQLiteOnly([_knowledge("rule", KnowledgeType.RULE, "rule")])
    ).build(BriefRequest(task="rule", project_id="NPKI"))

    assert [item.id for item in result.items] == ["rule"]


def test_same_snapshot_and_clock_produce_identical_result():
    repository = BriefRepository(
        [
            _knowledge("b", KnowledgeType.LESSON, "same"),
            _knowledge("a", KnowledgeType.LESSON, "same"),
        ]
    )
    service = _service(repository)
    request = BriefRequest(task="same", project_id="NPKI")

    assert service.build(request) == service.build(request)


def test_invalid_request_limits_fail_before_repository_access():
    class NeverRead(BriefRepository):
        def list_brief_knowledge(self, project_id, at):
            pytest.fail("repository must not be read")

    service = _service(NeverRead([]))

    with pytest.raises(ValueError, match="max_tokens"):
        service.build(BriefRequest(task="task", project_id="NPKI", max_tokens=0))
    with pytest.raises(ValueError, match="project_id"):
        service.build(BriefRequest(task="task", project_id=""))


def test_budget_counts_complete_terminal_markdown_and_json_renderer_output():
    rule = _knowledge(
        "rule-with-visible-id",
        KnowledgeType.RULE,
        "x",
        evidence_ids=("evidence-visible-1", "evidence-visible-2"),
    )
    request = BriefRequest(task="visible task", project_id="NPKI")

    result = _service(BriefRepository([rule])).build(request)
    rendered_costs = (
        estimate_tokens(render_brief_terminal(result)),
        estimate_tokens(render_brief_markdown(result)),
        estimate_tokens(
            json.dumps(brief_json_data(result), ensure_ascii=False, sort_keys=True)
            + "\n"
        ),
    )

    assert result.estimated_tokens == max(rendered_costs)
    assert all(cost <= result.max_tokens for cost in rendered_costs)
    assert result.items[0].estimated_tokens > estimate_tokens(rule.text)

    with pytest.raises(BriefBudgetError) as caught:
        _service(BriefRepository([rule])).build(
            BriefRequest(task="visible task", project_id="NPKI", max_tokens=5)
        )
    assert caught.value.required_tokens > estimate_tokens(rule.text)
