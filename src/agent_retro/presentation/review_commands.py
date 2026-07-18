"""Review CLI dispatch and stable presentation-only serialization."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from agent_retro.application.knowledge import KnowledgeService
from agent_retro.application.ports import RetroRepository
from agent_retro.application.review import ReviewService, ReviewUnavailableError
from agent_retro.application.sync import ProjectionCoordinator, ProjectionResult
from agent_retro.domain.models import CandidateStatus, KnowledgeType
from agent_retro.infrastructure.settings import RetroSettings
from agent_retro.presentation.output import safe_text, write_json


ReviewServiceBuilder = Callable[[RetroSettings, RetroRepository], ReviewService]


def run_review_command(
    args: argparse.Namespace,
    settings: RetroSettings,
    repository: RetroRepository,
    *,
    build_review_service: ReviewServiceBuilder,
    projection_coordinator: ProjectionCoordinator | None = None,
) -> int:
    command = args.review_command
    if command == "list":
        if args.candidate_status:
            candidates = repository.list_candidates(
                CandidateStatus(args.candidate_status)
            )
        else:
            candidates = [
                candidate
                for status in CandidateStatus
                for candidate in repository.list_candidates(status)
            ]
            candidates.sort(key=lambda item: item.id)
        _write_result(
            args.json_output,
            code="RETRO_REVIEW_LISTED",
            message="Review candidates listed.",
            human=f"知识候选: {len(candidates)} 条",
            data={"candidates": [_candidate_data(item) for item in candidates]},
        )
        return 0
    if command == "show":
        candidate = repository.get_candidate(args.candidate_id)
        if candidate is None:
            raise KeyError(f"candidate not found: {args.candidate_id}")
        data = {
            "candidate": _candidate_data(candidate),
            "evidence": [
                _evidence_data(item)
                for item in repository.evidence_for_candidate(candidate.id)
            ],
            "review": _review_data(repository.get_review_result(candidate.id)),
        }
        _write_result(
            args.json_output,
            code="RETRO_REVIEW_SHOWN",
            message="Review candidate shown.",
            human=json.dumps(data, ensure_ascii=False, sort_keys=True),
            data=data,
        )
        return 0
    lifecycle = KnowledgeService(repository)
    if command == "accept":
        knowledge = lifecycle.accept(args.candidate_id, actor="user")
        projection = _project(
            projection_coordinator, "manual_accept", knowledge.id, knowledge.project_id
        )
        _write_result(
            args.json_output,
            code="RETRO_CANDIDATE_ACCEPTED",
            message="Knowledge candidate accepted.",
            human=f"已接受知识候选 {args.candidate_id}",
            data={**_knowledge_data(knowledge), "projection": projection},
        )
        return 0
    if command == "edit":
        knowledge = lifecycle.edit(
            args.candidate_id,
            text=args.text,
            actor="user",
            knowledge_type=(
                None
                if args.knowledge_type is None
                else KnowledgeType(args.knowledge_type)
            ),
            scope=args.scope,
            valid_until=args.valid_until,
        )
        projection = _project(
            projection_coordinator, "manual_edit", knowledge.id, knowledge.project_id
        )
        _write_result(
            args.json_output,
            code="RETRO_CANDIDATE_EDITED",
            message="Knowledge candidate edited and accepted.",
            human=f"已编辑并接受知识候选 {args.candidate_id}",
            data={**_knowledge_data(knowledge), "projection": projection},
        )
        return 0
    if command == "reject":
        candidate = lifecycle.reject(args.candidate_id, actor="user")
        _write_result(
            args.json_output,
            code="RETRO_CANDIDATE_REJECTED",
            message="Knowledge candidate rejected.",
            human=f"已拒绝知识候选 {args.candidate_id}",
            data=_candidate_data(candidate),
        )
        return 0
    if command == "merge":
        knowledge = lifecycle.resolve_conflict(
            args.conflict_id, text=args.text, actor="user"
        )
        projection = _project(
            projection_coordinator,
            "conflict_resolve",
            knowledge.id,
            knowledge.project_id,
        )
        _write_result(
            args.json_output,
            code="RETRO_CONFLICT_MERGED",
            message="Knowledge conflict merged.",
            human=f"已合并知识冲突 {args.conflict_id}",
            data={**_knowledge_data(knowledge), "projection": projection},
        )
        return 0
    if command == "promote":
        knowledge = lifecycle.promote_global(args.knowledge_id, actor="user")
        _write_result(
            args.json_output,
            code="RETRO_KNOWLEDGE_PROMOTED",
            message="Knowledge promoted globally.",
            human=f"已提升全局知识 {args.knowledge_id}",
            data=_knowledge_data(knowledge),
        )
        return 0
    if command == "archive":
        knowledge = lifecycle.archive(args.knowledge_id, actor="user")
        projection = _project(
            projection_coordinator, "archive", knowledge.id, knowledge.project_id
        )
        _write_result(
            args.json_output,
            code="RETRO_KNOWLEDGE_ARCHIVED",
            message="Knowledge archived.",
            human=f"已归档知识 {args.knowledge_id}",
            data={**_knowledge_data(knowledge), "projection": projection},
        )
        return 0
    if command in {"run", "retry"}:
        service = build_review_service(settings, repository)
        if command == "run":
            results = service.review_session(args.session_id)
            message = "Session review completed."
            code = "RETRO_REVIEW_COMPLETED"
            human = f"会话审核完成: {args.session_id}"
        elif args.retry_candidate_id:
            results = [service.retry_candidate(args.retry_candidate_id)]
            message = "Review retry completed."
            code = "RETRO_REVIEW_RETRIED"
            human = f"候选重试完成: {args.retry_candidate_id}"
        else:
            results = service.retry_session(args.retry_session_id)
            message = "Review retry completed."
            code = "RETRO_REVIEW_RETRIED"
            human = f"会话重试完成: {args.retry_session_id}"
        if any(result is None for result in results):
            raise ReviewUnavailableError(
                "model review failed; retry is available for stored candidates"
            )
        if command == "run":
            candidates = repository.candidates_for_session(args.session_id)
            cause_entity = args.session_id
        elif args.retry_candidate_id:
            candidate = repository.get_candidate(args.retry_candidate_id)
            candidates = [] if candidate is None else [candidate]
            cause_entity = args.retry_candidate_id
        else:
            candidates = repository.candidates_for_session(args.retry_session_id)
            cause_entity = args.retry_session_id
        projects = sorted(
            {
                knowledge.project_id
                for candidate in candidates
                if (knowledge := repository.knowledge_for_candidate(candidate.id))
                is not None
                and knowledge.status == "active"
            }
        )
        projections = [
            _project(projection_coordinator, "auto_accept", cause_entity, project)
            for project in projects
        ]
        _write_result(
            args.json_output,
            code=code,
            message=message,
            human=human,
            data={
                "results": [_review_data(item) for item in results],
                "projections": projections,
            },
        )
        return 0
    raise ValueError(f"unsupported review command: {command}")


def _write_result(
    json_output: bool,
    *,
    code: str,
    message: str,
    human: str,
    data: object,
) -> None:
    if json_output:
        write_json({"status": "ok", "code": code, "message": message, "data": data})
    else:
        sys.stdout.write(safe_text(human + _projection_human(data)) + "\n")


def _projection_human(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    projections: list[dict[str, object]] = []
    projection = data.get("projection")
    if isinstance(projection, dict):
        projections.append(projection)
    listed = data.get("projections")
    if isinstance(listed, list):
        projections.extend(item for item in listed if isinstance(item, dict))
    if not projections:
        return ""
    if all(item.get("status") == "synced" for item in projections):
        return "；SQLite 已提交；Obsidian vault 已验证同步。"
    blocked = next(item for item in projections if item.get("status") != "synced")
    return (
        "；SQLite 已提交，知识保持有效；"
        f"{blocked.get('warning', 'RETRO_SYNC_PENDING')}；"
        f"恢复命令: {blocked.get('recovery_command', '')}"
    )


def _candidate_data(candidate) -> dict[str, object]:
    return {
        "id": candidate.id,
        "knowledge_type": candidate.knowledge_type.value,
        "project_id": candidate.project_id,
        "scope": candidate.scope,
        "proposed_text": candidate.proposed_text,
        "evidence_ids": list(candidate.evidence_ids),
        "status": candidate.status.value,
        "extraction_confidence": candidate.extraction_confidence,
    }


def _evidence_data(evidence) -> dict[str, object]:
    return {
        "id": evidence.id,
        "session_id": evidence.session_id,
        "kind": evidence.kind,
        "excerpt": evidence.excerpt,
        "locator": {
            "session_id": evidence.locator.session_id,
            "event_id": evidence.locator.event_id,
            "source_path": evidence.locator.source_path,
            "content_hash": evidence.locator.content_hash,
        },
    }


def _review_data(review) -> dict[str, object] | None:
    if review is None:
        return None
    return {
        "verdict": review.verdict.value,
        "confidence": review.confidence,
        "reason": review.reason,
        "normalized_text": review.normalized_text,
        "duplicate_of": review.duplicate_of,
        "conflict_with": review.conflict_with,
    }


def _knowledge_data(knowledge) -> dict[str, object]:
    return {
        "id": knowledge.id,
        "version": knowledge.version,
        "candidate_id": knowledge.candidate_id,
        "knowledge_type": knowledge.knowledge_type.value,
        "project_id": knowledge.project_id,
        "scope": knowledge.scope,
        "text": knowledge.text,
        "status": knowledge.status,
        "confidence": knowledge.confidence,
        "accepted_by": knowledge.accepted_by,
        "evidence_ids": list(knowledge.evidence_ids),
        "valid_until": (
            None if knowledge.valid_until is None else knowledge.valid_until.isoformat()
        ),
        "updated_at": knowledge.updated_at.isoformat(),
        "supersedes": list(knowledge.supersedes),
    }


def _project(
    coordinator: ProjectionCoordinator | None,
    cause: str,
    entity_id: str,
    project_id: str,
) -> dict[str, object] | None:
    if coordinator is None:
        return None
    return _projection_data(coordinator.after_commit(cause, entity_id, project_id))


def _projection_data(result: ProjectionResult) -> dict[str, object]:
    return {
        "event_id": result.event_id,
        "status": result.status.value,
        "warning": result.warning,
        "recovery_command": result.recovery_command,
    }
