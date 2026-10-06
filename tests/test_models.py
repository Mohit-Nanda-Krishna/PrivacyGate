from dataclasses import asdict

from privacygate.models import AuditReport, ContentBlock, Document, PIIEntity, ValidationResult


def test_document_preserves_blocks_and_source_location():
    block = ContentBlock(
        block_id="page_1_block_1", text="Synthetic example", page_number=1,
        paragraph_number=1, extraction_method="native", metadata={"kind": "paragraph"},
    )
    document = Document(
        document_id="test-doc", filename="sample.pdf", file_type="pdf",
        metadata={"page_count": 1}, blocks=[block],
    )
    assert document.blocks[0].page_number == 1
    assert document.blocks[0].slide_number is None
    assert asdict(document)["blocks"][0]["text"] == "Synthetic example"
    assert "Synthetic example" not in repr(block)
    assert "sample.pdf" not in repr(document)


def test_entity_preserves_offsets_and_traceability_without_raw_value():
    entity = PIIEntity(
        entity_type="EMAIL", start=0, end=8, confidence=1.0,
        detector="regex", block_id="b1", source_location={"page_number": 1},
        risk_level="HIGH",
    )
    assert (entity.start, entity.end) == (0, 8)
    assert entity.source_location == {"page_number": 1}
    assert entity.risk_level == "HIGH"
    assert "text" not in asdict(entity)
    assert "value" not in asdict(entity)


def test_unvalidated_results_and_audits_default_to_blocked():
    result = ValidationResult()
    report = AuditReport(document_id="test-doc")
    assert result.status == report.validation.status == "BLOCKED"
    assert "not been performed" in result.reason
    assert report.detected_count == report.redacted_count == 0
    assert "text" not in asdict(report)
    assert "blocks" not in asdict(report)


def test_mutable_defaults_are_not_shared():
    first = Document("one", "one.pdf", "pdf")
    second = Document("two", "two.pdf", "pdf")
    first.blocks.append(ContentBlock("b1", "Synthetic example"))
    first.metadata["page_count"] = 1
    assert second.blocks == []
    assert second.metadata == {}

    first_report = AuditReport("one")
    second_report = AuditReport("two")
    first_report.counts_by_category["EMAIL"] = 1
    first_report.validation.reason = "Test reason"
    assert second_report.counts_by_category == {}
    assert second_report.validation.reason == "Privacy validation has not been performed."
