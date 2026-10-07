"""Audit report generation with zero raw PII persistence."""

from __future__ import annotations

import json
from typing import Any, Sequence
from privacygate.models import AuditReport, ContentBlock, Document, PIIEntity, RiskLevel, ValidationResult
from privacygate.risk.classifier import summarize_risks


def location_type(block: ContentBlock) -> str:
    """Where a block's text lives: image, header, footer, text_box, notes, table, scanned_page or body."""
    if block.extraction_method == "embedded_image_ocr":
        return "image"
    kind = block.metadata.get("kind")
    if kind in ("header", "footer", "text_box", "notes"):
        return kind
    if kind == "table_cell":
        return "table"
    if block.extraction_method == "ocr":
        return "scanned_page"
    return "body"


def generate_audit_report(
    document: Document,
    detected_entities: Sequence[PIIEntity],
    redacted_count: int,
    validation_result: ValidationResult,
) -> AuditReport:
    """Generate an audit-compliant report containing metrics and privacy decision.

    Guarantees no raw PII values or sensitive text are persisted.
    """
    counts_by_category: dict[str, int] = {}
    for entity in detected_entities:
        counts_by_category[entity.entity_type] = counts_by_category.get(entity.entity_type, 0) + 1

    blocks = {block.block_id: block for block in document.blocks}
    counts_by_location: dict[str, int] = {}
    for entity in detected_entities:
        block = blocks.get(entity.block_id)
        where = location_type(block) if block is not None else "unknown"
        counts_by_location[where] = counts_by_location.get(where, 0) + 1

    counts_by_risk = summarize_risks(detected_entities)

    return AuditReport(
        document_id=document.document_id,
        detected_count=len(detected_entities),
        redacted_count=redacted_count,
        counts_by_category=counts_by_category,
        counts_by_risk=counts_by_risk,
        validation=validation_result,
        page_report=[dict(entry) for entry in document.metadata.get("page_report", [])],
        counts_by_location=counts_by_location,
        embedded_images=[dict(entry) for entry in document.metadata.get("embedded_images", [])],
        extraction_warnings=[dict(entry) for entry in document.metadata.get("extraction_warnings", [])],
    )


def audit_report_to_dict(report: AuditReport) -> dict[str, Any]:
    """Serialize AuditReport to a clean dictionary."""
    return {
        "document_id": report.document_id,
        "detected_count": report.detected_count,
        "redacted_count": report.redacted_count,
        "counts_by_category": dict(report.counts_by_category),
        "counts_by_risk": dict(report.counts_by_risk),
        "counts_by_location": dict(report.counts_by_location),
        "validation": {
            "status": report.validation.status,
            "reason": report.validation.reason,
            "residual_count": len(report.validation.residual_entities),
        },
        "extraction": {
            "pages": [dict(entry) for entry in report.page_report],
            "failed_pages": [entry["page"] for entry in report.page_report if entry.get("status") == "failed"],
            "embedded_images": [dict(entry) for entry in report.embedded_images],
            "warnings": [dict(entry) for entry in report.extraction_warnings],
        },
    }


def audit_report_to_json(report: AuditReport, indent: int = 2) -> str:
    """Serialize AuditReport to formatted JSON."""
    return json.dumps(audit_report_to_dict(report), indent=indent)
