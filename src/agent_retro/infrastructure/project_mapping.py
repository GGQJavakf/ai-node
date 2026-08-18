"""Git-backed project resolution and audited SQLite mapping lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence
from urllib.parse import unquote, urlsplit

from agent_retro.application.ports import RetroRepository
from agent_retro.domain.models import Evidence, ProjectMapping


class ProjectMappingError(ValueError):
    pass


class ProjectMappingConflictError(ProjectMappingError):
    pass


class UnsafeProjectPathError(ProjectMappingError):
    pass


class GitProjectError(ProjectMappingError):
    pass


@dataclass(frozen=True)
class ProjectResolution:
    status: str
    project_id: str = ""
    mapping_id: str = ""
    diagnostic: str = ""


def normalize_git_remote(remote: str) -> str:
    """Normalize HTTPS, SSH URL, and SCP-style remotes without credentials."""

    value = remote.strip()
    if not value:
        return ""
    scp_match = re.fullmatch(r"(?:[^@/:]+@)?([^/:]+):(.+)", value)
    if scp_match and "://" not in value:
        host = scp_match.group(1).lower()
        path = scp_match.group(2)
    elif "://" in value:
        parsed = urlsplit(value)
        if not parsed.hostname:
            raise GitProjectError("Git remote 缺少 host")
        host = parsed.hostname.lower()
        if parsed.port:
            host = f"{host}:{parsed.port}"
        path = unquote(parsed.path)
    else:
        # Already-normalized identities are accepted by the resolver.
        normalized = value.replace("\\", "/").strip("/")
        return normalized[:-4] if normalized.lower().endswith(".git") else normalized
    normalized_path = str(PurePosixPath(path.replace("\\", "/").lstrip("/")))
    if normalized_path.lower().endswith(".git"):
        normalized_path = normalized_path[:-4]
    if normalized_path in ("", ".") or normalized_path.startswith("../"):
        raise GitProjectError("Git remote 路径无效")
    return f"{host}/{normalized_path}"


def resolve_git_identity(path: Path) -> tuple[Path, str]:
    """Resolve the canonical Git root and sanitized origin identity."""

    supplied = Path(path).expanduser().resolve()
    try:
        root_result = subprocess.run(
            ["git", "-C", str(supplied), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise GitProjectError(f"不是可用的 Git 工作树: {supplied}") from exc
    root = Path(root_result.stdout.strip()).resolve()
    remote_result = subprocess.run(
        ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    remote = (
        normalize_git_remote(remote_result.stdout)
        if remote_result.returncode == 0
        else ""
    )
    return root, remote


class ProjectResolver:
    """Resolve a session project without guessing between mappings."""

    def __init__(self, mappings: Sequence[ProjectMapping]) -> None:
        self.mappings = tuple(mapping for mapping in mappings if mapping.active)

    def resolve(
        self,
        git_root: Path,
        remote_identity: str = "",
        *,
        source_path: Path | None = None,
    ) -> ProjectResolution:
        git_resolution = self._resolve_git(git_root, remote_identity)
        workspace_resolution = self._resolve_workspace(source_path)
        if "ambiguous" in (git_resolution.status, workspace_resolution.status):
            diagnostics = tuple(
                item.diagnostic
                for item in (git_resolution, workspace_resolution)
                if item.diagnostic
            )
            return ProjectResolution(
                status="ambiguous", diagnostic="；".join(diagnostics)
            )
        if git_resolution.status == workspace_resolution.status == "resolved":
            if git_resolution.project_id != workspace_resolution.project_id:
                return ProjectResolution(
                    status="ambiguous",
                    diagnostic="Git 映射与工作区映射指向不同项目",
                )
            return git_resolution
        if git_resolution.status == "resolved":
            return git_resolution
        if workspace_resolution.status == "resolved":
            return workspace_resolution
        return ProjectResolution(status="unknown", diagnostic="没有匹配的项目映射")

    def _resolve_git(
        self, git_root: Path, remote_identity: str = ""
    ) -> ProjectResolution:
        mappings = tuple(
            item for item in self.mappings if item.mapping_kind == "git"
        )
        root_key = _path_key(git_root)
        remote_key = normalize_git_remote(remote_identity) if remote_identity else ""
        exact = [
            item
            for item in mappings
            if _path_key(item.git_root) == root_key
            and item.remote_identity == remote_key
        ]
        resolution = self._from_candidates(exact, "Git root and remote")
        if resolution is not None:
            return resolution
        by_root = [
            item for item in mappings if _path_key(item.git_root) == root_key
        ]
        resolution = self._from_candidates(by_root, "Git root")
        if resolution is not None:
            return resolution
        by_remote = (
            [item for item in mappings if item.remote_identity == remote_key]
            if remote_key
            else []
        )
        resolution = self._from_candidates(by_remote, "Git remote")
        if resolution is not None:
            return resolution
        return ProjectResolution(status="unknown", diagnostic="没有匹配的项目映射")

    def _resolve_workspace(self, source_path: Path | None) -> ProjectResolution:
        if source_path is None:
            return ProjectResolution(status="unknown")
        source_key = _path_key(source_path)
        candidates = [
            item
            for item in self.mappings
            if item.mapping_kind == "workspace"
            and _path_contains(_path_key(item.git_root), source_key)
        ]
        if not candidates:
            return ProjectResolution(status="unknown")
        longest = max(len(_path_key(item.git_root)) for item in candidates)
        nearest = [
            item for item in candidates if len(_path_key(item.git_root)) == longest
        ]
        resolution = self._from_candidates(nearest, "工作区根目录")
        assert resolution is not None
        return resolution

    @staticmethod
    def _from_candidates(
        candidates: Sequence[ProjectMapping], source: str
    ) -> ProjectResolution | None:
        if not candidates:
            return None
        target_ids = {(item.id, item.obsidian_project) for item in candidates}
        if len(target_ids) != 1:
            return ProjectResolution(
                status="ambiguous", diagnostic=f"{source} 匹配多个项目映射"
            )
        mapping = candidates[0]
        return ProjectResolution(
            status="resolved",
            project_id=mapping.obsidian_project,
            mapping_id=mapping.id,
        )


ReviewStoredEvidence = Callable[[str, str, Sequence[Evidence]], None]


class ProjectMappingService:
    """Create and recover project mappings without reading session JSONL."""

    def __init__(
        self,
        repository: RetroRepository,
        *,
        vault_root: Path | None,
        review_stored_evidence: ReviewStoredEvidence,
    ) -> None:
        if not callable(review_stored_evidence):
            raise TypeError("review_stored_evidence callback is required")
        self.repository = repository
        self.vault_root = (
            Path(vault_root).expanduser().resolve() if vault_root else None
        )
        self.review_stored_evidence = review_stored_evidence

    def map(
        self, git_root: Path, obsidian_project: str, actor: str = "user"
    ) -> ProjectMapping:
        root, remote = resolve_git_identity(git_root)
        return self._save_mapping(root, remote, obsidian_project, "git", actor)

    def map_workspace(
        self, workspace_root: Path, obsidian_project: str, actor: str = "user"
    ) -> ProjectMapping:
        supplied = Path(workspace_root).expanduser()
        if not supplied.exists() or not supplied.is_dir():
            raise ProjectMappingError(f"工作区根目录不存在或不是目录: {supplied}")
        if supplied.is_symlink():
            raise ProjectMappingError(f"工作区根目录不能是符号链接: {supplied}")
        return self._save_mapping(
            supplied.resolve(), "", obsidian_project, "workspace", actor
        )

    def _save_mapping(
        self,
        root: Path,
        remote: str,
        obsidian_project: str,
        mapping_kind: str,
        actor: str,
    ) -> ProjectMapping:
        project = self._validated_project(obsidian_project)
        for existing in self.repository.list_project_mappings():
            same_root = _path_key(existing.git_root) == _path_key(root)
            same_remote = (
                mapping_kind == existing.mapping_kind == "git"
                and bool(remote)
                and existing.remote_identity == remote
            )
            if not (same_root or same_remote):
                continue
            if existing.obsidian_project == project:
                return existing
            raise ProjectMappingConflictError("项目根目录或 Git remote 已映射到不兼容的项目")
        identity = json.dumps(
            [mapping_kind, str(root), remote, project],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        mapping = ProjectMapping(
            id="mapping-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
            git_root=root,
            remote_identity=remote,
            obsidian_project=project,
            active=True,
            mapping_kind=mapping_kind,
        )
        self.repository.save_project_mapping(mapping, actor)
        return mapping

    def list(self) -> list[ProjectMapping]:
        # remote_identity is already transport- and credential-free.
        return self.repository.list_project_mappings()

    def remove(self, mapping_id: str, actor: str = "user") -> None:
        self.repository.deactivate_project_mapping(mapping_id, actor)

    def reclassify(self, session_id: str, mapping_id: str, actor: str = "user") -> None:
        mappings = {item.id: item for item in self.repository.list_project_mappings()}
        mapping = mappings.get(mapping_id)
        if mapping is None:
            raise ProjectMappingError(f"项目映射不存在或已停用: {mapping_id}")
        session = self.repository.find_session_by_source_id(session_id)
        if session is None:
            raise ProjectMappingError(f"会话不存在: {session_id}")
        if not session.project_id.startswith("awaiting:"):
            raise ProjectMappingConflictError(
                f"会话不在 awaiting classification 状态: {session_id}"
            )
        evidence = self.repository.list_evidence(session.id)
        self.review_stored_evidence(session_id, session.project_id, tuple(evidence))
        reclassification = self.repository.reclassify_session(
            session_id,
            mapping.obsidian_project,
            mapping.id,
            actor,
        )
        try:
            self.review_stored_evidence(
                session_id, mapping.obsidian_project, tuple(evidence)
            )
        except Exception as exc:
            self.repository.rollback_reclassification(
                reclassification,
                actor,
                affected_candidate_ids=getattr(exc, "candidate_ids", ()),
            )
            raise

    def _validated_project(self, obsidian_project: str) -> str:
        if self.vault_root is None:
            raise UnsafeProjectPathError("未配置 Obsidian vault root")
        if not obsidian_project or Path(obsidian_project).is_absolute():
            raise UnsafeProjectPathError("vault project 必须是非空相对路径")
        relative = Path(obsidian_project)
        if ".." in relative.parts:
            raise UnsafeProjectPathError("vault project 不能逃逸 vault root")
        cursor = self.vault_root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                raise UnsafeProjectPathError("vault project 不能经过符号链接")
        target = (self.vault_root / relative).resolve()
        try:
            target.relative_to(self.vault_root)
        except ValueError as exc:
            raise UnsafeProjectPathError("vault project 不能逃逸 vault root") from exc
        return relative.as_posix().strip("/")


def _path_key(path: Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _path_contains(root_key: str, child_key: str) -> bool:
    try:
        return os.path.commonpath((root_key, child_key)) == root_key
    except ValueError:
        return False
