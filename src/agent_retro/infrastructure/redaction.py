"""Sensitive value redaction shared by model and persistence boundaries."""

from __future__ import annotations

import re
from collections.abc import Callable


Replacement = str | Callable[[re.Match[str]], str]


def _preserve(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}[REDACTED]{match.groupdict().get('suffix', '')}"


REDACTION_RULES: tuple[tuple[re.Pattern[str], Replacement], ...] = (
    (
        re.compile(
            r"(?is)-----BEGIN (?P<kind>[A-Z0-9 ]*PRIVATE KEY)-----.*?"
            r"-----END (?P=kind)-----"
        ),
        lambda match: (
            f"-----BEGIN {match.group('kind')}-----\n[REDACTED]\n"
            f"-----END {match.group('kind')}-----"
        ),
    ),
    (
        re.compile(
            r"(?i)(?P<prefix>\bAuthorization\s*:\s*Bearer\s+)"
            r"(?!\[REDACTED\])[^\s,;]+"
        ),
        _preserve,
    ),
    (
        re.compile(
            r'(?i)(?P<prefix>["\'](?:api[_-]?key|access[_-]?token|token|'
            r'password|passwd|secret|client[_-]?secret)["\']\s*:\s*["\'])'
            r'(?!\[REDACTED\])[^"\']*(?P<suffix>["\'])'
        ),
        _preserve,
    ),
    (
        re.compile(
            r"(?i)(?P<prefix>\b(?:api[_-]?key|access[_-]?token|token|password|"
            r"passwd|secret|client[_-]?secret)\s*[=:]\s*[\"']?)"
            r"(?!\[REDACTED\])[^\s,;\"']+(?P<suffix>[\"']?)"
        ),
        _preserve,
    ),
    (
        re.compile(
            r"(?i)(?P<prefix>\b[a-z][a-z0-9+.-]*://[^\s/:@]+:)"
            r"(?!\[REDACTED\])[^\s/@]+(?P<suffix>@)"
        ),
        _preserve,
    ),
)


class Redactor:
    """Apply deterministic and idempotent value-only redaction."""

    def redact(self, text: str) -> str:
        value = text
        for pattern, replacement in REDACTION_RULES:
            value = pattern.sub(replacement, value)
        return value

    def contains_sensitive_value(self, text: str) -> bool:
        return self.redact(text) != text
