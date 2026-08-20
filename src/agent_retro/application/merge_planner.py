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
    canonical_merge_project_path,
    canonical_merge_path_identity,
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


class MergeProposalScopeError(ValueError):
    """A semantic proposal escaped its project Markdown boundary."""


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
        project_root = self._project_root(project_id)
        deadline = self.monotonic() + self.discovery_timeout_seconds
        paths = self._discover_markdown(project_root, deadline)
        documents = self._read_documents(project_root, paths, deadline)
        proposal = self._request_proposal(project_id, instruction, documents)
        return self._persist_plan(project_id, proposal)

    def _project_root(self, project_id: str) -> Path:
        try:
            project_part = canonical_merge_project_path(project_id)
        except ValueError as exc:
            raise ValueError("merge_planner_project_invalid") from exc
        if self.redactor.contains_sensitive_value(project_id):
            raise SensitiveMergeContentError("sensitive_merge_content")
        project_relative = Path("项目") / project_part
        project_root = self.vault_root / project_relative
        vault = self.vault_root.resolve(strict=True)
        try:
            project_root.resolve(strict=False).relative_to(vault)
        except ValueError as exc:
            raise ValueError("merge_planner_project_invalid") from exc
        current = self.vault_root
        for part in project_relative.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("merge_planner_unsafe_markdown")
        return project_root

    def _discover_markdown(self, project_root: Path, deadline: float) -> list[Path]:
        paths: list[Path] = []
        for path in project_root.rglob("*.md"):
            if self.monotonic() > deadline:
                raise ValueError("merge_planner_discovery_timeout")
            paths.append(path)
            if len(paths) > self.max_files:
                raise ValueError("merge_planner_input_limit")
        paths.sort(key=lambda item: item.as_posix())
        if not paths:
            raise ValueError("merge_planner_no_markdown")
        return paths

    def _read_documents(
        self, project_root: Path, paths: list[Path], deadline: float
    ) -> dict[str, str]:
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
        return documents

    def _request_proposal(
        self, project_id: str, instruction: str, documents: Mapping[str, str]
    ) -> MergeProposal:
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
        self._validate_proposal_scope(project_id, proposal)
        return proposal

    def _persist_plan(self, project_id: str, proposal: MergeProposal) -> MergePlan:
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

    def _validate_proposal_scope(
        self, project_id: str, proposal: MergeProposal
    ) -> None:
        paths = [*proposal.replacements, *proposal.deletes]
        for source, target in proposal.renames:
            paths.extend((source, target))
        try:
            project_path = canonical_merge_project_path(project_id)
            project_prefix = ("项目", *project_path.parts)
            expected = canonical_merge_path_identity(Path("项目") / project_path).split(
                "/"
            )
            vault = self.vault_root.resolve(strict=True)
            for raw_path in paths:
                path = Path(raw_path)
                if path.is_absolute() or not path.parts or ".." in path.parts:
                    raise ValueError
                if tuple(path.parts[: len(project_prefix)]) != project_prefix:
                    raise ValueError
                identity = canonical_merge_path_identity(path).split("/")
                if (
                    len(identity) <= len(expected)
                    or identity[: len(expected)] != expected
                    or ".obsidian" in identity
                    or not identity[-1].endswith(".md")
                ):
                    raise ValueError
                current = self.vault_root
                for part in path.parts:
                    current = current / part
                    if current.exists() and current.is_symlink():
                        raise ValueError
                (self.vault_root / path).resolve(strict=False).relative_to(vault)
        except (OSError, TypeError, ValueError):
            raise MergeProposalScopeError("merge_proposal_scope_invalid") from None
