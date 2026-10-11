"""Privacy-safe diagnostics for residual PII findings."""

from __future__ import annotations

from typing import Any, Sequence

from privacygate.models import PIIEntity


_ALLOWED_ENTITY_TYPES = frozenset({
    "PERSON",
    "EMAIL",
    "EMAIL_ADDRESS",
    "PHONE",
    "PHONE_NUMBER",
    "LOCATION",
    "ADDRESS",
    "GOVERNMENT_ID",
    "CUSTOMER_ID",
    "EMPLOYEE_ID",
    "FINANCIAL_ACCOUNT",
    "CREDIT_CARD",
    "DATE_OF_BIRTH",
    "IP_ADDRESS",
    "PII",
})

_ALLOWED_EXTRACTION_METHODS = frozenset({
    "native",
    "ocr",
    "embedded_image_ocr",
})

_ALLOWED_DETECTORS = frozenset({
    "presidio:SpacyRecognizer",
    "gate:id_shape",
    "gate:digit_run",
    "gate:email_shape",
    "gate:name_registry",
})


def build_residual_diagnostics(
    residual_entities: Sequence[PIIEntity],
) -> list[dict[str, Any]]:
    """Return allowlisted metadata without source text or identifiers."""
    diagnostics: list[dict[str, Any]] = []

    for entity in residual_entities:
        entity_type = (
            entity.entity_type
            if type(entity.entity_type) is str
            and entity.entity_type in _ALLOWED_ENTITY_TYPES
            else "OTHER"
        )

        detectors = entity.detector.split("|") if type(entity.detector) is str else []
        safe_detectors = sorted({
            detector
            for detector in detectors
            if detector in _ALLOWED_DETECTORS
        })

        location = (
            entity.source_location
            if type(entity.source_location) is dict
            else {}
        )

        page_number = location.get("page_number")
        if type(page_number) is not int or page_number <= 0:
            page_number = None

        extraction_method = location.get("extraction_method")
        if (
            type(extraction_method) is not str
            or extraction_method not in _ALLOWED_EXTRACTION_METHODS
        ):
            extraction_method = "unknown"

        diagnostics.append({
            "entity_type": entity_type,
            "detectors": safe_detectors,
            "page": page_number,
            "extraction_method": extraction_method,
        })

    return diagnostics

