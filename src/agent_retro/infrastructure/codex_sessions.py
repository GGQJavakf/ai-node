"""Bounded, fail-closed parsing of completed local Codex sessions."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from agent_retro.domain.models import (
    NormalizedEvent,
    NormalizedSession,
    SourceLocator,
)


class CodexSessionError(RuntimeError):
    """Base error for local Codex session ingestion."""


class SessionNotFoundError(CodexSessionError):
    pass


class IncompleteSessionError(CodexSessionError):
    pass


class SessionFormatError(CodexSessionError):
    pass


class SessionSizeLimitError(CodexSessionError):
    pass


class SessionDiscoveryTimeout(CodexSessionError):
    pass


@dataclass(frozen=True)
class DiscoveryDiagnostics:
    inspected_count: int = 0
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SessionCandidate:
    path: Path
    size: int


_SESSION_PATH_PATTERN = re.compile(
    r"^rollout-"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-"
    r"(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$",
    re.IGNORECASE,
)


def effective_codex_home(
    *, home: Path | None = None, env: Mapping[str, str] | None = None
) -> Path:
    """Return the effective local Codex home without touching it."""

    environment = os.environ if env is None else env
    configured = environment.get("CODEX_HOME")
    base = Path.home() if home is None else Path(home)
    return Path(configured if configured else base / ".codex").expanduser().resolve()


class CodexSessionSource:
    """Read one versioned JSONL session from an injected Codex home."""

    def __init__(
        self,
        codex_home: Path,
        *,
        max_candidates: int = 1000,
        discovery_timeout_seconds: float = 10.0,
        max_session_bytes: int = 128 * 1024 * 1024,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_candidates <= 0:
            raise ValueError("max_candidates must be positive")
        if discovery_timeout_seconds <= 0:
            raise ValueError("discovery_timeout_seconds must be positive")
        if max_session_bytes <= 0:
            raise ValueError("max_session_bytes must be positive")
        self.codex_home = Path(codex_home).expanduser().resolve()
        self.max_candidates = max_candidates
        self.discovery_timeout_seconds = discovery_timeout_seconds
        self.max_session_bytes = max_session_bytes
        self.monotonic = monotonic
        self.last_discovery = DiscoveryDiagnostics()
        self._warnings: list[str] = []
        self._diagnostics: list[str] = []
        self._inspected_count = 0

    def latest_completed(self) -> NormalizedSession:
        self._begin_discovery()
        deadline = self.monotonic() + self.discovery_timeout_seconds
        try:
            self._require_home(deadline)
            candidates = self._session_candidates_newest_first(deadline)
            for candidate in candidates:
                self._check_deadline(deadline)
                try:
                    session = self._parse_bounded(candidate, deadline)
                except SessionDiscoveryTimeout:
                    raise
                except CodexSessionError as exc:
                    self._diagnostics.append(f"跳过 {candidate.path}: {exc}")
                    continue
                if session.completed:
                    self._finish_discovery()
                    return session
                self._diagnostics.append(
                    f"跳过未完成会话 {session.source_session_id}: {candidate.path}"
                )
        except BaseException:
            self._finish_discovery()
            raise
        self._finish_discovery()
        raise SessionNotFoundError("未找到已完成的 Codex 会话")

    def load(self, session_id: str) -> NormalizedSession:
        if not session_id or not session_id.strip():
            raise SessionNotFoundError("Codex 会话 ID 不能为空")
        self._begin_discovery()
        deadline = self.monotonic() + self.discovery_timeout_seconds
        try:
            self._require_home(deadline)
            candidates = self._session_candidates_newest_first(deadline)
            session = self._load_candidate(session_id, candidates, deadline)
        except BaseException:
            self._finish_discovery()
            raise
        self._finish_discovery()
        if not session.completed:
            raise IncompleteSessionError(f"Codex 会话仍在进行: {session_id}")
        return session

    def _load_candidate(
        self,
        session_id: str,
        candidates: list[_SessionCandidate],
        deadline: float,
    ) -> NormalizedSession:
        aliases = {session_id, session_id.removeprefix("session-")}
        self._check_deadline(deadline)
        direct = [
            candidate
            for candidate in candidates
            if candidate.path.stem in aliases or session_id in candidate.path.stem
        ]
        self._check_deadline(deadline)
        for candidate in direct:
            session = self._parse_bounded(candidate, deadline)
            if session.source_session_id == session_id:
                return session
            self._diagnostics.append(f"跳过 ID 不匹配会话 {candidate.path}")
        for candidate in candidates:
            if candidate in direct:
                continue
            self._check_size(candidate)
            if self._peek_session_id(candidate, deadline) == session_id:
                return self._parse_bounded(candidate, deadline)
        raise SessionNotFoundError(f"未找到 Codex 会话: {session_id}")

    def _check_deadline(self, deadline: float) -> None:
        if self.monotonic() >= deadline:
            message = "会话发现超过配置时限"
            if message not in self._diagnostics:
                self._diagnostics.append(message)
            raise SessionDiscoveryTimeout(message)

    def _require_home(self, deadline: float) -> None:
        self._check_deadline(deadline)
        available = self.codex_home.is_dir()
        self._check_deadline(deadline)
        if not available:
            raise SessionNotFoundError(f"Codex 会话源不可用: {self.codex_home}")

    def _session_candidates_newest_first(
        self, deadline: float
    ) -> list[_SessionCandidate]:
        directories = [self.codex_home / "sessions"]
        newest: list[tuple[tuple[str, str], str, Path]] = []
        while directories:
            self._check_deadline(deadline)
            directory = directories.pop(0)
            try:
                with os.scandir(directory) as entries:
                    self._check_deadline(deadline)
                    child_directories: list[Path] = []
                    for entry in entries:
                        self._check_deadline(deadline)
                        entry_path = Path(entry.path)
                        try:
                            is_symlink = entry.is_symlink()
                            self._check_deadline(deadline)
                            if is_symlink:
                                self._diagnostics.append(
                                    f"跳过符号链接 Codex 会话来源 {entry_path}"
                                )
                                continue
                            is_directory = entry.is_dir(follow_symlinks=False)
                            self._check_deadline(deadline)
                            if is_directory:
                                child_directories.append(entry_path)
                                continue
                            if not entry.name.lower().endswith(".jsonl"):
                                continue
                            recency_key = self._trusted_recency_key(entry_path)
                            if recency_key is None:
                                continue
                            discovered = (
                                recency_key,
                                str(entry_path),
                                entry_path,
                            )
                            if len(newest) < self.max_candidates:
                                heapq.heappush(newest, discovered)
                            elif discovered > newest[0]:
                                skipped = heapq.heapreplace(newest, discovered)
                                self._diagnostics.append(
                                    "跳过超出最新候选数量限制 "
                                    f"{self.max_candidates} 的 Codex 会话 "
                                    f"{skipped[2]}"
                                )
                            else:
                                self._diagnostics.append(
                                    "跳过超出最新候选数量限制 "
                                    f"{self.max_candidates} 的 Codex 会话 "
                                    f"{entry_path}"
                                )
                        except OSError as exc:
                            self._diagnostics.append(
                                f"跳过无法检查路径 {entry_path}: {exc}"
                            )
                    child_directories.sort(
                        key=lambda item: (item.name, str(item)), reverse=True
                    )
                    self._check_deadline(deadline)
                    directories[0:0] = child_directories
            except OSError as exc:
                self._diagnostics.append(f"跳过无法枚举目录 {directory}: {exc}")
        self._check_deadline(deadline)
        candidates: list[_SessionCandidate] = []
        for _, _, path in sorted(newest, reverse=True):
            self._check_deadline(deadline)
            try:
                stat = path.stat()
                self._check_deadline(deadline)
            except OSError as exc:
                self._diagnostics.append(f"跳过无法检查路径 {path}: {exc}")
                continue
            candidates.append(
                _SessionCandidate(
                    path=path,
                    size=stat.st_size,
                )
            )
        self._inspected_count = len(candidates)
        return candidates

    def _trusted_recency_key(self, path: Path) -> tuple[str, str] | None:
        try:
            relative = path.relative_to(self.codex_home)
        except ValueError:
            relative = path
        parts = relative.parts
        match = _SESSION_PATH_PATTERN.fullmatch(path.name)
        expected_shape = len(parts) == 5 and parts[0].lower() == "sessions"
        if match is None or not expected_shape:
            self._diagnostics.append(
                "跳过非规范 Codex 会话路径 "
                f"{path}: 需要 sessions/YYYY/MM/DD/"
                "rollout-YYYY-MM-DDTHH-MM-SS-<uuid>.jsonl"
            )
            return None
        timestamp = match.group("timestamp")
        try:
            datetime.strptime(timestamp, "%Y-%m-%dT%H-%M-%S")
        except ValueError:
            self._diagnostics.append(
                f"跳过非规范 Codex 会话路径 {path}: 文件名时间无效"
            )
            return None
        if parts[1:4] != (
            timestamp[0:4],
            timestamp[5:7],
            timestamp[8:10],
        ):
            self._diagnostics.append(
                f"跳过非规范 Codex 会话路径 {path}: 目录日期与文件名不一致"
            )
            return None
        return timestamp, match.group("uuid").lower()

    def _begin_discovery(self) -> None:
        self._warnings = []
        self._diagnostics = []
        self._inspected_count = 0
        self.last_discovery = DiscoveryDiagnostics()

    def _finish_discovery(self) -> None:
        self.last_discovery = DiscoveryDiagnostics(
            inspected_count=self._inspected_count,
            warnings=tuple(self._warnings),
            diagnostics=tuple(self._diagnostics),
        )

    def _peek_session_id(
        self, candidate: _SessionCandidate, deadline: float
    ) -> str | None:
        self._check_size(candidate)
        self._check_deadline(deadline)
        try:
            with candidate.path.open("r", encoding="utf-8") as stream:
                self._check_deadline(deadline)
                while True:
                    line = self._readline_with_deadline(stream, deadline)
                    if line == "":
                        break
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    self._check_deadline(deadline)
                    if value.get("type") != "session_meta":
                        return None
                    payload = value.get("payload")
                    return payload.get("id") if isinstance(payload, dict) else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return None

    def _readline_with_deadline(self, stream, deadline: float):
        self._check_deadline(deadline)
        line = stream.readline()
        self._check_deadline(deadline)
        return line

    def _check_size(self, candidate: _SessionCandidate) -> None:
        if candidate.size > self.max_session_bytes:
            raise SessionSizeLimitError(
                f"Codex 会话超过 {self.max_session_bytes} 字节限制: {candidate.path}"
            )

    def _parse_bounded(
        self, candidate: _SessionCandidate, deadline: float
    ) -> NormalizedSession:
        self._check_size(candidate)
        self._check_deadline(deadline)
        return self._parse(candidate.path, deadline)

    def _parse(self, path: Path, deadline: float) -> NormalizedSession:
        digest = hashlib.sha256()
        session_id: str | None = None
        project_id: str | None = None
        completion_state: bool | None = None
        completed_at: datetime | None = None
        events: list[NormalizedEvent] = []
        saw_meta = False
        try:
            with path.open("rb") as stream:
                self._check_deadline(deadline)
                line_number = 0
                while True:
                    raw_line = self._readline_with_deadline(stream, deadline)
                    if raw_line == b"":
                        break
                    line_number += 1
                    digest.update(raw_line)
                    if not raw_line.strip():
                        continue
                    try:
                        record = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError) as exc:
                        raise SessionFormatError(
                            f"无效 JSONL，行 {line_number}: {path}"
                        ) from exc
                    if not isinstance(record, dict):
                        raise SessionFormatError(
                            f"JSONL 记录必须是对象，行 {line_number}: {path}"
                        )
                    self._check_deadline(deadline)
                    version = record.get("version")
                    if version not in (None, 1, "1"):
                        raise SessionFormatError(
                            f"不支持的 Codex 会话版本 {version}: {path}"
                        )
                    record_type = record.get("type")
                    payload = record.get("payload")
                    if not isinstance(payload, dict):
                        raise SessionFormatError(
                            f"缺少事件 payload，行 {line_number}: {path}"
                        )
                    if record_type == "session_meta":
                        if saw_meta:
                            raise SessionFormatError(f"重复 session_meta: {path}")
                        saw_meta = True
                        session_id = _required_text(payload.get("id"), "session ID")
                        project_id = _required_text(
                            payload.get("cwd"), "session source locator"
                        )
                        completed_at = _parse_timestamp(record.get("timestamp"))
                        continue
                    if not saw_meta or session_id is None:
                        raise SessionFormatError(
                            f"事件出现在 session_meta 之前，行 {line_number}: {path}"
                        )
                    normalized = self._normalize_event(
                        record_type,
                        payload,
                        record.get("timestamp"),
                        session_id,
                        path,
                        line_number,
                    )
                    if normalized is _COMPLETION:
                        completion_state = True
                        completed_at = _parse_timestamp(record.get("timestamp"))
                    elif normalized in (_STARTED, _ABORTED):
                        completion_state = False
                    elif isinstance(normalized, NormalizedEvent):
                        events.append(normalized)
        except OSError as exc:
            raise SessionNotFoundError(f"无法读取 Codex 会话: {path}") from exc

        if not saw_meta or session_id is None:
            raise SessionFormatError(f"缺少 session ID: {path}")
        if project_id is None:
            raise SessionFormatError(f"缺少 session source locator: {path}")
        if completion_state is None:
            completion_state = False
        if completed_at is None:
            self._check_deadline(deadline)
            stat = path.stat()
            self._check_deadline(deadline)
            completed_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        source_hash = digest.hexdigest()
        internal_id = (
            "session-"
            + hashlib.sha256(f"{session_id}:{source_hash}".encode("utf-8")).hexdigest()[
                :24
            ]
        )
        source_path = path.resolve()
        self._check_deadline(deadline)
        return NormalizedSession(
            id=internal_id,
            source_session_id=session_id,
            source_path=source_path,
            source_hash=source_hash,
            project_id=project_id,
            completed=completion_state,
            completed_at=completed_at,
            events=tuple(events),
        )

    def _normalize_event(
        self,
        record_type: object,
        payload: dict[str, object],
        timestamp: object,
        session_id: str,
        path: Path,
        line_number: int,
    ) -> NormalizedEvent | object | None:
        payload_type = payload.get("type")
        if record_type in ("completion", "turn_complete") or payload_type in (
            "task_complete",
            "turn_complete",
        ):
            return _COMPLETION
        if payload_type == "task_started":
            return _STARTED
        if payload_type == "turn_aborted" or record_type == "turn_aborted":
            return _ABORTED

        kind: str | None = None
        content: str | None = None
        if record_type == "event_msg" and payload_type == "user_message":
            kind = "user"
            content = _content_text(payload.get("message"))
        elif record_type == "event_msg" and payload_type == "agent_message":
            kind = "assistant"
            content = _content_text(payload.get("message"))
        elif record_type == "response_item" and payload_type == "message":
            role = payload.get("role")
            if role in ("assistant", "user"):
                kind = str(role)
                content = _message_content(payload.get("content"))
        elif record_type == "response_item" and payload_type in (
            "function_call_output",
            "custom_tool_call_output",
        ):
            kind = "command"
            content = _content_text(payload.get("output"))
        elif record_type in ("turn_context", "session_meta"):
            return None

        if kind is None or content is None:
            optional_kind = str(payload_type or record_type or "unknown")
            self._warnings.append(
                f"忽略未知可选 Codex 事件 {optional_kind}，行 {line_number}: {path}"
            )
            return None
        source_identity = str(payload.get("id") or payload.get("call_id") or kind)
        event_id = (
            "event-"
            + hashlib.sha256(
                f"{session_id}:{line_number}:{source_identity}".encode("utf-8")
            ).hexdigest()[:24]
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        locator = SourceLocator(
            session_id=session_id,
            event_id=event_id,
            source_path=str(path.resolve()),
            content_hash=content_hash,
        )
        return NormalizedEvent(
            id=event_id,
            kind=kind,
            content=content,
            locator=locator,
        )


_COMPLETION = object()
_STARTED = object()
_ABORTED = object()


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SessionFormatError(f"缺少 {field}")
    return value


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SessionFormatError(f"无效 timestamp: {value}") from exc


def _message_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, Iterable) or isinstance(value, (bytes, dict)):
        return _content_text(value)
    parts: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("text") or item.get("input_text") or item.get("output_text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
