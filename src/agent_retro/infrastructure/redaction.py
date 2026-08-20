"""Sensitive value redaction shared by model and persistence boundaries."""

from __future__ import annotations

import re
from collections.abc import Callable


Replacement = str | Callable[[re.Match[str]], str]

_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_FLATTENED_HEADER = re.compile(rf"{_TOKEN}[ \t]*:(?=[ \t]+|\Z)")
_SENSITIVE_HEADER = re.compile(
    r"(?<![!#$%&'*+\-.^_`|~0-9A-Za-z])"
    r"(?P<name>Proxy-Authorization|Authorization|Set-Cookie|Cookie)"
    r"[ \t]*:[ \t]*",
    re.IGNORECASE,
)
_AUTHORIZATION_SCHEME = re.compile(rf"(?P<scheme>{_TOKEN})")


def _preserve(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}[REDACTED]{match.groupdict().get('suffix', '')}"


def _redact_authentication_headers(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    search_from = 0
    while match := _SENSITIVE_HEADER.search(text, search_from):
        parts.append(text[cursor : match.start()])
        value_start = match.end()
        scheme = ""
        header_name = match.group("name").casefold()
        if header_name in {"authorization", "proxy-authorization"}:
            scheme_start, _ = _skip_header_whitespace(text, value_start)
            scheme_match = _AUTHORIZATION_SCHEME.match(text, scheme_start)
            if scheme_match is not None:
                credential_start, separated = _skip_header_whitespace(
                    text, scheme_match.end()
                )
            else:
                credential_start, separated = value_start, False
            if scheme_match is not None and separated:
                scheme = scheme_match.group("scheme")
                value_start = credential_start

        # A raw Set-Cookie extension value may legally contain spaces and colons,
        # so an apparent flattened header is ambiguous. Fail closed to the
        # physical header boundary; only preserve following flattened headers
        # once this value is already the deterministic placeholder.
        allow_flattened_boundary = header_name != "set-cookie" or text.startswith(
            "[REDACTED]", value_start
        )
        value_end = _header_value_end(
            text,
            value_start,
            allow_flattened_boundary=allow_flattened_boundary,
        )
        value = text[value_start:value_end]
        if not value.strip() or value.strip() == "[REDACTED]":
            parts.append(text[match.start() : value_end])
        else:
            prefix = text[match.start() : match.end()].rstrip() + " "
            replacement = f"{prefix}{scheme} " if scheme else prefix
            parts.append(f"{replacement}[REDACTED]")
        cursor = value_end
        search_from = value_end
    parts.append(text[cursor:])
    return "".join(parts)


def _skip_header_whitespace(text: str, start: int) -> tuple[int, bool]:
    index = start
    while index < len(text):
        if text[index] in " \t":
            index += 1
            continue
        if text[index] not in "\r\n":
            break
        newline_end = index + 1
        if (
            text[index] == "\r"
            and newline_end < len(text)
            and text[newline_end] == "\n"
        ):
            newline_end += 1
        if newline_end >= len(text) or text[newline_end] not in " \t":
            break
        index = newline_end
    return index, index > start


def _folded_line_start(text: str, index: int) -> int | None:
    newline_end = index + 1
    if text[index] == "\r" and newline_end < len(text) and text[newline_end] == "\n":
        newline_end += 1
    if newline_end >= len(text) or text[newline_end] not in " \t":
        return None
    return newline_end


def _header_value_end(
    text: str, start: int, *, allow_flattened_boundary: bool = True
) -> int:
    quote = ""
    escaped = False
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char in "\r\n":
                folded_start = _folded_line_start(text, index)
                if folded_start is None:
                    return index
                index = folded_start
                escaped = False
            elif escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in ('"', "'"):
            quote = char
        elif char in "\r\n":
            folded_start = _folded_line_start(text, index)
            if folded_start is None:
                return index
            index = folded_start
        elif allow_flattened_boundary and char in " \t":
            next_token = index
            while next_token < len(text) and text[next_token] in " \t":
                next_token += 1
            if _FLATTENED_HEADER.match(text, next_token):
                return index
            index = next_token
            continue
        index += 1
    return len(text)


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
        value = _redact_authentication_headers(text)
        for pattern, replacement in REDACTION_RULES:
            value = pattern.sub(replacement, value)
        return value

    def contains_sensitive_value(self, text: str) -> bool:
        return self.redact(text) != text
