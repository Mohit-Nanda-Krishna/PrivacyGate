"""Fail-closed secondary privacy gate verifying sanitized content."""

from __future__ import annotations

import re

from privacygate.detection import detect_pii, merge_entities
from privacygate.detection.names import NameRegistry
from privacygate.models import Document, PIIEntity, ValidationResult
from privacygate.validation.residual_checks import GATE_DETECTOR_PREFIX, independent_residual_checks

# Regex matching our standard placeholder patterns, e.g. [PERSON], [EMAIL], [PII]
PLACEHOLDER_PATTERN = re.compile(r"\[[A-Z_]+\]")


def _is_placeholder_span(text: str, start: int, end: int) -> bool:
    """Return True if the span [start, end) matches an applied semantic placeholder."""
    span_text = text[start:end].strip()
    return bool(PLACEHOLDER_PATTERN.fullmatch(span_text))


def validate_privacy(
    sanitized_doc: Document,
    confidence_threshold: float = 0.40,
    name_registry: NameRegistry | None = None,
) -> ValidationResult:
    """Perform secondary privacy scan on sanitized document.

    Two independent layers run: the full hybrid detector, and blunt checks
    that do not depend on the NER model (names and variants from the original
    document's registry, 7+ digit runs, e-mail and ID shapes). Any residual
    from either layer blocks. Fails closed: any validation error blocks, and
    the reason names only the error type, never its message (which could
    contain document text).
    """
    failed_pages = sanitized_doc.metadata.get("ocr_failed_pages") or []
    if failed_pages:
        # Content on these pages was never inspected, so it cannot be approved.
        return ValidationResult(
            status="BLOCKED",
            reason=(
                "Extraction incomplete: OCR failed for page(s) "
                f"{', '.join(map(str, failed_pages))}. Content on those pages was not inspected."
            ),
            residual_entities=[],
        )

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

        independent = independent_residual_checks(sanitized_doc.blocks, name_registry)
        # Merge overlapping residuals so a later redaction pass can splice them safely;
        # merged detector provenance keeps the "gate:" marker.
        residual_entities = merge_entities(residual_entities + independent)

        if residual_entities:
            independent_count = len(independent)
            return ValidationResult(
                status="BLOCKED",
                reason=(
                    f"Residual PII detected: {len(residual_entities)} sensitive "
                    "entity/entities remain after redaction"
                    + (f" ({independent_count} found by independent residual checks)." if independent_count else ".")
                ),
                residual_entities=residual_entities,
            )

        return ValidationResult(
            status="APPROVED",
            reason="Sanitized document passed secondary privacy scan with zero residual PII.",
            residual_entities=[],
        )

    except Exception as exc:
        # Strictly fail closed. Exception messages can quote document text, so only the type is reported.
        return ValidationResult(
            status="BLOCKED",
            reason=f"Privacy gate failed closed due to unexpected validation error: {type(exc).__name__}",
            residual_entities=[],
        )


def found_by_independent_checks(result: ValidationResult) -> bool:
    """True if any residual came from a check that does not rely on the primary detectors."""
    return any(
        source.startswith(GATE_DETECTOR_PREFIX)
        for entity in result.residual_entities
        for source in entity.detector.split("|")
    )
