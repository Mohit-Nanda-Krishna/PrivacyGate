"""Tests for Phase 3 secondary privacy validation gate."""

from privacygate.models import ContentBlock, Document
from privacygate.validation import validate_privacy


def test_validate_privacy_approved_clean_sanitized() -> None:
    # Sanitized document with only semantic placeholders and safe text
    block = ContentBlock(
        block_id="b1",
        text="Employee [PERSON] with email [EMAIL] submitted request [EMPLOYEE_ID].",
        page_number=1,
    )
    doc = Document(
        document_id="clean_doc",
        filename="clean.pdf",
        file_type="pdf",
        blocks=[block],
    )
    result = validate_privacy(doc)
    assert result.status == "APPROVED"
    assert len(result.residual_entities) == 0
    assert "passed secondary privacy scan" in result.reason.lower()


def test_validate_privacy_blocked_on_residual_pii() -> None:
    # Sanitized document that leaked an email and an SSN
    block = ContentBlock(
        block_id="b1",
        text="Employee [PERSON] forgot to redact leaked@cadence.com and SSN 123-45-6789.",
        page_number=1,
    )
    doc = Document(
        document_id="leaked_doc",
        filename="leaked.pdf",
        file_type="pdf",
        blocks=[block],
    )
    result = validate_privacy(doc)
    assert result.status == "BLOCKED"
    assert len(result.residual_entities) >= 1
    assert "Residual PII detected" in result.reason


def test_validate_privacy_fails_closed_on_error(monkeypatch) -> None:
    # Injected detector failure
    def mock_detect_pii_error(doc):
        raise RuntimeError("Presidio/NLP engine failure")

    monkeypatch.setattr("privacygate.validation.privacy_gate.detect_pii", mock_detect_pii_error)

    doc = Document(
        document_id="bad_doc",
        filename="bad.pdf",
        file_type="pdf",
        blocks=[ContentBlock(block_id="b1", text="Safe text")],
    )
    result = validate_privacy(doc)
    assert result.status == "BLOCKED"
    assert "Privacy gate failed closed" in result.reason
    assert "Presidio/NLP engine failure" in result.reason
