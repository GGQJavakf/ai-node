"""Focused command execution and error rendering for the AgentRetro CLI."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import singledispatch

from agent_retro.application.brief import BriefBudgetError, BriefTimeoutError
from agent_retro.application.capture import (
    CapturePlanChangedError,
    RecentCaptureBoundsError,
)
from agent_retro.application.inbox import InboxLimitError
from agent_retro.application.merge import (
    ConfirmationRequiredError,
    MergeIntegrityError,
    StalePlanError,
)
from agent_retro.application.obsidian_init import (
    BoundaryInitError,
    BoundaryInitStalePlan,
)
from agent_retro.application.purge import (
    IncompletePurgeConfirmation,
    KnowledgeAlreadyPurged,
    KnowledgeSyncPending,
    PurgeAlreadyComplete,
    PurgeBlockedError,
    PurgeError,
    PurgeKnowledgeNotFound,
    PurgeRecoveryNotFound,
    PurgeRecoveryNotIncomplete,
    StalePurgePlan,
    UnknownPurgePlan,
)
from agent_retro.application.review import ReviewUnavailableError
from agent_retro.application.sync import ProjectionPersistenceError
from agent_retro.infrastructure.codex_guidance import GuidanceError
from agent_retro.infrastructure.llm_merge import MergeProposalUnavailableError
from agent_retro.infrastructure.project_mapping import ProjectReferenceError
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.presentation.output import safe_text, write_json


@dataclass(frozen=True)
class _ErrorResponse:
    code: str
    message: str
    data: Mapping[str, object]
    human: str


_EXPECTED_ERRORS = (
    BriefBudgetError,
    BriefTimeoutError,
    ProjectReferenceError,
    RecentCaptureBoundsError,
    InboxLimitError,
    CapturePlanChangedError,
    GuidanceError,
    BoundaryInitError,
    ReviewUnavailableError,
    ProjectionPersistenceError,
    PurgeError,
    ConfirmationRequiredError,
    StalePlanError,
    MergeIntegrityError,
    MergeProposalUnavailableError,
    KeyError,
    OSError,
    RuntimeError,
    ValueError,
)


def dispatch_command(
    command_name: str, handlers: Mapping[str, Callable[[], int]]
) -> int:
    """Dispatch one already-parsed command through an explicit lazy handler map."""

    try:
        handler = handlers[command_name]
    except KeyError:
        raise ValueError(f"unsupported AgentRetro command: {command_name}") from None
    return handler()


def run_with_error_handling(*, json_output: bool, command: Callable[[], int]) -> int:
    """Execute one command while preserving the stable CLI failure envelope."""

    try:
        return command()
    except _EXPECTED_ERRORS as exc:
        response = _error_response(exc)
        if json_output:
            write_json(
                {
                    "status": "error",
                    "code": response.code,
                    "message": response.message,
                    "data": dict(response.data),
                }
            )
        else:
            sys.stderr.write(safe_text(response.human) + "\n")
        return 2


def write_success(
    *, json_output: bool, code: str, message: str, data: object
) -> None:
    """Render the stable success envelope for one command family."""

    if json_output:
        write_json(
            {
                "status": "ok",
                "code": code,
                "message": message,
                "data": data,
            }
        )
    else:
        sys.stdout.write(safe_text(_json_text(data)) + "\n")


def write_operation_outcome(
    *, json_output: bool, outcome: tuple[int, str, str, object]
) -> int:
    """Render success or recoverable failure without changing its exit code."""

    exit_code, code, message, data = outcome
    if json_output:
        write_json(
            {
                "status": "ok" if exit_code == 0 else "error",
                "code": code,
                "message": message,
                "data": data,
            }
        )
    else:
        sys.stdout.write(safe_text(_json_text(data)) + "\n")
    return exit_code


@singledispatch
def _error_response(exc: BaseException) -> _ErrorResponse:
    raise TypeError(f"unsupported command error: {type(exc).__name__}")


@_error_response.register
def _brief_budget_error(exc: BriefBudgetError) -> _ErrorResponse:
    data = {
        "max_tokens": exc.max_tokens,
        "reason": exc.reason,
        "required_tokens": exc.required_tokens,
    }
    return _response(
        "RETRO_BRIEF_BUDGET_EXCEEDED",
        "Mandatory rules exceed the brief budget.",
        data,
    )


@_error_response.register
def _brief_timeout_error(exc: BriefTimeoutError) -> _ErrorResponse:
    return _response(
        "RETRO_BRIEF_DEADLINE_EXCEEDED",
        "Local brief rendering exceeded its deadline.",
        {"reason": exc.reason},
        str(exc),
    )


@_error_response.register
def _project_reference_error(exc: ProjectReferenceError) -> _ErrorResponse:
    code = (
        "RETRO_AMBIGUOUS_PROJECT_REFERENCE"
        if exc.status == "ambiguous"
        else "RETRO_UNKNOWN_PROJECT_REFERENCE"
    )
    return _response(
        code,
        "Project reference could not be resolved safely.",
        {
            "reason": exc.reason,
            "mapping_ids": list(exc.mapping_ids),
            "recovery_command": exc.recovery_command,
        },
    )


@_error_response.register
def _recent_capture_bounds_error(exc: RecentCaptureBoundsError) -> _ErrorResponse:
    return _response(
        "RETRO_RECENT_CAPTURE_COUNT_OUT_OF_BOUNDS",
        "Recent capture count is outside the safe bound.",
        {
            "reason": exc.reason,
            "requested_count": exc.count,
            "recent_capture_max": exc.maximum,
        },
    )


@_error_response.register
def _inbox_limit_error(exc: InboxLimitError) -> _ErrorResponse:
    return _response(
        "RETRO_REVIEW_INBOX_LIMIT_OUT_OF_BOUNDS",
        "Review inbox limit is outside the safe bound.",
        {"reason": exc.reason, "limit": exc.limit, "minimum": 1, "maximum": 50},
    )


@_error_response.register
def _capture_plan_changed_error(exc: CapturePlanChangedError) -> _ErrorResponse:
    return _response(
        "RETRO_CAPTURE_PLAN_CHANGED",
        "Recent capture plan changed before apply.",
        {"reason": exc.reason, "recovery_command": exc.recovery_command},
    )


@_error_response.register
def _guidance_error(exc: GuidanceError) -> _ErrorResponse:
    reason = getattr(exc, "reason", "guidance_error")
    return _response(
        "RETRO_CODEX_INTEGRATION_FAILED",
        "Codex guidance integration failed safely.",
        {"reason": reason},
        reason,
    )


@_error_response.register
def _boundary_init_error(exc: BoundaryInitError) -> _ErrorResponse:
    code = (
        "RETRO_SYNC_INIT_STALE"
        if isinstance(exc, BoundaryInitStalePlan)
        else "RETRO_SYNC_INIT_FAILED"
    )
    return _response(
        code,
        "Obsidian managed-boundary initialization failed safely.",
        {"reason": exc.reason, "recovery_command": exc.recovery_command},
    )


@_error_response.register
def _review_unavailable_error(exc: ReviewUnavailableError) -> _ErrorResponse:
    del exc
    return _response(
        "RETRO_REVIEW_RETRYABLE",
        "Model review is unavailable; retry is available.",
        {"retryable": True},
        "模型审核暂不可用；可安全重试。",
    )


@_error_response.register
def _projection_persistence_error(exc: ProjectionPersistenceError) -> _ErrorResponse:
    return _response(
        "RETRO_SYNC_STATE_UNAVAILABLE",
        "Projection state is unavailable; SQLite knowledge remains authoritative.",
        {"reason": exc.reason, "recovery_command": exc.recovery_command},
        "SQLite 知识保持权威；"
        f"{exc.reason}；恢复命令: {exc.recovery_command}",
    )


@_error_response.register
def _purge_error(exc: PurgeError) -> _ErrorResponse:
    recovery_command = getattr(exc, "recovery_command", _purge_recovery(exc))
    return _response(
        _purge_error_code(exc),
        "Sensitive purge command failed safely.",
        {"recovery_command": recovery_command},
    )


@_error_response.register
def _confirmation_required_error(exc: ConfirmationRequiredError) -> _ErrorResponse:
    return _response(
        "RETRO_MERGE_CONFIRMATION_REQUIRED",
        "Exact merge confirmation is required.",
        {
            "missing_operation_ids": list(exc.missing_operation_ids),
            "recovery_command": "retro merge preview <plan-id>",
        },
    )


@_error_response.register
def _stale_plan_error(exc: StalePlanError) -> _ErrorResponse:
    del exc
    return _response(
        "RETRO_MERGE_PLAN_STALE",
        "Merge plan inputs changed; create a new plan.",
        {},
        "合并计划已过期，请重新生成。",
    )


@_error_response.register
def _merge_integrity_error(exc: MergeIntegrityError) -> _ErrorResponse:
    del exc
    return _response(
        "RETRO_MERGE_PLAN_INVALID",
        "Merge plan integrity validation failed.",
        {},
        "合并计划完整性校验失败。",
    )


@_error_response.register
def _merge_proposal_unavailable_error(
    exc: MergeProposalUnavailableError,
) -> _ErrorResponse:
    del exc
    return _response(
        "RETRO_MERGE_MODEL_UNAVAILABLE",
        "Semantic merge model is unavailable.",
        {"retryable": True},
        "语义合并模型暂不可用；可安全重试。",
    )


def _generic_command_error(exc: BaseException) -> _ErrorResponse:
    detail = Redactor().redact(str(exc))
    return _response(
        "RETRO_COMMAND_FAILED",
        "AgentRetro command failed.",
        {"detail": detail},
        detail,
    )


for _generic_type in (KeyError, OSError, RuntimeError, ValueError):
    _error_response.register(_generic_type)(_generic_command_error)


def _response(
    code: str,
    message: str,
    data: Mapping[str, object],
    human: str | None = None,
) -> _ErrorResponse:
    return _ErrorResponse(code, message, data, human or _json_text(data))


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _purge_recovery(exc: PurgeError) -> str:
    plan_errors = (
        IncompletePurgeConfirmation,
        KnowledgeAlreadyPurged,
        KnowledgeSyncPending,
        PurgeKnowledgeNotFound,
        StalePurgePlan,
        UnknownPurgePlan,
    )
    return (
        "retro kb purge <id> --plan"
        if isinstance(exc, plan_errors)
        else "retro kb purge <id> --recover"
    )


@singledispatch
def _purge_error_code(exc: PurgeError) -> str:
    return "RETRO_PURGE_FAILED"


@_purge_error_code.register(IncompletePurgeConfirmation)
def _purge_confirmation_code(exc: PurgeError) -> str:
    del exc
    return "RETRO_PURGE_CONFIRMATION_REQUIRED"


@_purge_error_code.register(StalePurgePlan)
@_purge_error_code.register(UnknownPurgePlan)
def _purge_stale_code(exc: PurgeError) -> str:
    del exc
    return "RETRO_PURGE_PLAN_STALE"


@_purge_error_code.register(PurgeBlockedError)
def _purge_blocked_code(exc: PurgeError) -> str:
    del exc
    return "RETRO_PURGE_BLOCKED"


@_purge_error_code.register(PurgeRecoveryNotFound)
def _purge_recovery_not_found_code(exc: PurgeError) -> str:
    del exc
    return "RETRO_PURGE_RECOVERY_NOT_FOUND"


@_purge_error_code.register(PurgeAlreadyComplete)
@_purge_error_code.register(KnowledgeAlreadyPurged)
def _purge_already_complete_code(exc: PurgeError) -> str:
    del exc
    return "RETRO_PURGE_ALREADY_COMPLETE"


@_purge_error_code.register(PurgeRecoveryNotIncomplete)
def _purge_recovery_not_incomplete_code(exc: PurgeError) -> str:
    del exc
    return "RETRO_PURGE_RECOVERY_NOT_INCOMPLETE"


@_purge_error_code.register(PurgeKnowledgeNotFound)
def _purge_knowledge_not_found_code(exc: PurgeError) -> str:
    del exc
    return "RETRO_PURGE_KNOWLEDGE_NOT_FOUND"


@_purge_error_code.register(KnowledgeSyncPending)
def _purge_sync_pending_code(exc: PurgeError) -> str:
    del exc
    return "RETRO_PURGE_SYNC_PENDING"
