"""Tests for Phase 3 secondary privacy validation gate."""

import pytest

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
    # Only the exception type is reported; messages can quote document text.
    assert result.reason.endswith("RuntimeError")
    assert "Presidio/NLP engine failure" not in result.reason


def test_failed_embedded_ocr_reason_reports_count_without_source_names() -> None:
    doc = Document(
        document_id="opaque", filename="synthetic.docx", file_type="docx",
        metadata={"embedded_images_failed": ["secret_image_name.png", "C:/private/image.png"]},
    )

    result = validate_privacy(doc)

    assert result.status == "BLOCKED"
    assert "2 embedded image(s)" in result.reason
    assert "secret_image_name.png" not in result.reason
    assert "C:/private" not in result.reason


def test_failed_page_reason_rejects_nonstructural_metadata() -> None:
    doc = Document(
        document_id="opaque", filename="synthetic.pdf", file_type="pdf",
        metadata={"ocr_failed_pages": [2, "SECRET_PERSON_VALUE_92731"]},
    )

    result = validate_privacy(doc)

    assert result.status == "BLOCKED"
    assert result.reason.endswith("TypeError")
    assert "SECRET_PERSON_VALUE_92731" not in result.reason


@pytest.mark.parametrize("key", ["ocr_failed_pages", "embedded_images_failed"])
@pytest.mark.parametrize("value", [7, 0, "SECRET_PERSON_VALUE_92731", "", None, True,
                                   [True], [object()], object(), {"secret": 1}])
def test_malformed_ocr_metadata_returns_controlled_blocked_result(key, value) -> None:
    doc = Document("source", "private.pdf", "pdf", metadata={key: value})

    result = validate_privacy(doc)

    assert result.status == "BLOCKED"
    assert result.residual_entities == []
    assert result.reason == "Privacy gate failed closed due to unexpected validation error: TypeError"


@pytest.mark.parametrize("pages", [["SECRET_PERSON_VALUE_92731"], [1, "2"], [0], [-1], [1.5]])
def test_failed_pages_require_positive_integers(pages) -> None:
    result = validate_privacy(Document("source", "private.pdf", "pdf", metadata={"ocr_failed_pages": pages}))
    assert result.status == "BLOCKED"
    assert result.reason == "Privacy gate failed closed due to unexpected validation error: TypeError"


@pytest.mark.parametrize("metadata", [None, 7, "SECRET_PERSON_VALUE_92731", object()])
def test_invalid_metadata_container_fails_closed(metadata) -> None:
    result = validate_privacy(Document("source", "private.pdf", "pdf", metadata=metadata))
    assert result.status == "BLOCKED"
    assert result.reason == "Privacy gate failed closed due to unexpected validation error: TypeError"


@pytest.mark.parametrize("pages", [[3, 1], (3, 1)])
def test_failed_page_sequence_preserves_structural_reason(pages) -> None:
    result = validate_privacy(Document("source", "private.pdf", "pdf", metadata={"ocr_failed_pages": pages}))
    assert result.status == "BLOCKED"
    assert "page(s) 1, 3" in result.reason
