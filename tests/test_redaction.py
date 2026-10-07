"""Tests for Phase 3 semantic redaction."""

from privacygate.models import ContentBlock, Document, PIIEntity
from privacygate.redaction import get_placeholder, redact_document, redact_text


def test_get_placeholder() -> None:
    assert get_placeholder("PERSON") == "[PERSON]"
    assert get_placeholder("email") == "[EMAIL]"
    assert get_placeholder("EMPLOYEE_ID") == "[EMPLOYEE_ID]"


def test_redact_text_semantic_placeholders() -> None:
    text = "John Smith submitted the report to john@cadence.com."
    entities = [
        PIIEntity(entity_type="PERSON", start=0, end=10, confidence=0.9, detector="presidio", block_id="b1"),
        PIIEntity(entity_type="EMAIL", start=35, end=51, confidence=1.0, detector="regex", block_id="b1"),
    ]
    sanitized, records = redact_text(text, entities)
    assert sanitized == "[PERSON] submitted the report to [EMAIL]."
    assert len(records) == 2
    assert records[0].placeholder == "[PERSON]"
    assert records[1].placeholder == "[EMAIL]"


def test_redact_document_preserves_structure_and_non_mutating() -> None:
    b1 = ContentBlock(
        block_id="p1_b1",
        text="Author: Alice Smith (EMP-12345).",
        page_number=1,
        paragraph_number=1,
    )
    b2 = ContentBlock(
        block_id="p1_b2",
        text="No sensitive data here.",
        page_number=1,
        paragraph_number=2,
    )
    original_doc = Document(
        document_id="doc_redact_1",
        filename="report.docx",
        file_type="docx",
        blocks=[b1, b2],
    )

    entities = [
        PIIEntity(entity_type="PERSON", start=8, end=19, confidence=0.9, detector="presidio", block_id="p1_b1"),
        PIIEntity(entity_type="EMPLOYEE_ID", start=21, end=30, confidence=0.98, detector="custom_enterprise", block_id="p1_b1"),
    ]

    sanitized_doc, records = redact_document(original_doc, entities)

    # Original document is unchanged
    assert original_doc.blocks[0].text == "Author: Alice Smith (EMP-12345)."

    # Sanitized document has placeholders
    assert sanitized_doc.blocks[0].text == "Author: [PERSON] ([EMPLOYEE_ID])."
    assert sanitized_doc.blocks[1].text == "No sensitive data here."
    assert sanitized_doc.blocks[0].page_number == 1
    assert sanitized_doc.blocks[0].paragraph_number == 1
    assert len(records) == 2
