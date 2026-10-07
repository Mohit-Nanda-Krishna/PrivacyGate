"""Tests for end-to-end PrivacyGate pipeline."""

from pathlib import Path
import pytest
from docx import Document as DocxDocument

from privacygate.extraction.errors import ExtractionError
from privacygate.pipeline import process_document, run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"


def test_pipeline_on_native_fixture_pdf() -> None:
    pdf_path = FIXTURES / "native.pdf"
    result = run_pipeline(pdf_path)

    assert result.document.filename == "native.pdf"
    assert result.validation.status == "APPROVED"
    assert result.audit_report.validation.status == "APPROVED"
    assert len(result.document.blocks) > 0


def test_pipeline_end_to_end_with_pii(tmp_path: Path) -> None:
    # Create a synthetic test DOCX with multiple PII categories
    test_docx = tmp_path / "cadence_report.docx"
    doc = DocxDocument()
    doc.add_paragraph("Employee Jane Doe (Employee ID: EMP-83921) submitted review.")
    doc.add_paragraph("Contact: jane.doe@cadence.com, SSN: 123-45-6789.")
    doc.add_paragraph("Account: ACC-994821.")
    doc.save(test_docx)

    pipeline_result = run_pipeline(test_docx)

    # 1. Extraction checks
    assert pipeline_result.document.file_type == "docx"
    assert len(pipeline_result.document.blocks) == 3

    # 2. Detection checks
    detected_types = {e.entity_type for e in pipeline_result.entities}
    assert "EMPLOYEE_ID" in detected_types
    assert bool(detected_types & {"EMAIL", "EMAIL_ADDRESS"})
    assert bool(detected_types & {"GOVERNMENT_ID", "US_SSN"})
    assert "ACCOUNT_NUMBER" in detected_types

    # 3. Risk classification checks
    for e in pipeline_result.entities:
        assert e.risk_level in ("CRITICAL", "HIGH", "MEDIUM")

    # 4. Redaction checks
    sanitized_text = " ".join(b.text for b in pipeline_result.sanitized_document.blocks)
    assert "[EMPLOYEE_ID]" in sanitized_text
    assert "[EMAIL]" in sanitized_text
    assert "[GOVERNMENT_ID]" in sanitized_text
    assert "[ACCOUNT_NUMBER]" in sanitized_text
    assert "123-45-6789" not in sanitized_text
    assert "EMP-83921" not in sanitized_text

    # 5. Secondary Privacy Validation checks
    assert pipeline_result.validation.status == "APPROVED"
    assert len(pipeline_result.validation.residual_entities) == 0

    # 6. Audit Report checks
    audit = pipeline_result.audit_report
    assert audit.detected_count >= 4
    assert audit.redacted_count >= 4
    assert audit.counts_by_risk["CRITICAL"] >= 2  # SSN + Account
    assert audit.counts_by_risk["HIGH"] >= 2      # Employee ID + Email
    assert audit.validation.status == "APPROVED"

    # 7. Check process_document entry point returns matching AuditReport
    direct_report = process_document(test_docx)
    assert direct_report.detected_count == audit.detected_count
    assert direct_report.validation.status == "APPROVED"


def test_pipeline_nonexistent_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError):
        run_pipeline(tmp_path / "nonexistent.pdf")
