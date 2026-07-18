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
    build_projection_coordinator,
    build_retro_repository,
)
from agent_retro.application.brief import (
    BriefBudgetError,
    BriefRequest,
    BriefService,
    BriefTimeoutError,
)
from agent_retro.application.merge import (
    ConfirmationRequiredError,
    MergeIntegrityError,
    MergeService,
    StalePlanError,
)
from agent_retro.application.merge_planner import MergePlanner
from agent_retro.application.sync import ProjectionPersistenceError
from agent_retro.application.capture import CaptureResult, CaptureService
from agent_retro.application.review import ReviewService, ReviewUnavailableError
from agent_retro.domain.models import CandidateStatus, KnowledgeType
from agent_retro.infrastructure.codex_sessions import (
    CodexSessionSource,
    effective_codex_home,
)
from agent_retro.infrastructure.codex_guidance import (
    CodexGuidance,
    GuidanceError,
    discover_managed_instruction,
)
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

    project = commands.add_parser("project", help="管理项目映射")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    map_command = project_commands.add_parser("map", help="创建项目映射")
    map_command.add_argument("--root", required=True, type=Path)
    map_command.add_argument("--vault-project", required=True)
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
        try:
            return _run_command(args, home=home, env=env)
        except BriefBudgetError as exc:
            data = {
                "max_tokens": exc.max_tokens,
                "reason": exc.reason,
                "required_tokens": exc.required_tokens,
            }
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_BRIEF_BUDGET_EXCEEDED",
                        "message": "Mandatory rules exceed the brief budget.",
                        "data": data,
                    }
                )
            else:
                sys.stderr.write(safe_text(json_text(data)) + "\n")
            return 2
        except BriefTimeoutError as exc:
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_BRIEF_DEADLINE_EXCEEDED",
                        "message": "Local brief rendering exceeded its deadline.",
                        "data": {"reason": exc.reason},
                    }
                )
            else:
                sys.stderr.write(safe_text(str(exc)) + "\n")
            return 2
        except GuidanceError as exc:
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_CODEX_INTEGRATION_FAILED",
                        "message": "Codex guidance integration failed safely.",
                        "data": {"reason": getattr(exc, "reason", "guidance_error")},
                    }
                )
            else:
                sys.stderr.write(
                    safe_text(getattr(exc, "reason", "guidance_error")) + "\n"
                )
            return 2
        except ReviewUnavailableError:
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_REVIEW_RETRYABLE",
                        "message": ("Model review is unavailable; retry is available."),
                        "data": {"retryable": True},
                    }
                )
            else:
                sys.stderr.write(safe_text("模型审核暂不可用；可安全重试。") + "\n")
            return 2
        except ProjectionPersistenceError as exc:
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_SYNC_STATE_UNAVAILABLE",
                        "message": "Projection state is unavailable; SQLite knowledge remains authoritative.",
                        "data": {
                            "reason": exc.reason,
                            "recovery_command": exc.recovery_command,
                        },
                    }
                )
            else:
                sys.stderr.write(
                    safe_text(
                        "SQLite 知识保持权威；"
                        f"{exc.reason}；恢复命令: {exc.recovery_command}"
                    )
                    + "\n"
                )
            return 2
        except ConfirmationRequiredError as exc:
            data = {
                "missing_operation_ids": list(exc.missing_operation_ids),
                "recovery_command": "retro merge preview <plan-id>",
            }
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_MERGE_CONFIRMATION_REQUIRED",
                        "message": "Exact merge confirmation is required.",
                        "data": data,
                    }
                )
            else:
                sys.stderr.write(safe_text(json_text(data)) + "\n")
            return 2
        except StalePlanError:
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_MERGE_PLAN_STALE",
                        "message": "Merge plan inputs changed; create a new plan.",
                        "data": {},
                    }
                )
            else:
                sys.stderr.write(safe_text("合并计划已过期，请重新生成。") + "\n")
            return 2
        except MergeIntegrityError:
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_MERGE_PLAN_INVALID",
                        "message": "Merge plan integrity validation failed.",
                        "data": {},
                    }
                )
            else:
                sys.stderr.write(safe_text("合并计划完整性校验失败。") + "\n")
            return 2
        except MergeProposalUnavailableError:
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_MERGE_MODEL_UNAVAILABLE",
                        "message": "Semantic merge model is unavailable.",
                        "data": {"retryable": True},
                    }
                )
            else:
                sys.stderr.write(safe_text("语义合并模型暂不可用；可安全重试。") + "\n")
            return 2
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            detail = Redactor().redact(str(exc))
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_COMMAND_FAILED",
                        "message": "AgentRetro command failed.",
                        "data": {"detail": detail},
                    }
                )
            else:
                sys.stderr.write(safe_text(detail) + "\n")
            return 2
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

    if args.command == "doctor":
        report = build_doctor_service(
            settings, codex_home, load_legacy_model_config
        ).run()
        data = doctor_json_data(report)
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
                    "data": data,
                }
            )
        else:
            sys.stdout.write(safe_text(render_doctor_terminal(report)))
        return report.exit_code

    if args.command == "integrate":
        guidance = CodexGuidance(codex_home, settings.backup_dir)
        action = (
            "remove"
            if args.integrate_remove
            else "apply"
            if args.integrate_apply
            else "preview"
        )
        preview = (
            guidance.preview_remove() if action == "remove" else guidance.preview()
        )
        data = _guidance_preview_data(preview)
        data["override_conflict"] = (codex_home / "AGENTS.override.md").exists() or (
            codex_home / "AGENTS.override.md"
        ).is_symlink()
        if action != "preview":
            result = (
                guidance.remove(preview.id)
                if action == "remove"
                else guidance.apply(preview.id)
            )
            data.update(
                {
                    "changed": result.changed,
                    "result_status": result.status,
                    "target_hash": result.target_hash,
                }
            )
            if action == "apply":
                data["discoverable"] = discover_managed_instruction(codex_home)
        code = {
            "preview": "RETRO_CODEX_INTEGRATION_PREVIEW",
            "apply": "RETRO_CODEX_INTEGRATION_APPLIED",
            "remove": "RETRO_CODEX_INTEGRATION_REMOVED",
        }[action]
        if args.json_output:
            write_json(
                {
                    "status": "ok",
                    "code": code,
                    "message": "Codex guidance integration command completed.",
                    "data": data,
                }
            )
        else:
            sys.stdout.write(safe_text(json_text(data)) + "\n")
        return 0

    repository = build_retro_repository(settings)
    if args.command == "brief":
        result = BriefService(
            repository,
            timeout_seconds=settings.brief_timeout_seconds,
            default_max_tokens=settings.brief_max_tokens,
        ).build(
            BriefRequest(
                task=args.task,
                project_id=args.project_id,
                max_tokens=args.max_tokens,
            )
        )
        if args.json_output:
            write_json(
                {
                    "status": "ok",
                    "code": "RETRO_BRIEF_READY",
                    "message": "Task-scoped brief generated.",
                    "data": brief_json_data(result),
                }
            )
        elif args.markdown:
            sys.stdout.write(safe_text(render_brief_markdown(result)))
        else:
            sys.stdout.write(safe_text(render_brief_terminal(result)))
        return 0

    coordinator = build_projection_coordinator(settings, repository)
    resolver = ProjectResolver(repository.list_project_mappings())
    if args.command == "sync":
        if args.sync_command == "retry":
            result = coordinator.retry(args.event_id)
            data = {
                "event_id": result.event_id,
                "projection_status": result.status.value,
                "warning": result.warning,
                "recovery_command": result.recovery_command,
                "reason": result.reason,
            }
            code = "RETRO_SYNC_RETRIED"
            message = "Obsidian projection retry completed."
        else:
            merge_service = MergeService(
                repository,
                settings.obsidian_root,
                settings.backup_dir,
            )
            if args.sync_command == "conflicts":
                conflicts = merge_service.find_external_edits(args.project_id)
                data = {
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
                }
                code = "RETRO_SYNC_CONFLICTS"
                message = "Obsidian external-edit conflicts inspected."
            else:
                reconciled = merge_service.reconcile(
                    args.conflict_id, args.action, actor="user"
                )
                data = {
                    "conflict_id": reconciled.conflict_id,
                    "status": reconciled.status,
                    "candidate_id": reconciled.candidate_id,
                    "plan_id": reconciled.plan_id,
                }
                code = "RETRO_SYNC_RECONCILED"
                message = "Obsidian external edit reconciliation recorded."
        if args.json_output:
            write_json(
                {
                    "status": "ok",
                    "code": code,
                    "message": message,
                    "data": data,
                }
            )
        else:
            sys.stdout.write(safe_text(json_text(data)) + "\n")
        return 0
    if args.command == "merge":
        merge_service = MergeService(
            repository,
            settings.obsidian_root,
            settings.backup_dir,
        )
        if args.merge_command == "plan":
            plan = _build_merge_planner(settings, repository).plan(
                args.project_id, args.instruction
            )
            data = _merge_plan_data(plan)
            code = "RETRO_MERGE_PLANNED"
            message = "Preview-only semantic merge plan created."
        elif args.merge_command == "preview":
            plan = merge_service.preview(args.plan_id)
            data = _merge_plan_data(plan)
            code = "RETRO_MERGE_PREVIEW"
            message = "Current complete merge plan preview."
        else:
            result = merge_service.apply(
                args.plan_id,
                confirmed=args.merge_confirmed,
                confirmed_operations=tuple(args.confirmed_operations),
            )
            data = {
                "plan_id": result.plan_id,
                "status": result.status,
                "reason": result.reason,
            }
            code = "RETRO_MERGE_APPLIED"
            message = "Confirmed merge apply completed."
        if args.json_output:
            write_json(
                {
                    "status": "ok",
                    "code": code,
                    "message": message,
                    "data": data,
                }
            )
        else:
            sys.stdout.write(safe_text(json_text(data)) + "\n")
        return 0
    if args.command == "capture":
        source = CodexSessionSource(
            effective_codex_home(home=home, env=values),
            max_candidates=settings.discovery_max_files,
            discovery_timeout_seconds=settings.discovery_timeout_seconds,
            max_session_bytes=settings.session_max_bytes,
        )
        service = CaptureService(source, repository, Redactor(), resolver)
        result = (
            service.capture_last()
            if args.capture_last
            else service.capture_session(args.session_id)
        )
        _write_capture_result(result, args.json_output)
        return 0

    if args.command == "review":
        return run_review_command(
            args,
            settings,
            repository,
            build_review_service=_build_review_service,
            projection_coordinator=coordinator,
        )

    review_stored_evidence = _review_unavailable
    if args.project_command == "reclassify":
        review_stored_evidence = _build_review_service(
            settings, repository
        ).review_stored_evidence
    service = ProjectMappingService(
        repository,
        vault_root=settings.obsidian_root,
        review_stored_evidence=review_stored_evidence,
    )
    if args.project_command == "map":
        mapping = service.map(args.root, args.vault_project)
        data = _mapping_data(mapping)
    elif args.project_command == "list":
        data = [_mapping_data(mapping) for mapping in service.list()]
    elif args.project_command == "remove":
        service.remove(args.mapping_id)
        data = {"mapping_id": args.mapping_id, "active": False}
    elif args.project_command == "reclassify":
        service.reclassify(args.session_id, args.mapping_id)
        data = {
            "session_id": args.session_id,
            "mapping_id": args.mapping_id,
        }
    else:
        raise ValueError(f"unsupported project command: {args.project_command}")
    if args.json_output:
        write_json(
            {
                "status": "ok",
                "code": "RETRO_PROJECT_UPDATED",
                "message": (
                    "Project session reclassified."
                    if args.project_command == "reclassify"
                    else "Project mapping command completed."
                ),
                "data": data,
            }
        )
    else:
        sys.stdout.write(safe_text(json_text(data)) + "\n")
    return 0


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
    else:
        action = "已复用" if result.reused else "已捕获"
        sys.stdout.write(
            safe_text(
                f"{action} Codex 会话 {result.session_id}；"
                f"项目状态: {result.project_status}"
            )
            + "\n"
        )


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


def json_text(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _review_unavailable(session_id, project_id, evidence) -> None:
    raise RuntimeError("项目重分类将在 ReviewService 接入后开放")
