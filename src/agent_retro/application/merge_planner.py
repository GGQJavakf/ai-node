"""Bounded semantic planning for preview-only deep Obsidian merges."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable, Mapping, Protocol

from agent_retro.application.merge import (
    MergePlan,
    MergeService,
    SensitiveMergeContentError,
)
from agent_retro.infrastructure.redaction import Redactor


@dataclass(frozen=True)
class MergeProposal:
    replacements: Mapping[Path, str]
    deletes: tuple[Path, ...]
    renames: tuple[tuple[Path, Path], ...]
    conflicts: tuple[str, ...]


class MergeProposalGateway(Protocol):
    def propose(
        self,
        project_id: str,
        instruction: str,
        documents: Mapping[str, str],
        *,
        timeout: int,
    ) -> MergeProposal: ...


class MergePlanner:
    """Discover bounded Markdown, redact it, and persist only a preview plan."""

    def __init__(
        self,
        merge_service: MergeService,
        vault_root: Path,
        gateway: MergeProposalGateway,
        *,
        max_files: int = 200,
        max_bytes: int = 4 * 1024 * 1024,
        timeout_seconds: int = 120,
        discovery_timeout_seconds: float = 10.0,
        monotonic: Callable[[], float] = monotonic,
    ) -> None:
        if (
            max_files <= 0
            or max_bytes <= 0
            or timeout_seconds <= 0
            or discovery_timeout_seconds <= 0
        ):
            raise ValueError("merge_planner_limits_invalid")
        self.merge_service = merge_service
        self.vault_root = Path(vault_root)
        self.gateway = gateway
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.discovery_timeout_seconds = discovery_timeout_seconds
        self.monotonic = monotonic
        self.redactor = Redactor()

    def plan(self, project_id: str, instruction: str) -> MergePlan:
        project_part = Path(project_id)
        if (
            not project_id.strip()
            or project_part.is_absolute()
            or len(project_part.parts) != 1
            or project_part.name != project_id
        ):
            raise ValueError("merge_planner_project_invalid")
        if self.redactor.contains_sensitive_value(project_id):
            raise SensitiveMergeContentError("sensitive_merge_content")
        project_root = self.vault_root / "项目" / project_id
        vault = self.vault_root.resolve(strict=True)
        try:
            project_root.resolve(strict=False).relative_to(vault)
        except ValueError as exc:
            raise ValueError("merge_planner_project_invalid") from exc
        if project_root.is_symlink():
            raise ValueError("merge_planner_unsafe_markdown")
        deadline = self.monotonic() + self.discovery_timeout_seconds
        paths = []
        for path in project_root.rglob("*.md"):
            if self.monotonic() > deadline:
                raise ValueError("merge_planner_discovery_timeout")
            paths.append(path)
            if len(paths) > self.max_files:
                raise ValueError("merge_planner_input_limit")
        paths.sort(key=lambda item: item.as_posix())
        if not paths:
            raise ValueError("merge_planner_no_markdown")
        documents: dict[str, str] = {}
        total_bytes = 0
        for path in paths:
            if self.monotonic() > deadline:
                raise ValueError("merge_planner_discovery_timeout")
            relative = path.relative_to(self.vault_root).as_posix()
            if self.redactor.contains_sensitive_value(relative):
                raise SensitiveMergeContentError("sensitive_merge_content")
            if path.is_symlink() or not path.is_file():
                raise ValueError("merge_planner_unsafe_markdown")
            try:
                path.resolve(strict=True).relative_to(project_root.resolve(strict=True))
            except ValueError as exc:
                raise ValueError("merge_planner_unsafe_markdown") from exc
            content = path.read_bytes()
            if self.monotonic() > deadline:
                raise ValueError("merge_planner_discovery_timeout")
            total_bytes += len(content)
            if total_bytes > self.max_bytes:
                raise ValueError("merge_planner_input_limit")
            try:
                text = content.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError("merge_planner_markdown_invalid") from exc
            documents[relative] = self.redactor.redact(text)
        proposal = self.gateway.propose(
            project_id,
            self.redactor.redact(instruction),
            documents,
            timeout=self.timeout_seconds,
        )
        if not isinstance(proposal, MergeProposal):
            raise ValueError("merge_planner_proposal_invalid")
        if not any(
            (
                proposal.replacements,
                proposal.deletes,
                proposal.renames,
                proposal.conflicts,
            )
        ):
            raise ValueError("merge_planner_empty_proposal")
        replacements = {
            Path(path): content.encode("utf-8")
            for path, content in proposal.replacements.items()
        }
        return self.merge_service.create_plan(
            project_id,
            replacements=replacements,
            deletes=proposal.deletes,
            renames=proposal.renames,
            conflicts=proposal.conflicts,
        )
