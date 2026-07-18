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
    build_projection_coordinator,
    build_retro_repository,
)
from agent_retro.application.capture import CaptureResult, CaptureService
from agent_retro.application.review import ReviewService, ReviewUnavailableError
from agent_retro.domain.models import CandidateStatus, KnowledgeType
from agent_retro.infrastructure.codex_sessions import (
    CodexSessionSource,
    effective_codex_home,
)
from agent_retro.infrastructure.legacy_model import (
    build_retro_llm_client_from_config,
    load_legacy_model_config,
)
from agent_retro.infrastructure.llm_review import (
    LLMExtractionGateway,
    LLMReviewGateway,
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
from agent_retro.presentation.output import safe_text, write_json
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
    repository = build_retro_repository(settings)
    coordinator = build_projection_coordinator(settings, repository)
    resolver = ProjectResolver(repository.list_project_mappings())
    if args.command == "sync":
        result = coordinator.retry(args.event_id)
        data = {
            "event_id": result.event_id,
            "projection_status": result.status.value,
            "warning": result.warning,
            "recovery_command": result.recovery_command,
            "reason": result.reason,
        }
        if args.json_output:
            write_json(
                {
                    "status": "ok",
                    "code": "RETRO_SYNC_RETRIED",
                    "message": "Obsidian projection retry completed.",
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


def json_text(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _review_unavailable(session_id, project_id, evidence) -> None:
    raise RuntimeError("项目重分类将在 ReviewService 接入后开放")
