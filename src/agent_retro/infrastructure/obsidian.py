"""Deterministic, bounded Obsidian projection planning."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence

from agent_retro.domain.models import Knowledge, KnowledgeType


EMPTY_HASH = hashlib.sha256(b"").hexdigest()


class BoundaryError(ValueError):
    """A managed file does not contain one valid AgentRetro boundary."""


class UnsafeVaultPathError(ValueError):
    """A planned target is outside the configured vault boundary."""


class VaultNotConfiguredError(ValueError):
    """Obsidian projection is explicitly disabled until a root is configured."""


@dataclass(frozen=True)
class PlannedWrite:
    target: Path
    before_hash: str
    after_bytes: bytes
    before_managed_hash: str = ""
    after_managed_hash: str = ""
    ownership_kind: str = "full"


@dataclass(frozen=True)
class SyncPlan:
    id: str
    project_id: str
    writes: tuple[PlannedWrite, ...]
    backup_dir: Path
    event_id: str = ""
    input_hash: str = ""


_FILENAMES = {
    KnowledgeType.RULE: "规则.md",
    KnowledgeType.LESSON: "经验.md",
    KnowledgeType.TASK_STATE: "任务状态.md",
}
_START = re.compile(rb"<!-- agentretro:(summary|index):start project=([^>\r\n]+) -->")
_END = re.compile(rb"<!-- agentretro:(summary|index):end -->")
ManagedBoundaryKind = Literal["summary", "index"]


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def inspect_managed_boundary(
    content: bytes, project_id: str, kind: ManagedBoundaryKind
) -> bool:
    """Return whether one exact boundary exists, failing closed on marker drift."""

    try:
        content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BoundaryError("managed boundary target must be valid UTF-8") from exc
    starts = list(_START.finditer(content))
    ends = list(_END.finditer(content))
    marker_count = content.count(b"<!-- agentretro:")
    if not starts and not ends and marker_count == 0:
        return False
    if len(starts) != 1 or len(ends) != 1 or marker_count != 2:
        raise BoundaryError("managed boundary must contain exactly one start/end pair")
    start, end = starts[0], ends[0]
    expected_kind = kind.encode("ascii")
    if start.group(1) != expected_kind or end.group(1) != expected_kind:
        raise BoundaryError("managed boundary kind does not match target")
    try:
        marker_project = start.group(2).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BoundaryError("managed boundary project is not valid UTF-8") from exc
    if marker_project != project_id:
        raise BoundaryError("managed boundary project does not match mapping")
    if end.start() <= start.end():
        raise BoundaryError("managed boundary is nested or reversed")
    return True


def initialize_managed_boundary(
    content: bytes, project_id: str, kind: ManagedBoundaryKind
) -> bytes:
    """Append one empty boundary while preserving every existing input byte."""

    if inspect_managed_boundary(content, project_id, kind):
        return content
    newline = b"\r\n" if b"\r\n" in content else b"\n"
    if not content:
        separator = b""
    elif content.endswith(newline + newline):
        separator = b""
    elif content.endswith(newline):
        separator = newline
    else:
        separator = newline + newline
    block = (
        f"<!-- agentretro:{kind}:start project={project_id} -->".encode("utf-8")
        + newline
        + f"<!-- agentretro:{kind}:end -->".encode("utf-8")
        + newline
    )
    return content + separator + block


def replace_managed_block(content: bytes, project_id: str, inner: str) -> bytes:
    """Replace exactly one summary/index block and preserve surrounding bytes."""

    starts = list(_START.finditer(content))
    ends = list(_END.finditer(content))
    if len(starts) != 1 or len(ends) != 1:
        raise BoundaryError("managed boundary must contain exactly one start/end pair")
    start, end = starts[0], ends[0]
    if start.group(1) != end.group(1):
        raise BoundaryError("managed boundary kinds do not match")
    if start.group(2).decode("utf-8") != project_id:
        raise BoundaryError("managed boundary project does not match mapping")
    if end.start() <= start.end():
        raise BoundaryError("managed boundary is nested or reversed")
    newline = b"\r\n" if b"\r\n" in content else b"\n"
    rendered = inner.encode("utf-8").replace(b"\n", newline)
    middle = newline + rendered.rstrip(b"\r\n") + newline
    return content[: start.end()] + middle + content[end.start() :]


def managed_block_hash(content: bytes) -> str:
    starts = list(_START.finditer(content))
    ends = list(_END.finditer(content))
    if len(starts) != 1 or len(ends) != 1 or ends[0].start() <= starts[0].end():
        raise BoundaryError("managed boundary must contain exactly one ordered pair")
    return sha256_bytes(content[starts[0].end() : ends[0].start()])


def managed_block_bytes(content: bytes) -> bytes:
    starts = list(_START.finditer(content))
    ends = list(_END.finditer(content))
    if len(starts) != 1 or len(ends) != 1 or ends[0].start() <= starts[0].end():
        raise BoundaryError("managed boundary must contain exactly one ordered pair")
    return content[starts[0].end() : ends[0].start()]


def replace_managed_block_bytes(
    content: bytes, project_id: str, owned_bytes: bytes
) -> bytes:
    """Restore exact owned bytes while preserving the current surrounding prose."""

    starts = list(_START.finditer(content))
    ends = list(_END.finditer(content))
    if len(starts) != 1 or len(ends) != 1:
        raise BoundaryError("managed boundary must contain exactly one start/end pair")
    start, end = starts[0], ends[0]
    if start.group(1) != end.group(1) or end.start() <= start.end():
        raise BoundaryError("managed boundary kinds do not match")
    if start.group(2).decode("utf-8") != project_id:
        raise BoundaryError("managed boundary project does not match mapping")
    return content[: start.end()] + owned_bytes + content[end.start() :]


def parse_aggregate_entries(content: bytes) -> dict[str, str]:
    """Parse stable AgentRetro aggregate entries without interpreting prose."""

    text = content.decode("utf-8")
    headings = list(re.finditer(r"(?m)^### ([^\r\n]+)\r?$", text))
    entries: dict[str, str] = {}
    for index, heading in enumerate(headings):
        identifier = heading.group(1).strip()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end() : end]
        archived = re.search(r"(?m)^## 已归档\r?$", block)
        if archived is not None:
            block = block[: archived.start()]
        if identifier in entries:
            raise BoundaryError("aggregate contains a duplicate stable item id")
        lines = block.replace("\r\n", "\n").split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        separator = next(
            (offset for offset, line in enumerate(lines) if not line.strip()),
            None,
        )
        if separator is None:
            raise BoundaryError("aggregate item metadata is malformed")
        body = "\n".join(lines[separator + 1 :]).strip()
        entries[identifier] = body
    return entries


def render_aggregate(kind: KnowledgeType, items: Iterable[Knowledge]) -> bytes:
    """Render one complete aggregate from committed knowledge metadata."""

    title = _FILENAMES[kind].removesuffix(".md")
    ordered = sorted(items, key=lambda item: item.id)
    active = [item for item in ordered if item.status == "active"]
    archived = [item for item in ordered if item.status == "archived"]
    lines = [f"# {title}", ""]
    for item in active:
        lines.extend(_render_item(item))
    lines.extend(["## 已归档", ""])
    for item in archived:
        lines.extend(_render_item(item))
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


class ObsidianProjection:
    """Build immutable write plans; applying them belongs to SyncService."""

    def __init__(
        self, vault_root: Path | None, backup_root: Path | None = None
    ) -> None:
        self.vault_root = None if vault_root is None else Path(vault_root)
        self.backup_root = Path(backup_root) if backup_root is not None else None

    def plan(
        self,
        project_id: str,
        knowledge: Sequence[Knowledge],
        *,
        event_id: str | None = None,
        input_hash: str = "",
    ) -> SyncPlan:
        if self.vault_root is None:
            raise VaultNotConfiguredError("Obsidian vault is not configured")
        if self.backup_root is None:
            raise ValueError("AgentRetro backup root is not configured")
        project_root = self._safe_target(Path("项目") / project_id)
        grouped: dict[KnowledgeType, list[Knowledge]] = {}
        for item in knowledge:
            if item.project_id == project_id and item.scope == "project":
                grouped.setdefault(item.knowledge_type, []).append(item)
        writes: list[PlannedWrite] = []
        for kind in KnowledgeType:
            items = grouped.get(kind)
            if not items:
                continue
            target = self._safe_target(
                Path("项目") / project_id / "AgentRetro" / _FILENAMES[kind]
            )
            writes.append(self._write(target, render_aggregate(kind, items)))

        summary_inner = self._render_summary(grouped)
        optional = (
            (project_root / f"项目_{Path(project_id).name}.md", summary_inner),
            (self.vault_root / "项目" / "项目索引.md", f"- [[项目/{project_id}]]"),
        )
        for target, inner in optional:
            target = self._safe_existing_target(target)
            if target.exists():
                before = target.read_bytes()
                after = replace_managed_block(before, project_id, inner)
                writes.append(
                    PlannedWrite(
                        target,
                        sha256_bytes(before),
                        after,
                        managed_block_hash(before),
                        managed_block_hash(after),
                        "managed_block",
                    )
                )

        if event_id is not None:
            log = self._safe_target(
                Path("项目") / project_id / "AgentRetro" / "变更日志.md"
            )
            before = log.read_bytes() if log.exists() else b""
            key = f"<!-- agentretro:event={event_id} -->".encode()
            after = before
            if key not in before:
                prefix = b"" if not before or before.endswith(b"\n") else b"\n"
                after = before + prefix + key + b"\n"
            writes.append(self._write(log, after))

        identity = json.dumps(
            [
                project_id,
                [
                    [
                        str(write.target.relative_to(self.vault_root)),
                        write.before_hash,
                        sha256_bytes(write.after_bytes),
                    ]
                    for write in writes
                ],
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        plan_id = "sync-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        return SyncPlan(
            id=plan_id,
            project_id=project_id,
            writes=tuple(writes),
            backup_dir=self.backup_root / plan_id,
            event_id=event_id or "",
            input_hash=input_hash,
        )

    def _safe_existing_target(self, target: Path) -> Path:
        relative = target.relative_to(self.vault_root)
        return self._safe_target(relative)

    def _safe_target(self, relative: Path) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise UnsafeVaultPathError("vault target must be a contained relative path")
        root = self.vault_root.resolve()
        target = self.vault_root / relative
        current = self.vault_root
        for part in relative.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise UnsafeVaultPathError(f"unexpected symlink: {current}")
        try:
            target.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise UnsafeVaultPathError("vault target escapes configured root") from exc
        return target

    @staticmethod
    def _write(target: Path, after: bytes) -> PlannedWrite:
        before = target.read_bytes() if target.exists() else b""
        return PlannedWrite(
            target=target,
            before_hash=sha256_bytes(before),
            after_bytes=after,
            before_managed_hash=sha256_bytes(before),
            after_managed_hash=sha256_bytes(after),
        )

    @staticmethod
    def _render_summary(grouped: dict[KnowledgeType, list[Knowledge]]) -> str:
        lines = []
        for kind in KnowledgeType:
            count = sum(item.status == "active" for item in grouped.get(kind, []))
            lines.append(f"- {_FILENAMES[kind].removesuffix('.md')}: {count}")
        return "\n".join(lines)


def _render_item(item: Knowledge) -> list[str]:
    evidence = ", ".join(sorted(item.evidence_ids))
    return [
        f"### {item.id}",
        f"- ID: {item.id}",
        f"- 范围: {item.scope}",
        f"- 置信度: {item.confidence:.4f}",
        f"- 证据: {evidence}",
        f"- 版本: {item.version}",
        f"- 更新时间: {item.updated_at.isoformat()}",
        "",
        item.text,
        "",
    ]
