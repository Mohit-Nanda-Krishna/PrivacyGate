"""Tests for Phase 3 audit report generation."""

import json
from privacygate.audit import audit_report_to_dict, audit_report_to_json, generate_audit_report
from privacygate.models import Document, PIIEntity, ValidationResult


def test_generate_audit_report_privacy_preserved() -> None:
    doc = Document(document_id="doc_audit_1", filename="statement.pdf", file_type="pdf")
    entities = [
        PIIEntity(entity_type="CREDIT_CARD", start=0, end=16, confidence=1.0, detector="regex", block_id="b1"),
        PIIEntity(entity_type="EMAIL", start=20, end=35, confidence=1.0, detector="regex", block_id="b1"),
    ]
    val = ValidationResult(status="APPROVED", reason="Clean", residual_entities=[])

    report = generate_audit_report(
        document=doc,
        detected_entities=entities,
        redacted_count=2,
        validation_result=val,
    )

    assert report.document_id == "doc_audit_1"
    assert report.detected_count == 2
    assert report.redacted_count == 2
    assert report.counts_by_category["CREDIT_CARD"] == 1
    assert report.counts_by_category["EMAIL"] == 1
    assert report.counts_by_risk["CRITICAL"] == 1
    assert report.counts_by_risk["HIGH"] == 1
    assert report.validation.status == "APPROVED"

    # Test serialization to dict and json
    report_dict = audit_report_to_dict(report)
    assert report_dict["detected_count"] == 2
    assert "validation" in report_dict

    report_json = audit_report_to_json(report)
    parsed = json.loads(report_json)
    assert parsed["document_id"] == "doc_audit_1"
