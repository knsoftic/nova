"""Strip secrets before anything is written to logs or the database."""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    # key=value / key: value style secrets
    re.compile(
        r"(?i)\b(password|passwd|pwd|pass|secret|api[_-]?key|token|access[_-]?token|auth)\b(\s*[:=]\s*|\s+(?:is|hai)\s+)(\S+)"
    ),
    # Bearer tokens
    re.compile(r"(?i)\b(bearer)(\s+)([A-Za-z0-9\-._~+/]+=*)"),
]

_STANDALONE = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),  # common AI provider key shape
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),  # GitHub tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),  # JWT
]


def redact(text: str | None) -> str | None:
    if not text:
        return text
    out = text
    for pattern in _PATTERNS:
        out = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    for pattern in _STANDALONE:
        out = pattern.sub(REDACTED, out)
    return out
