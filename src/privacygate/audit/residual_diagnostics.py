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
    # Types the detectors emit under their own names.
    "US_SSN",
    "ACCOUNT_NUMBER",
    "IBAN_CODE",
    "CLIENT_ID",
    "PORTFOLIO_ID",
    "CUSTOMER_REF",
})

# The extraction_method values the extractors actually set ("native" kept for compatibility).
_ALLOWED_EXTRACTION_METHODS = frozenset({
    "native",
    "pdf_native",
    "docx_native",
    "pptx_native",
    "ocr",
    "embedded_image_ocr",
    "figure_ocr",
})

# Every detector name the pipeline emits. tests/test_residual_diagnostics.py checks
# that each detector string in the source is listed here, so this cannot drift.
_ALLOWED_DETECTORS = frozenset({
    "presidio:SpacyRecognizer",
    "presidio:EmailRecognizer",
    "presidio:PhoneRecognizer",
    "presidio:IpRecognizer",
    "presidio:CreditCardRecognizer",
    "presidio:IbanRecognizer",
    "presidio:UsSsnRecognizer",
    "regex:email",
    "regex:email_ocr",
    "regex:labelled_phone",
    "regex:phone",
    "regex:phone_short",
    "regex:ssn",
    "regex:ssn_last4",
    "regex:ssn_ocr",
    "regex:ip",
    "regex:iban",
    "regex:credit_card",
    "regex:in_pan",
    "regex:passport",
    "regex:pesel",
    "regex:pesel_checksum",
    "regex:tin",
    "regex:dob",
    "regex:account_ending",
    "regex:us_address",
    "custom:employee_id",
    "custom:client_id",
    "custom:customer_id",
    "custom:portfolio_id",
    "custom:account_number",
    "custom:personnel_id",
    "name_sweep",
    "name_sweep_ocr",
    "pattern:ocr_email",
    "pattern:ocr_labelled_id",
    "pattern:ocr_ip",
    "pattern:ocr_dob",
    "context:column_role",
    "context:wrapped_value",
    "context:figure_duplicate",
    "pattern:name_with_initial",
    "context:table_header",
    "context:split_phone",
    "context:role_name",
    "gate:id_shape",
    "gate:digit_run",
    "gate:email_shape",
    "gate:name_registry",
    "gate:unissued_placeholder",
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

