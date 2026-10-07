"""Semantic PII redaction module."""

from privacygate.redaction.redactor import (
    RedactionRecord,
    get_placeholder,
    redact_document,
    redact_text,
)

__all__ = [
    "RedactionRecord",
    "get_placeholder",
    "redact_document",
    "redact_text",
]
