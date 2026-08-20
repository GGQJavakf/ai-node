"""Independent AgentRetro command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Mapping

from agent_retro.application.bootstrap import (
    build_doctor_service,
    build_managed_boundary_initializer,
    build_purge_service,
    build_projection_coordinator,
    build_retro_repository,
)
from agent_retro.application.brief import (
    BriefRequest,
    BriefService,
)
from agent_retro.application.merge import MergeService
from agent_retro.application.merge_planner import MergePlanner
from agent_retro.application.purge import (
    IncompletePurgeConfirmation,
    StalePurgePlan,
)
from agent_retro.application.capture import (
    CaptureResult,
    CaptureService,
    RecentCapturePlan,
    RecentCaptureResult,
)
from agent_retro.application.review import ReviewService
from agent_retro.domain.models import (
    CandidateStatus,
    KnowledgeType,
    ProjectionStatus,
    PurgeStatus,
)
from agent_retro.infrastructure.codex_sessions import (
    CodexSessionSource,
    effective_codex_home,
)
from agent_retro.infrastructure.codex_guidance import CodexGuidance
from agent_retro.infrastructure.legacy_model import (
    build_retro_llm_client_from_config,
    load_legacy_model_config,
)
from agent_retro.infrastructure.llm_review import (
    LLMExtractionGateway,
    LLMReviewGateway,
)
from agent_retro.infrastructure.llm_merge import (
    LLMMergeProposalGateway,
    MergeProposalUnavailableError,
)
from agent_retro.infrastructure.project_mapping import (
    ProjectMappingService,
    ProjectReferenceError,
    ProjectReferenceResolver,
    ProjectResolver,
)
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.settings import (
    effective_model_timeout,
    load_retro_settings,
)
from agent_retro.presentation.output import (
    brief_json_data,
    doctor_json_data,
    render_brief_markdown,
    render_brief_terminal,
    render_doctor_terminal,
    safe_text,
    write_json,
)
from agent_retro.presentation._command_dispatch import (
    dispatch_command,
    run_with_error_handling,
    write_operation_outcome,
    write_success,
)
from agent_retro.presentation.review_commands import run_review_command


_READY_MESSAGE = "AgentRetro 已就绪。"
_READY_ENVELOPE = {
    "status": "ok",
    "code": "RETRO_READY",
    "message": "AgentRetro is ready.",
    "data": {},
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retro", description="Codex 会话复盘与知识沉淀"
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    commands = parser.add_subparsers(dest="command")

    capture = commands.add_parser("capture", help="捕获一个已完成的 Codex 会话")
    selector = capture.add_mutually_exclusive_group(required=True)
    selector.add_argument("--last", action="store_true", dest="capture_last")
    selector.add_argument("--session", dest="session_id")
    selector.add_argument("--recent", type=int, dest="recent_count")
    capture_mode = capture.add_mutually_exclusive_group()
    capture_mode.add_argument("--dry-run", action="store_true", dest="capture_dry_run")
    capture_mode.add_argument("--apply", dest="capture_plan_id")

    project = commands.add_parser("project", help="管理项目映射")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    map_command = project_commands.add_parser("map", help="创建项目映射")
    map_command.add_argument("--root", required=True, type=Path)
    map_command.add_argument("--vault-project", required=True)
    map_workspace = project_commands.add_parser(
        "map-workspace", help="创建非 Git 工作区显式映射"
    )
    map_workspace.add_argument("--root", required=True, type=Path)
    map_workspace.add_argument("--vault-project", required=True)
    project_commands.add_parser("list", help="列出活动项目映射")
    remove = project_commands.add_parser("remove", help="停用项目映射")
    remove.add_argument("mapping_id")
    reclassify = project_commands.add_parser(
        "reclassify", help="重新分类 awaiting 会话"
    )
    reclassify.add_argument("--session", dest="session_id", required=True)
    reclassify.add_argument("--mapping", dest="mapping_id", required=True)

    review = commands.add_parser("review", help="审核知识候选")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    run = review_commands.add_parser("run", help="提取并审核一个已捕获会话")
    run.add_argument("--session", dest="session_id", required=True)
    list_command = review_commands.add_parser("list", help="列出知识候选")
    list_command.add_argument(
        "--status",
        dest="candidate_status",
        choices=[item.value for item in CandidateStatus],
    )
    show = review_commands.add_parser("show", help="查看知识候选")
    show.add_argument("candidate_id")
    accept = review_commands.add_parser("accept", help="接受知识候选")
    accept.add_argument("candidate_id")
    edit = review_commands.add_parser("edit", help="编辑并接受知识候选")
    edit.add_argument("candidate_id")
    edit.add_argument("--text", required=True)
    edit.add_argument(
        "--type",
        dest="knowledge_type",
        choices=[item.value for item in KnowledgeType],
    )
    edit.add_argument("--scope", choices=("project", "global"))
    edit.add_argument("--valid-until", dest="valid_until", type=_datetime_argument)
    reject = review_commands.add_parser("reject", help="拒绝知识候选")
    reject.add_argument("candidate_id")
    retry = review_commands.add_parser("retry", help="重试模型审核")
    retry_selector = retry.add_mutually_exclusive_group(required=True)
    retry_selector.add_argument("--candidate", dest="retry_candidate_id")
    retry_selector.add_argument("--session", dest="retry_session_id")
    inbox = review_commands.add_parser("inbox", help="查看只读审核工作摘要")
    inbox_selector = inbox.add_mutually_exclusive_group()
    inbox_selector.add_argument("--project", dest="inbox_project")
    inbox_selector.add_argument("--awaiting", action="store_true", dest="inbox_awaiting")
    inbox.add_argument("--limit", type=int, default=20, dest="inbox_limit")
    merge = review_commands.add_parser("merge", help="合并知识冲突")
    merge.add_argument("conflict_id")
    merge.add_argument("--text", required=True)
    promote = review_commands.add_parser("promote", help="提升为全局知识")
    promote.add_argument("knowledge_id")
    archive = review_commands.add_parser("archive", help="归档知识")
    archive.add_argument("knowledge_id")
    sync = commands.add_parser("sync", help="恢复 Obsidian 知识投影")
    sync_commands = sync.add_subparsers(dest="sync_command", required=True)
    sync_retry = sync_commands.add_parser("retry", help="重试待同步投影")
    sync_retry.add_argument("event_id")
    sync_init = sync_commands.add_parser("init", help="预览或初始化 Obsidian 托管块")
    sync_init.add_argument("--project", required=True, dest="project_id")
    sync_init.add_argument("--apply", metavar="PLAN_ID", dest="init_plan_id")
    sync_conflicts = sync_commands.add_parser(
        "conflicts", help="列出 Obsidian 外部编辑冲突"
    )
    sync_conflicts.add_argument("--project", required=True, dest="project_id")
    sync_reconcile = sync_commands.add_parser(
        "reconcile", help="协调 Obsidian 外部编辑"
    )
    sync_reconcile.add_argument("conflict_id")
    sync_reconcile.add_argument(
        "--action",
        required=True,
        choices=("keep_database", "adopt_vault", "manual_edit"),
    )

    merge = commands.add_parser("merge", help="预览并应用受控 Obsidian 深度合并")
    merge_commands = merge.add_subparsers(dest="merge_command", required=True)
    merge_plan = merge_commands.add_parser("plan", help="生成语义合并预览计划")
    merge_plan.add_argument("--project", required=True, dest="project_id")
    merge_plan.add_argument("--instruction", required=True)
    merge_preview = merge_commands.add_parser("preview", help="查看完整合并计划")
    merge_preview.add_argument("plan_id")
    merge_apply = merge_commands.add_parser("apply", help="应用当前合并计划")
    merge_apply.add_argument("plan_id")
    merge_apply.add_argument("--apply", action="store_true", dest="merge_confirmed")
    merge_apply.add_argument(
        "--confirm-operation",
        action="append",
        default=[],
        dest="confirmed_operations",
    )

    knowledge = commands.add_parser("kb", aliases=["knowledge"], help="管理已接受知识")
    knowledge_commands = knowledge.add_subparsers(
        dest="knowledge_command", required=True
    )
    purge = knowledge_commands.add_parser("purge", help="显式清除敏感知识")
    purge.add_argument("knowledge_id")
    purge_mode = purge.add_mutually_exclusive_group(required=True)
    purge_mode.add_argument("--plan", action="store_true", dest="purge_plan")
    purge_mode.add_argument("--apply-plan", dest="purge_plan_id")
    purge_mode.add_argument("--recover", action="store_true", dest="purge_recover")
    purge.add_argument(
        "--confirm-operation",
        action="append",
        default=[],
        dest="confirmed_operations",
    )

    brief = commands.add_parser("brief", help="生成任务范围内的本地知识简报")
    brief.add_argument("task")
    brief.add_argument("--project", required=True, dest="project_id")
    brief.add_argument("--max-tokens", type=int, dest="max_tokens")
    brief.add_argument("--markdown", action="store_true")

    commands.add_parser("doctor", help="只读检查 AgentRetro 就绪状态")

    integrate = commands.add_parser("integrate", help="管理显式 Codex 指引集成")
    integrate_commands = integrate.add_subparsers(
        dest="integrate_command", required=True
    )
    codex = integrate_commands.add_parser("codex", help="管理 canonical AGENTS.md")
    action = codex.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", dest="integrate_apply")
    action.add_argument("--remove", action="store_true", dest="integrate_remove")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command is not None:
        return run_with_error_handling(
            json_output=args.json_output,
            command=lambda: _run_command(args, home=home, env=env),
        )
    if args.json_output:
        write_json(_READY_ENVELOPE)
    else:
        sys.stdout.write(safe_text(_READY_MESSAGE) + "\n")
    return 0


def _run_command(
    args: argparse.Namespace,
    *,
    home: Path | None,
    env: Mapping[str, str] | None,
) -> int:
    values = os.environ if env is None else env
    settings = load_retro_settings(home=home, env=values)
    codex_home = effective_codex_home(home=home, env=values)
    early_handlers = {
        "doctor": lambda: _run_doctor_command(args, settings, codex_home),
        "integrate": lambda: _run_integrate_command(
            args, settings, codex_home
        ),
    }
    if args.command in early_handlers:
        return dispatch_command(args.command, early_handlers)

    repository = build_retro_repository(settings)
    if args.command == "brief":
        return _run_brief_command(args, settings, repository)

    coordinator = build_projection_coordinator(settings, repository)
    if args.command in {"kb", "knowledge"}:
        return _run_purge_command(
            args,
            build_purge_service(
                settings,
                repository,
                completed_projection=coordinator.after_commit,
            ),
        )

    resolver = ProjectResolver(repository.list_project_mappings())
    handlers = {
        "sync": lambda: _run_sync_command(
            args, settings, repository, coordinator
        ),
        "merge": lambda: _run_merge_command(args, settings, repository),
        "capture": lambda: _run_capture_command(
            args, settings, repository, resolver, home, values
        ),
        "review": lambda: run_review_command(
            args,
            settings,
            repository,
            build_review_service=_build_review_service,
            projection_coordinator=coordinator,
        ),
        "project": lambda: _run_project_command(args, settings, repository),
    }
    return dispatch_command(args.command, handlers)


def _run_doctor_command(args, settings, codex_home: Path) -> int:
    report = build_doctor_service(
        settings, codex_home, load_legacy_model_config
    ).run()
    if args.json_output:
        write_json(
            {
                "status": "ok" if report.exit_code == 0 else "error",
                "code": (
                    "RETRO_DOCTOR_READY"
                    if report.exit_code == 0
                    else "RETRO_DOCTOR_ISSUES"
                ),
                "message": "AgentRetro doctor checks completed.",
                "data": doctor_json_data(report),
            }
        )
    else:
        sys.stdout.write(safe_text(render_doctor_terminal(report)))
    return report.exit_code


def _run_integrate_command(args, settings, codex_home: Path) -> int:
    guidance = CodexGuidance(codex_home, settings.backup_dir)
    action = (
        "remove"
        if args.integrate_remove
        else "apply"
        if args.integrate_apply
        else "preview"
    )
    preview = guidance.preview_remove() if action == "remove" else guidance.preview()
    guidance_data = _guidance_preview_data(preview)
    override = codex_home / "AGENTS.override.md"
    guidance_data["override_conflict"] = override.exists() or override.is_symlink()
    if action != "preview":
        guidance_result = (
            guidance.remove(preview.id)
            if action == "remove"
            else guidance.apply(preview.id)
        )
        guidance_data.update(
            {
                "changed": guidance_result.changed,
                "result_status": guidance_result.status,
                "target_hash": guidance_result.target_hash,
            }
        )
        if action == "apply":
            guidance_data["discoverable"] = guidance_result.discoverable
    code = {
        "preview": "RETRO_CODEX_INTEGRATION_PREVIEW",
        "apply": "RETRO_CODEX_INTEGRATION_APPLIED",
        "remove": "RETRO_CODEX_INTEGRATION_REMOVED",
    }[action]
    _write_success(
        args,
        code,
        "Codex guidance integration command completed.",
        guidance_data,
    )
    return 0


def _run_brief_command(args, settings, repository) -> int:
    project_resolution = ProjectReferenceResolver(
        repository.list_project_mappings()
    ).resolve(args.project_id)
    if project_resolution.status != "resolved":
        raise ProjectReferenceError(project_resolution)
    brief_result = BriefService(
        repository,
        timeout_seconds=settings.brief_timeout_seconds,
        default_max_tokens=settings.brief_max_tokens,
        recent_capture_max=settings.recent_capture_max,
    ).build(
        BriefRequest(
            task=args.task,
            project_id=project_resolution.project_id,
            max_tokens=args.max_tokens,
        )
    )
    if args.json_output:
        write_json(
            {
                "status": "ok",
                "code": "RETRO_BRIEF_READY",
                "message": "Task-scoped brief generated.",
                "data": brief_json_data(brief_result),
            }
        )
    elif args.markdown:
        sys.stdout.write(safe_text(render_brief_markdown(brief_result)))
    else:
        sys.stdout.write(safe_text(render_brief_terminal(brief_result)))
    return 0


def _run_sync_command(args, settings, repository, coordinator) -> int:
    if args.sync_command == "init":
        outcome = _sync_init_outcome(args, settings, repository)
    elif args.sync_command == "retry":
        outcome = _sync_retry_outcome(args, coordinator)
    else:
        outcome = _sync_external_edit_outcome(args, settings, repository)
    return _write_operation_outcome(args, outcome)


def _sync_init_outcome(args, settings, repository):
    initializer = build_managed_boundary_initializer(settings, repository)
    init_plan = initializer.preview(args.project_id)
    sync_data = _boundary_init_plan_data(init_plan)
    if not args.init_plan_id:
        return (
            0,
            "RETRO_SYNC_INIT_PREVIEW",
            "Obsidian managed-boundary initialization previewed.",
            sync_data,
        )
    init_result = initializer.apply(args.project_id, args.init_plan_id)
    sync_data = _boundary_init_plan_data(init_result.plan)
    sync_data.update(
        {
            "status": init_result.status.value,
            "changed": init_result.changed,
            "reason": init_result.reason,
            "recovery_command": init_result.recovery_command,
        }
    )
    synced = init_result.status is ProjectionStatus.SYNCED
    return (
        0 if synced else 2,
        "RETRO_SYNC_INIT_APPLIED" if synced else "RETRO_SYNC_INIT_FAILED",
        "Obsidian managed-boundary initialization applied.",
        sync_data,
    )


def _sync_retry_outcome(args, coordinator):
    retry_result = coordinator.retry(args.event_id)
    sync_data = {
        "event_id": retry_result.event_id,
        "projection_status": retry_result.status.value,
        "warning": retry_result.warning,
        "recovery_command": retry_result.recovery_command,
        "reason": retry_result.reason,
    }
    if retry_result.status is ProjectionStatus.SYNCED:
        return (
            0,
            "RETRO_SYNC_RETRIED",
            "Obsidian projection retry completed.",
            sync_data,
        )
    code = retry_result.warning or (
        "RETRO_ROLLBACK_REQUIRED"
        if retry_result.status is ProjectionStatus.ROLLBACK_REQUIRED
        else "RETRO_SYNC_PENDING"
    )
    if not sync_data["recovery_command"]:
        sync_data["recovery_command"] = (
            "retro doctor --repair-sync"
            if retry_result.status is ProjectionStatus.ROLLBACK_REQUIRED
            else f"retro sync retry {retry_result.event_id}"
        )
    return (
        2,
        code,
        "Obsidian projection retry remains incomplete.",
        sync_data,
    )


def _sync_external_edit_outcome(args, settings, repository):
    merge_service = MergeService(
        repository,
        settings.obsidian_root,
        settings.backup_dir,
    )
    if args.sync_command == "conflicts":
        conflicts = merge_service.find_external_edits(args.project_id)
        return (
            0,
            "RETRO_SYNC_CONFLICTS",
            "Obsidian external-edit conflicts inspected.",
            {
                "conflicts": [
                    {
                        "id": item.id,
                        "project_id": item.project_id,
                        "path": item.path.as_posix(),
                        "recorded_hash": item.recorded_hash,
                        "vault_hash": item.vault_hash,
                        "status": item.status,
                    }
                    for item in conflicts
                ]
            },
        )
    reconciled = merge_service.reconcile(
        args.conflict_id, args.action, actor="user"
    )
    return (
        0,
        "RETRO_SYNC_RECONCILED",
        "Obsidian external edit reconciliation recorded.",
        {
            "conflict_id": reconciled.conflict_id,
            "status": reconciled.status,
            "candidate_id": reconciled.candidate_id,
            "plan_id": reconciled.plan_id,
        },
    )


def _run_merge_command(args, settings, repository) -> int:
    merge_service = MergeService(
        repository,
        settings.obsidian_root,
        settings.backup_dir,
    )
    if args.merge_command == "plan":
        merge_plan = _build_merge_planner(settings, repository).plan(
            args.project_id, args.instruction
        )
        outcome = (
            0,
            "RETRO_MERGE_PLANNED",
            "Preview-only semantic merge plan created.",
            _merge_plan_data(merge_plan),
        )
    elif args.merge_command == "preview":
        merge_plan = merge_service.preview(args.plan_id)
        outcome = (
            0,
            "RETRO_MERGE_PREVIEW",
            "Current complete merge plan preview.",
            _merge_plan_data(merge_plan),
        )
    else:
        outcome = _merge_apply_outcome(args, merge_service)
    return _write_operation_outcome(args, outcome)


def _merge_apply_outcome(args, merge_service):
    merge_result = merge_service.apply(
        args.plan_id,
        confirmed=args.merge_confirmed,
        confirmed_operations=tuple(args.confirmed_operations),
    )
    merge_data = {
        "plan_id": merge_result.plan_id,
        "status": merge_result.status,
        "reason": merge_result.reason,
    }
    if merge_result.status in {"synced", "already_applied"}:
        return (
            0,
            "RETRO_MERGE_APPLIED",
            "Confirmed merge apply completed.",
            merge_data,
        )
    if merge_result.status == "rollback_required":
        code = "RETRO_ROLLBACK_REQUIRED"
        recovery_command = "retro doctor --repair-sync"
    else:
        code = "RETRO_MERGE_SYNC_PENDING"
        recovery_command = f"retro merge preview {merge_result.plan_id}"
    merge_data["recovery_command"] = recovery_command
    return (
        2,
        code,
        "Confirmed merge apply remains incomplete.",
        merge_data,
    )


def _run_capture_command(
    args, settings, repository, resolver, home: Path | None, values
) -> int:
    source = CodexSessionSource(
        effective_codex_home(home=home, env=values),
        max_candidates=settings.discovery_max_files,
        discovery_timeout_seconds=settings.discovery_timeout_seconds,
        max_session_bytes=settings.session_max_bytes,
    )
    capture_service = CaptureService(source, repository, Redactor(), resolver)
    if args.recent_count is not None:
        return _run_recent_capture(args, settings, capture_service)
    if args.capture_dry_run or args.capture_plan_id:
        raise ValueError("--dry-run and --apply require --recent <count>")
    capture_result = (
        capture_service.capture_last()
        if args.capture_last
        else capture_service.capture_session(args.session_id)
    )
    _write_capture_result(capture_result, args.json_output)
    return 0


def _run_recent_capture(args, settings, capture_service) -> int:
    if not args.capture_dry_run and not args.capture_plan_id:
        raise ValueError("recent capture requires --dry-run or --apply <plan-id>")
    if args.capture_dry_run:
        capture_plan = capture_service.preview_recent(
            args.recent_count, settings.recent_capture_max
        )
        _write_recent_capture_plan(capture_plan, args.json_output)
        return 0
    capture_batch = capture_service.apply_recent(
        args.recent_count,
        settings.recent_capture_max,
        args.capture_plan_id,
    )
    _write_recent_capture_result(capture_batch, args.json_output)
    return 2 if capture_batch.failed else 0


def _run_project_command(args, settings, repository) -> int:
    review_stored_evidence = _review_unavailable
    if args.project_command == "reclassify":
        review_stored_evidence = _build_review_service(
            settings, repository
        ).review_stored_evidence
    project_service = ProjectMappingService(
        repository,
        vault_root=settings.obsidian_root,
        review_stored_evidence=review_stored_evidence,
    )
    project_data = _project_command_data(args, project_service)
    _write_success(
        args,
        "RETRO_PROJECT_UPDATED",
        (
            "Project session reclassified."
            if args.project_command == "reclassify"
            else "Project mapping command completed."
        ),
        project_data,
    )
    return 0


def _project_command_data(args, project_service):
    if args.project_command == "map":
        return _mapping_data(
            project_service.map(args.root, args.vault_project)
        )
    if args.project_command == "map-workspace":
        return _mapping_data(
            project_service.map_workspace(args.root, args.vault_project)
        )
    if args.project_command == "list":
        return [_mapping_data(mapping) for mapping in project_service.list()]
    if args.project_command == "remove":
        project_service.remove(args.mapping_id)
        return {"mapping_id": args.mapping_id, "active": False}
    if args.project_command == "reclassify":
        project_service.reclassify(args.session_id, args.mapping_id)
        return {"session_id": args.session_id, "mapping_id": args.mapping_id}
    raise ValueError(f"unsupported project command: {args.project_command}")


def _write_success(args, code: str, message: str, data) -> None:
    write_success(
        json_output=args.json_output, code=code, message=message, data=data
    )


def _write_operation_outcome(args, outcome) -> int:
    return write_operation_outcome(
        json_output=args.json_output, outcome=outcome
    )


def _run_purge_command(args: argparse.Namespace, service) -> int:
    if args.confirmed_operations and not args.purge_plan_id:
        raise IncompletePurgeConfirmation(
            "confirm-operation is valid only with apply-plan"
        )

    if args.purge_plan:
        plan = service.plan(args.knowledge_id)
        data = {
            "plan_id": plan.id,
            "purge_status": plan.status.value,
            "projection_status": "not_started",
            "operations": [
                {"id": operation.id, "kind": operation.location_kind}
                for operation in plan.operations
            ],
        }
        code = "RETRO_PURGE_PLANNED"
        message = "Read-only sensitive purge plan created."
        exit_code = 0
    else:
        if args.purge_recover:
            purge_status = service.recover(args.knowledge_id, actor="user")
            code = "RETRO_PURGE_RECOVERED"
            message = "Sensitive purge recovery completed."
        else:
            current = service.plan(args.knowledge_id)
            if current.id != args.purge_plan_id:
                raise StalePurgePlan("purge plan no longer matches current state")
            purge_status = service.apply(
                args.purge_plan_id,
                frozenset(args.confirmed_operations),
                actor="user",
            )
            code = "RETRO_PURGE_APPLIED"
            message = "Confirmed sensitive purge completed."
        projection = service.projection_result
        data = {
            "plan_id": args.purge_plan_id or "",
            "purge_status": purge_status.value,
            "projection_status": (
                projection.status.value if projection is not None else "not_started"
            ),
            "event_id": projection.event_id if projection is not None else "",
            "reason": projection.reason if projection is not None else "",
            "recovery_command": (
                projection.recovery_command if projection is not None else ""
            ),
        }
        exit_code = 0 if purge_status is PurgeStatus.PURGED else 2
        if exit_code:
            code = "RETRO_PURGE_INCOMPLETE"
            message = "Sensitive purge remains incomplete."

    if args.json_output:
        write_json(
            {
                "status": "ok" if exit_code == 0 else "error",
                "code": code,
                "message": message,
                "data": data,
            }
        )
    else:
        output = sys.stdout if exit_code == 0 else sys.stderr
        output.write(safe_text(json_text(data)) + "\n")
    return exit_code


def _write_capture_result(result: CaptureResult, json_output: bool) -> None:
    data = {
        "session_id": result.session_id,
        "captured": result.captured,
        "reused": result.reused,
        "warnings": list(result.warnings),
        "project_status": result.project_status,
    }
    if json_output:
        write_json(
            {
                "status": "ok",
                "code": "RETRO_CAPTURED",
                "message": "Codex session capture completed.",
                "data": data,
            }
        )

    if not json_output:
        action = "已复用" if result.reused else "已捕获"
        sys.stdout.write(
            safe_text(
                f"{action} Codex 会话 {result.session_id}；"
                f"项目状态: {result.project_status}"
            )
            + "\n"
        )


def _write_recent_capture_plan(result: RecentCapturePlan, json_output: bool) -> None:
    data = {
        "plan_id": result.plan_id,
        "schema_version": result.schema_version,
        "requested_count": result.requested_count,
        "recent_capture_max": result.recent_capture_max,
        "items": [
            {
                "session_id": item.session_id,
                "source_hash": item.source_hash,
                "resolution_status": item.resolution_status,
                "canonical_project_id": item.canonical_project_id,
                "mapping_id": item.mapping_id,
                "reuse_status": item.reuse_status,
            }
            for item in result.items
        ],
        "warnings": list(result.warnings),
    }
    if json_output:
        write_json(
            {
                "status": "ok",
                "code": "RETRO_CAPTURE_RECENT_PREVIEW",
                "message": "Recent capture plan previewed without writes.",
                "data": data,
            }
        )
    if not json_output:
        sys.stdout.write(safe_text(json_text(data)) + "\n")


def _write_recent_capture_result(
    result: RecentCaptureResult, json_output: bool
) -> None:
    def items(values):
        return [
            {"session_id": item.session_id, "reason": item.reason} for item in values
        ]

    data = {
        "plan_id": result.plan_id,
        "requested_count": result.requested_count,
        "captured": items(result.captured),
        "reused": items(result.reused),
        "failed": items(result.failed),
        "skipped": items(result.skipped),
        "recovery_command": result.recovery_command,
    }
    failed = bool(result.failed)
    if json_output:
        write_json(
            {
                "status": "error" if failed else "ok",
                "code": (
                    "RETRO_CAPTURE_RECENT_PARTIAL"
                    if failed
                    else "RETRO_CAPTURE_RECENT_APPLIED"
                ),
                "message": (
                    "Recent capture stopped after a per-session failure."
                    if failed
                    else "Recent capture plan applied."
                ),
                "data": data,
            }
        )
    else:
        stream = sys.stderr if failed else sys.stdout
        stream.write(safe_text(json_text(data)) + "\n")


def _build_review_service(settings, repository):
    legacy = load_legacy_model_config()
    model_value = legacy.get("model")
    if not isinstance(model_value, str) or not model_value.strip():
        raise RuntimeError("AgentRetro model is not configured.")
    model = model_value.strip()
    client = build_retro_llm_client_from_config(legacy)
    return ReviewService(
        repository,
        LLMExtractionGateway(client, model=model),
        LLMReviewGateway(client, model=model),
        model_timeout_seconds=effective_model_timeout(settings, legacy),
        redact=Redactor().redact,
    )


def _build_merge_planner(settings, repository):
    legacy = load_legacy_model_config()
    model_value = legacy.get("model")
    if not isinstance(model_value, str) or not model_value.strip():
        raise MergeProposalUnavailableError("merge_proposal_unavailable")
    model = model_value.strip()
    try:
        client = build_retro_llm_client_from_config(legacy)
    except Exception:
        raise MergeProposalUnavailableError("merge_proposal_unavailable") from None
    return MergePlanner(
        MergeService(repository, settings.obsidian_root, settings.backup_dir),
        settings.obsidian_root,
        LLMMergeProposalGateway(client, model=model),
        max_files=min(settings.discovery_max_files, 200),
        max_bytes=min(settings.session_max_bytes, 4 * 1024 * 1024),
        timeout_seconds=effective_model_timeout(settings, legacy),
        discovery_timeout_seconds=settings.discovery_timeout_seconds,
    )


def _datetime_argument(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("valid-until must be ISO-8601") from exc


def _mapping_data(mapping) -> dict[str, object]:
    return {
        "id": mapping.id,
        "mapping_kind": mapping.mapping_kind,
        "root": str(mapping.git_root),
        "git_root": str(mapping.git_root),
        "remote_identity": mapping.remote_identity,
        "obsidian_project": mapping.obsidian_project,
        "active": mapping.active,
    }


def _merge_plan_data(plan) -> dict[str, object]:
    from agent_retro.infrastructure.obsidian import sha256_bytes

    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "authority_hash": plan.authority_hash,
        "targets": [
            {
                "path": item.path.as_posix(),
                "input_hash": item.input_hash,
                "output_hash": sha256_bytes(item.output_bytes),
                "unified_diff": item.unified_diff,
            }
            for item in plan.targets
        ],
        "deletes": [
            {
                "operation_id": item.operation_id,
                "path": item.path.as_posix(),
                "input_hash": item.input_hash,
            }
            for item in plan.deletes
        ],
        "renames": [
            {
                "operation_id": item.operation_id,
                "source": item.source.as_posix(),
                "target": item.target.as_posix(),
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


def _guidance_preview_data(preview) -> dict[str, object]:
    return {
        "action": preview.action,
        "backup_location": (f"${{AGENTRETRO_BACKUP_DIR}}/{preview.id}/AGENTS.md"),
        "changed": preview.changed,
        "diff": preview.diff,
        "managed_hash": preview.managed_hash,
        "planned_hash": preview.planned_hash,
        "preview_id": preview.id,
        "target": "${CODEX_HOME}/AGENTS.md",
        "target_hash": preview.target_hash,
        "target_missing": preview.target_missing,
    }


def _boundary_init_plan_data(plan) -> dict[str, object]:
    return {
        "plan_id": plan.id,
        "project_id": plan.project_id,
        "changed": plan.changed,
        "backup_location": f"${{AGENTRETRO_BACKUP_DIR}}/{plan.id}",
        "targets": [
            {
                "path": target.relative_path.as_posix(),
                "kind": target.kind,
                "before_hash": target.before_hash,
                "after_hash": target.after_hash,
                "changed": target.changed,
                "diff": target.diff,
                "backup_path": (
                    f"${{AGENTRETRO_BACKUP_DIR}}/{plan.id}/"
                    f"{target.relative_path.as_posix()}"
                ),
            }
            for target in plan.targets
        ],
    }


def json_text(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _review_unavailable(session_id, project_id, evidence) -> None:
    raise RuntimeError("项目重分类将在 ReviewService 接入后开放")
