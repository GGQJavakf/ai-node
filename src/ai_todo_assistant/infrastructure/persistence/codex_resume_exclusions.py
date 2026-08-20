"""Persistent manual exclusions for automatic Codex resume."""
from __future__ import annotations

import json
import os
import tempfile

from ai_todo_assistant.application.workflow.codex_resume import CodexResumeExclusion
from ai_todo_assistant.domain.workflow import now_text


class JsonCodexResumeExclusionStore:
    """Stores thread ids that should be skipped by bulk/automatic resume."""

    def __init__(self, path: str):
        self.path = path

    def list_exclusions(self) -> list[CodexResumeExclusion]:
        data = self._read()
        entries = self._entries(data)
        exclusions: list[CodexResumeExclusion] = []
        for entry in entries:
            thread_id = str(entry.get("thread_id") or "").strip()
            if not thread_id:
                continue
            exclusions.append(
                CodexResumeExclusion(
                    thread_id=thread_id,
                    reason=str(entry.get("reason") or "").strip(),
                    created_at=str(entry.get("created_at") or "").strip(),
                )
            )
        return exclusions

    def exclude(self, thread_id: str, reason: str = "") -> CodexResumeExclusion:
        normalized = str(thread_id or "").strip()
        if not normalized:
            raise ValueError("thread_id is required")
        data = self._read()
        entries = self._entries(data)
        existing = next(
            (entry for entry in entries if str(entry.get("thread_id") or "").strip() == normalized),
            None,
        )
        if existing is None:
            existing = {"thread_id": normalized, "created_at": now_text()}
            entries.append(existing)
        existing["reason"] = str(reason or "").strip()
        data["exclusions"] = entries
        self._write(data)
        return CodexResumeExclusion(
            thread_id=normalized,
            reason=existing.get("reason", ""),
            created_at=existing.get("created_at", ""),
        )

    def include(self, thread_id: str) -> bool:
        normalized = str(thread_id or "").strip()
        if not normalized:
            raise ValueError("thread_id is required")
        data = self._read()
        before = self._entries(data)
        after = [
            entry
            for entry in before
            if str(entry.get("thread_id") or "").strip() != normalized
        ]
        if len(after) == len(before):
            return False
        data["exclusions"] = after
        self._write(data)
        return True

    def _read(self) -> dict:
        if not os.path.exists(self.path):
            return {"exclusions": []}
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("exclusion file must contain a JSON object")
        data.setdefault("exclusions", [])
        return data

    def _entries(self, data: dict) -> list[dict]:
        entries = data.get("exclusions", [])
        if not isinstance(entries, list):
            raise ValueError("exclusions must be a list")
        if not all(isinstance(entry, dict) for entry in entries):
            raise ValueError("exclusions entries must be JSON objects")
        return entries

    def _write(self, data: dict) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(self.path)}.",
            suffix=".tmp",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_path, self.path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
