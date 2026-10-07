"""Tests for Phase 3 audit report generation."""

import json
from uuid import UUID
import pytest
from privacygate.audit import audit_report_to_dict, audit_report_to_json, generate_audit_report
from privacygate.models import AuditReport, ContentBlock, Document, PIIEntity, ValidationResult


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

    assert UUID(report.document_id).version == 4
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
    assert parsed["document_id"] == report.document_id


def test_audit_allowlists_metadata_and_never_exports_source_strings() -> None:
    secret = "SECRET_PERSON_VALUE_92731"
    filename = "employee-secret-document.pdf"
    image_name = "secret_image_name.png"
    path = "C:/private/employee-secret-document.pdf"
    doc = Document(
        document_id=path, filename=filename, file_type="pdf",
        metadata={
            "arbitrary": secret,
            "pseudonym_map": {secret: "[PERSON_001]"},
            "page_report": [{
                "page": 2, "status": "failed", "attempts": 2, "seconds": 1.25,
                "reason": secret, "path": path,
            }],
            "embedded_images": [
                {"image": image_name, "status": "failed", "reason": secret},
                {"image": image_name, "status": secret},
            ],
            "extraction_warnings": [{"image": image_name, "reason": secret}],
        },
        blocks=[ContentBlock("b1", secret)],
    )
    entity = PIIEntity("PERSON", 0, len(secret), 0.9, "test", "b1", {"note": secret})
    validation = ValidationResult("BLOCKED", secret, [entity])

    report = generate_audit_report(doc, [entity], 1, validation)
    exported = audit_report_to_json(report)
    parsed = json.loads(exported)

    for value in (secret, filename, image_name, path):
        assert value not in exported
        assert value not in repr(report)
    assert "pseudonym_map" not in exported
    assert UUID(parsed["document_id"])
    assert parsed["detected_count"] == parsed["redacted_count"] == 1
    assert parsed["counts_by_category"] == {"PERSON": 1}
    assert parsed["validation"]["status"] == "BLOCKED"
    assert parsed["validation"]["residual_count"] == 1
    assert report.validation.residual_entities == []
    assert parsed["extraction"] == {
        "pages": [{"page": 2, "status": "failed", "attempts": 2, "seconds": 1.25}],
        "failed_pages": [2],
        "embedded_images": {"ocr": 0, "skipped_vector": 0, "skipped_tiny": 0, "failed": 1, "unknown": 1},
        "warnings": {"count": 1},
    }


def test_canonical_serializer_rechecks_manually_constructed_report() -> None:
    secret = "SECRET_PERSON_VALUE_92731"
    report = AuditReport(
        document_id=secret,
        detected_count=1,
        counts_by_category={secret: 1},
        validation=ValidationResult(status="BLOCKED", reason=secret),
        page_report=[{"page": 1, "status": "native", "reason": secret}],
        embedded_images={secret: 2},
    )

    exported = audit_report_to_json(report)

    assert secret not in exported
    assert json.loads(exported)["counts_by_category"] == {"OTHER": 1}


def test_audit_id_is_fresh_and_stable_without_source_uuid() -> None:
    secret = "12345678-1234-4234-8234-123456789abc"
    doc = Document(secret, "private.pdf", "pdf", blocks=[ContentBlock("b1", secret)])
    entity = PIIEntity("CUSTOMER_ID", 0, len(secret), 1.0, "test", "b1")
    validation = ValidationResult("APPROVED", secret)

    report = generate_audit_report(doc, [entity], 1, validation)
    another = generate_audit_report(doc, [entity], 1, validation)

    assert UUID(report.document_id).version == UUID(another.document_id).version == 4
    assert report.document_id != another.document_id
    for _ in range(2):
        exported = audit_report_to_json(report)
        assert secret not in exported
        assert json.loads(exported)["document_id"] == report.document_id
        assert audit_report_to_dict(report)["document_id"] == report.document_id


@pytest.mark.parametrize("status", ["APPROVED", "BLOCKED"])
@pytest.mark.parametrize("residual_count", [0, 2])
@pytest.mark.parametrize("page_status", ["native", "failed"])
def test_audit_observes_validation_decision_and_exact_residual_count(
    status, residual_count, page_status,
) -> None:
    doc = Document("source", "private.pdf", "pdf", metadata={
        "page_report": [{"page": 1, "status": page_status}],
        "embedded_images": [{"status": "failed"}],
    })
    residuals = [PIIEntity("PERSON", 0, 5, 0.9, "test", "b1") for _ in range(residual_count)]
    validation = ValidationResult(status, "SECRET_PERSON_VALUE_92731", residuals)

    report = generate_audit_report(doc, [], 0, validation)

    assert report.validation.status == validation.status == status
    assert report.residual_count == len(validation.residual_entities) == residual_count
    expected_reason = (
        "Document passed privacy validation." if status == "APPROVED" else
        "Document blocked because residual sensitive data was detected." if residual_count else
        "Document blocked by privacy validation."
    )
    for exported in (audit_report_to_dict(report), json.loads(audit_report_to_json(report))):
        assert exported["validation"] == {
            "status": status, "reason": expected_reason, "residual_count": residual_count,
        }
    assert report.validation.reason == expected_reason


def test_audit_preserves_known_categories_and_aggregates_unknown_as_other() -> None:
    categories = ["PERSON", "PERSON", "EMAIL_ADDRESS",
                  "SECRET_PERSON_VALUE_92731", "C:/private/document.pdf", "<script>secret</script>"]
    entities = [PIIEntity(category, 0, 5, 0.9, "test", "b1") for category in categories]
    doc = Document("source", "private.pdf", "pdf", blocks=[ContentBlock("b1", "Synthetic")])

    report = generate_audit_report(doc, entities, 6, ValidationResult("BLOCKED"))

    assert report.counts_by_category == {"PERSON": 2, "EMAIL_ADDRESS": 1, "OTHER": 3}
    exported = audit_report_to_dict(report)
    assert exported["counts_by_category"] == report.counts_by_category
    assert exported["detected_count"] == exported["redacted_count"] == 6
    assert exported["counts_by_risk"] == {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 5}
    assert exported["counts_by_location"] == {"body": 6}
    assert all(category not in audit_report_to_json(report) for category in categories[3:])
