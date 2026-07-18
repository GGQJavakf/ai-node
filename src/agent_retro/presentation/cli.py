"""Independent AgentRetro command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Mapping

from agent_retro.application.bootstrap import build_retro_repository
from agent_retro.application.capture import CaptureResult, CaptureService
from agent_retro.infrastructure.codex_sessions import (
    CodexSessionSource,
    effective_codex_home,
)
from agent_retro.infrastructure.project_mapping import (
    ProjectMappingService,
    ProjectResolver,
)
from agent_retro.infrastructure.redaction import Redactor
from agent_retro.infrastructure.settings import load_retro_settings
from agent_retro.presentation.output import safe_text, write_json


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
    project_commands = project.add_subparsers(
        dest="project_command", required=True
    )
    map_command = project_commands.add_parser("map", help="创建项目映射")
    map_command.add_argument("--root", required=True, type=Path)
    map_command.add_argument("--vault-project", required=True)
    project_commands.add_parser("list", help="列出活动项目映射")
    remove = project_commands.add_parser("remove", help="停用项目映射")
    remove.add_argument("mapping_id")
    reclassify = project_commands.add_parser(
        "reclassify", help="使用已存证据重新分类会话"
    )
    reclassify.add_argument("session_id")
    reclassify.add_argument("mapping_id")
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
        except (OSError, RuntimeError, ValueError) as exc:
            if args.json_output:
                write_json(
                    {
                        "status": "error",
                        "code": "RETRO_COMMAND_FAILED",
                        "message": str(exc),
                        "data": {},
                    }
                )
            else:
                sys.stderr.write(safe_text(str(exc)) + "\n")
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
    resolver = ProjectResolver(repository.list_project_mappings())
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

    service = ProjectMappingService(
        repository, vault_root=settings.obsidian_root
    )
    if args.project_command == "map":
        mapping = service.map(args.root, args.vault_project)
        data = _mapping_data(mapping)
    elif args.project_command == "list":
        data = [_mapping_data(mapping) for mapping in service.list()]
    elif args.project_command == "remove":
        service.remove(args.mapping_id)
        data = {"mapping_id": args.mapping_id, "active": False}
    else:
        service.reclassify(args.session_id, args.mapping_id)
        data = {
            "session_id": args.session_id,
            "mapping_id": args.mapping_id,
            "reclassified": True,
        }
    if args.json_output:
        write_json(
            {
                "status": "ok",
                "code": "RETRO_PROJECT_UPDATED",
                "message": "Project mapping command completed.",
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
