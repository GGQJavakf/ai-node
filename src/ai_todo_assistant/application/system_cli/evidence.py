"""Evidence helpers for safe system CLI command execution."""
from __future__ import annotations

import shlex
from dataclasses import dataclass

from ai_todo_assistant.application.ports.workflow_repository import WorkflowRepository
from ai_todo_assistant.application.system_cli.models import CommandExecutionRecord
from ai_todo_assistant.application.workflow import EvidenceService
from ai_todo_assistant.domain.workflow import Evidence, EvidenceType


SYSTEM_CLI_EVIDENCE_SOURCE = "system-cli"


@dataclass(frozen=True)
class SystemCliEvidenceResult:
    evidence: Evidence
    created: bool


def command_text(record: CommandExecutionRecord) -> str:
    if record.argv:
        return shlex.join(record.argv)
    return record.command_key


def evidence_output_excerpt(record: CommandExecutionRecord) -> str:
    return record.stdout_excerpt or record.stderr_excerpt


def evidence_summary(record: CommandExecutionRecord) -> str:
    outcome = "succeeded" if record.success else "failed"
    return f"system_cli {record.command_key} {outcome} (exit_code={record.returncode})"


def record_system_cli_evidence(
    repository: WorkflowRepository,
    work_item_id: str,
    record: CommandExecutionRecord,
) -> SystemCliEvidenceResult:
    command = command_text(record)
    output_excerpt = evidence_output_excerpt(record)
    for existing in repository.list_evidence(work_item_id):
        if (
            existing.evidence_type == EvidenceType.COMMAND.value
            and existing.source == SYSTEM_CLI_EVIDENCE_SOURCE
            and existing.command == command
            and existing.output_excerpt == output_excerpt
            and existing.success == record.success
        ):
            return SystemCliEvidenceResult(existing, created=False)
    evidence = EvidenceService(repository).record(
        work_item_id,
        EvidenceType.COMMAND.value,
        evidence_summary(record),
        command=command,
        output_excerpt=output_excerpt,
        success=record.success,
        source=SYSTEM_CLI_EVIDENCE_SOURCE,
    )
    return SystemCliEvidenceResult(evidence, created=True)
