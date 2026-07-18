"""Deterministic, bounded Obsidian projection planning."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from agent_retro.domain.models import Knowledge, KnowledgeType


EMPTY_HASH = hashlib.sha256(b"").hexdigest()


class BoundaryError(ValueError):
    """A managed file does not contain one valid AgentRetro boundary."""


class UnsafeVaultPathError(ValueError):
    """A planned target is outside the configured vault boundary."""


@dataclass(frozen=True)
class PlannedWrite:
    target: Path
    before_hash: str
    after_bytes: bytes
    before_managed_hash: str = ""
    after_managed_hash: str = ""


@dataclass(frozen=True)
class SyncPlan:
    id: str
    project_id: str
    writes: tuple[PlannedWrite, ...]
    backup_dir: Path


_FILENAMES = {
    KnowledgeType.RULE: "规则.md",
    KnowledgeType.LESSON: "经验.md",
    KnowledgeType.TASK_STATE: "任务状态.md",
}
_START = re.compile(
    rb"<!-- agentretro:(summary|index):start project=([^>\r\n]+) -->"
)
_END = re.compile(rb"<!-- agentretro:(summary|index):end -->")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def replace_managed_block(content: bytes, project_id: str, inner: str) -> bytes:
    """Replace exactly one summary/index block and preserve surrounding bytes."""

    starts = list(_START.finditer(content))
    ends = list(_END.finditer(content))
    if len(starts) != 1 or len(ends) != 1:
        raise BoundaryError("managed boundary must contain exactly one start/end pair")
    start, end = starts[0], ends[0]
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


class ObsidianProjection:
    """Build immutable write plans; applying them belongs to SyncService."""

    def __init__(self, vault_root: Path, backup_root: Path | None = None) -> None:
        self.vault_root = Path(vault_root)
        self.backup_root = Path(backup_root or self.vault_root.parent / "backups")

    def plan(
        self,
        project_id: str,
        knowledge: Sequence[Knowledge],
        *,
        event_id: str | None = None,
    ) -> SyncPlan:
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
            writes.append(self._write(target, self._render(kind, items)))

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
                    [str(write.target.relative_to(self.vault_root)), write.before_hash,
                     sha256_bytes(write.after_bytes)]
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
    def _render(kind: KnowledgeType, items: Iterable[Knowledge]) -> bytes:
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
