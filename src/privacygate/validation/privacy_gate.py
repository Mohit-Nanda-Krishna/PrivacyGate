"""Fail-closed secondary privacy gate verifying sanitized content."""

from __future__ import annotations

import re
from typing import Sequence
from privacygate.detection import detect_pii
from privacygate.models import Document, PIIEntity, ValidationResult

# Regex matching our standard placeholder patterns, e.g. [PERSON], [EMAIL], [PII]
PLACEHOLDER_PATTERN = re.compile(r"\[[A-Z_]+\]")


def _is_placeholder_span(text: str, start: int, end: int) -> bool:
    """Return True if the span [start, end) matches an applied semantic placeholder."""
    span_text = text[start:end].strip()
    return bool(PLACEHOLDER_PATTERN.fullmatch(span_text))


def validate_privacy(
    sanitized_doc: Document,
    confidence_threshold: float = 0.40,
) -> ValidationResult:
    """Perform secondary privacy scan on sanitized document.

    Fails closed: Any residual PII or validation error blocks the document.
    """
    try:
        # Scan sanitized document using full hybrid detection
        detected_candidates = detect_pii(sanitized_doc)

        # Build a lookup of block text by block_id
        blocks_by_id = {b.block_id: b.text for b in sanitized_doc.blocks}

        residual_entities: list[PIIEntity] = []
        for entity in detected_candidates:
            # Filter below threshold if applicable
            if entity.confidence < confidence_threshold:
                continue

            # Check if this detection is merely detecting one of our intentional placeholders
            block_text = blocks_by_id.get(entity.block_id, "")
            if _is_placeholder_span(block_text, entity.start, entity.end):
                continue

            residual_entities.append(entity)

        if residual_entities:
            return ValidationResult(
                status="BLOCKED",
                reason=(
                    f"Residual PII detected: {len(residual_entities)} sensitive "
                    "entity/entities remain after redaction."
                ),
                residual_entities=residual_entities,
            )

        return ValidationResult(
            status="APPROVED",
            reason="Sanitized document passed secondary privacy scan with zero residual PII.",
            residual_entities=[],
        )

    except Exception as exc:
        # Strictly fail closed on any internal error or pipeline failure
        return ValidationResult(
            status="BLOCKED",
            reason=f"Privacy gate failed closed due to unexpected validation error: {type(exc).__name__}: {exc}",
            residual_entities=[],
        )
