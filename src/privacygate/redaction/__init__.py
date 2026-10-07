"""Semantic PII redaction module."""

from privacygate.redaction.redactor import (
    PseudonymSession,
    RedactionRecord,
    get_placeholder,
    redact_document,
    redact_text,
)

__all__ = [
    "PseudonymSession",
    "RedactionRecord",
    "get_placeholder",
    "redact_document",
    "redact_text",
]
