"""Audit summaries with aggregate metrics and allowlisted structural metadata."""

from __future__ import annotations

import json
from math import isfinite
from typing import Any, Sequence
from uuid import UUID, uuid4

from privacygate.models import AuditReport, ContentBlock, Document, PIIEntity, ValidationResult
from privacygate.risk.classifier import RISK_MAPPING, summarize_risks

PAGE_STATUSES = frozenset({"native", "ocr", "failed"})
IMAGE_STATUSES = ("ocr", "skipped_vector", "skipped_tiny", "failed", "unknown")
LOCATION_TYPES = frozenset({"image", "header", "footer", "text_box", "notes", "table", "scanned_page", "body", "unknown"})
RISK_LEVELS = ("CRITICAL", "HIGH", "MEDIUM")
ENTITY_TYPES = frozenset(RISK_MAPPING) | {"PII"}


def _safe_count(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _safe_audit_id(value: object) -> str | None:
    """Check the format of an already-generated audit correlation ID."""
    try:
        return str(UUID(value)) if type(value) is str else None
    except ValueError:
        return None


def _safe_page_report(entries: object) -> list[dict[str, int | float | str]]:
    pages = []
    if type(entries) is not list:
        return pages
    for entry in entries:
        if type(entry) is not dict or type(entry.get("page")) is not int or entry["page"] < 1:
            continue
        status = entry.get("status")
        page: dict[str, int | float | str] = {
            "page": entry["page"],
            "status": status if type(status) is str and status in PAGE_STATUSES else "unknown",
        }
        attempts = entry.get("attempts")
        if type(attempts) is int and attempts >= 0:
            page["attempts"] = attempts
        seconds = entry.get("seconds")
        if type(seconds) in (int, float) and isfinite(seconds) and seconds >= 0:
            page["seconds"] = seconds
        pages.append(page)
    return pages


def _embedded_image_counts(entries: object) -> dict[str, int]:
    counts = dict.fromkeys(IMAGE_STATUSES, 0)
    if type(entries) is not list:
        return counts
    for entry in entries:
        status = entry.get("status") if type(entry) is dict else None
        counts[status if type(status) is str and status in counts else "unknown"] += 1
    return counts


def _safe_image_counts(counts: object) -> dict[str, int]:
    safe = dict.fromkeys(IMAGE_STATUSES, 0)
    if type(counts) is dict:
        for status, count in counts.items():
            if type(count) is int and count >= 0:
                safe[status if type(status) is str and status in safe else "unknown"] += count
    return safe


def _safe_category_counts(counts: object) -> dict[str, int]:
    safe: dict[str, int] = {}
    if type(counts) is dict:
        for category, count in counts.items():
            if type(count) is int and count >= 0:
                key = category if type(category) is str and category in ENTITY_TYPES else "OTHER"
                safe[key] = safe.get(key, 0) + count
    return safe


def _safe_risk_counts(counts: object) -> dict[str, int]:
    safe = dict.fromkeys(RISK_LEVELS, 0)
    if type(counts) is dict:
        for level, count in counts.items():
            if type(count) is int and count >= 0:
                safe[level if type(level) is str and level in safe else "MEDIUM"] += count
    return safe


def _safe_location_counts(counts: object) -> dict[str, int]:
    safe: dict[str, int] = {}
    if type(counts) is dict:
        for location, count in counts.items():
            if type(count) is int and count >= 0:
                key = location if type(location) is str and location in LOCATION_TYPES else "unknown"
                safe[key] = safe.get(key, 0) + count
    return safe


def _safe_validation_reason(status: str, residual_count: int) -> str:
    """Describe the supplied decision without revalidating document metadata."""
    if status == "APPROVED":
        return "Document passed privacy validation."
    if status != "BLOCKED":
        raise ValueError("Invalid privacy validation status")
    if residual_count:
        return "Document blocked because residual sensitive data was detected."
    return "Document blocked by privacy validation."


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
    """Store aggregate metrics and allowlisted structural metadata, never source text."""
    counts_by_category: dict[str, int] = {}
    for entity in detected_entities:
        category = entity.entity_type if entity.entity_type in ENTITY_TYPES else "OTHER"
        counts_by_category[category] = counts_by_category.get(category, 0) + 1

    blocks = {block.block_id: block for block in document.blocks}
    counts_by_location: dict[str, int] = {}
    for entity in detected_entities:
        block = blocks.get(entity.block_id)
        where = location_type(block) if block is not None else "unknown"
        counts_by_location[where] = counts_by_location.get(where, 0) + 1

    counts_by_risk = _safe_risk_counts(summarize_risks(detected_entities))
    pages = _safe_page_report(document.metadata.get("page_report"))
    images = _embedded_image_counts(document.metadata.get("embedded_images"))
    residual_count = len(validation_result.residual_entities)
    reason = _safe_validation_reason(validation_result.status, residual_count)
    warnings = document.metadata.get("extraction_warnings")

    return AuditReport(
        # This is an audit correlation ID, independent of the source identifier.
        document_id=str(uuid4()),
        detected_count=len(detected_entities),
        redacted_count=redacted_count,
        counts_by_category=counts_by_category,
        counts_by_risk=counts_by_risk,
        validation=ValidationResult(status=validation_result.status, reason=reason),
        residual_count=residual_count,
        page_report=pages,
        counts_by_location=counts_by_location,
        embedded_images=images,
        extraction_warning_count=len(warnings) if type(warnings) is list else 0,
    )


def audit_report_to_dict(report: AuditReport) -> dict[str, Any]:
    """Serialize only aggregate metrics, decisions, and allowlisted coordinates."""
    pages = _safe_page_report(report.page_report)
    images = _safe_image_counts(report.embedded_images)
    residual_count = _safe_count(report.residual_count)
    reason = _safe_validation_reason(report.validation.status, residual_count)
    return {
        "document_id": _safe_audit_id(report.document_id) or "unavailable",
        "detected_count": _safe_count(report.detected_count),
        "redacted_count": _safe_count(report.redacted_count),
        "counts_by_category": _safe_category_counts(report.counts_by_category),
        "counts_by_risk": _safe_risk_counts(report.counts_by_risk),
        "counts_by_location": _safe_location_counts(report.counts_by_location),
        "validation": {
            "status": report.validation.status,
            "reason": reason,
            "residual_count": residual_count,
        },
        "extraction": {
            "pages": pages,
            "failed_pages": [entry["page"] for entry in pages if entry["status"] == "failed"],
            "embedded_images": images,
            "warnings": {"count": _safe_count(report.extraction_warning_count)},
        },
    }


def audit_report_to_json(report: AuditReport, indent: int = 2) -> str:
    """Serialize AuditReport to formatted JSON."""
    return json.dumps(audit_report_to_dict(report), indent=indent)
