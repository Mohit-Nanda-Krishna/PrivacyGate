"""Audit report generation with zero raw PII persistence."""

from __future__ import annotations

import json
from typing import Any, Sequence
from privacygate.models import AuditReport, Document, PIIEntity, RiskLevel, ValidationResult
from privacygate.risk.classifier import summarize_risks


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

    counts_by_risk = summarize_risks(detected_entities)

    return AuditReport(
        document_id=document.document_id,
        detected_count=len(detected_entities),
        redacted_count=redacted_count,
        counts_by_category=counts_by_category,
        counts_by_risk=counts_by_risk,
        validation=validation_result,
    )


def audit_report_to_dict(report: AuditReport) -> dict[str, Any]:
    """Serialize AuditReport to a clean dictionary."""
    return {
        "document_id": report.document_id,
        "detected_count": report.detected_count,
        "redacted_count": report.redacted_count,
        "counts_by_category": dict(report.counts_by_category),
        "counts_by_risk": dict(report.counts_by_risk),
        "validation": {
            "status": report.validation.status,
            "reason": report.validation.reason,
            "residual_count": len(report.validation.residual_entities),
        },
    }


def audit_report_to_json(report: AuditReport, indent: int = 2) -> str:
    """Serialize AuditReport to formatted JSON."""
    return json.dumps(audit_report_to_dict(report), indent=indent)
