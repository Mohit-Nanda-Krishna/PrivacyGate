"""Shared recognition of legacy and session-issued semantic placeholders."""

import re

GENERIC_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z_]*\]")
NUMBERED_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z_]*_\d+\]")


def intentional_placeholder_spans(
    text: str, issued_tokens: frozenset[str] = frozenset(),
) -> list[tuple[int, int]]:
    """Legacy generic tokens and exact tokens issued by this run are intentional."""
    return [match.span() for match in GENERIC_PLACEHOLDER.finditer(text)] + [
        match.span() for match in NUMBERED_PLACEHOLDER.finditer(text)
        if match.group() in issued_tokens
    ]


def unissued_numbered_spans(
    text: str, issued_tokens: frozenset[str] = frozenset(),
) -> list[tuple[int, int]]:
    """Untrusted numbered lookalikes must be reviewed by the privacy gate."""
    return [
        match.span() for match in NUMBERED_PLACEHOLDER.finditer(text)
        if match.group() not in issued_tokens
    ]
