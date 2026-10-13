"""Synthetic personnel identifiers with context, without benchmark examples."""

import pytest

from privacygate.detection import detect_custom, detect_pii
from privacygate.llm import GateRefusedError, mock_llm_call
from privacygate.models import ContentBlock, Document
from privacygate.redaction import PseudonymSession, redact_document
from privacygate.risk import classify_risks
from privacygate.validation import validate_privacy
from privacygate.validation.residual_checks import independent_residual_checks


def _doc(*blocks: ContentBlock) -> Document:
    return Document("synthetic", "synthetic.docx", "docx", blocks=list(blocks))


def _table(header: str, value: str) -> Document:
    def cell(block_id: str, text: str, row: int) -> ContentBlock:
        return ContentBlock(
            block_id, text, page_number=1,
            metadata={"kind": "table_cell", "table_number": 1,
                      "row_number": row, "column_number": 2},
        )

    return _doc(cell("header", header, 1), cell("value", value, 2))


@pytest.mark.parametrize("label,value", [
    ("Employee ID", "QXR-48271"),
    ("Employee Number", "N7K42B"),
    ("Staff ID", "TLM-8042"),
    ("Staff Code", "V8R52A"),
    ("Personnel ID", "PZX-90541"),
    ("Associate ID", "K4N82Q"),
    ("Staff No.", "V8R_52A"),
    ("Staff ID", "482731"),
    ("Personnel ID", "583921"),
    ("Associate ID", "729104"),
    ("Employee Number", "12345"),
    ("Staff Code", "1234567890"),
])
def test_labeled_personnel_id_offsets_and_provenance(label: str, value: str) -> None:
    text = f"Review complete. {label}: {value}; proceed."
    entity = next(e for e in detect_custom(text, block_id="prose") if e.entity_type == "EMPLOYEE_ID")
    assert (entity.start, entity.end) == (text.index(value), text.index(value) + len(value))
    assert entity.detector.startswith("custom:")
    assert entity.block_id == "prose"


@pytest.mark.parametrize("header,value", [
    ("Staff Code", "V8R52A"),
    ("Personnel ID", "QXR-48271"),
    ("Associate ID", "K4N82Q"),
    ("Staff ID", "482731"),
    ("Personnel ID", "583921"),
    ("Associate ID", "729104"),
])
def test_table_header_detects_personnel_id_and_preserves_location(header: str, value: str) -> None:
    entity = next(e for e in detect_pii(_table(header, value)) if e.entity_type == "EMPLOYEE_ID")
    assert (entity.block_id, entity.start, entity.end) == ("value", 0, len(value))
    assert entity.source_location["row_number"] == 2
    assert entity.source_location["column_number"] == 2
    assert "table_header" in entity.detector


@pytest.mark.parametrize("document", [
    _doc(ContentBlock("prose", "Staff ID: V8R52A", page_number=1)),
    _table("Associate ID", "K4N82Q"),
    _doc(ContentBlock("numeric", "Staff ID: 482731", page_number=1)),
    _table("Associate ID", "729104"),
])
def test_personnel_id_redacts_and_sanitized_document_is_approved(document: Document) -> None:
    entities = classify_risks(detect_pii(document))
    assert any(e.entity_type == "EMPLOYEE_ID" and e.risk_level == "HIGH" for e in entities)
    session = PseudonymSession()
    sanitized, records = redact_document(document, entities, session=session)
    assert any(record.placeholder == "[EMPLOYEE_ID_001]" for record in records)
    assert all(value not in b.text for b in sanitized.blocks
               for value in ("V8R52A", "K4N82Q", "482731", "729104"))
    assert validate_privacy(sanitized, issued_tokens=session.issued_tokens).status == "APPROVED"


@pytest.mark.parametrize("document", [
    _doc(ContentBlock("prose", "Personnel ID: PZX-90541", page_number=1)),
    _table("Staff Code", "V8R52A"),
    _doc(ContentBlock("numeric", "Personnel ID: 583921", page_number=1)),
    _table("Staff ID", "482731"),
])
def test_independent_gate_blocks_surviving_personnel_id(monkeypatch, document: Document) -> None:
    monkeypatch.setattr("privacygate.validation.privacy_gate.detect_pii", lambda doc: [])
    result = validate_privacy(document)
    assert result.status == "BLOCKED"
    assert any(e.entity_type == "EMPLOYEE_ID" and "gate:" in e.detector for e in result.residual_entities)
    assert all(value not in result.reason for value in ("PZX-90541", "V8R52A", "583921", "482731"))
    with pytest.raises(GateRefusedError):
        mock_llm_call(document, result, "Summarize")


@pytest.mark.parametrize("text", [
    "Reference: QXR-48271",
    "Project Code: V8R52A",
    "Staff ID: ISS-2026-0112",
    "Personnel ID: 2026-06-11",
    "Staff ID: 2026-06-11T08:30",
    "Reference: 482731",
    "Staff ID: 1234",
    "Staff ID: 12345678901",
])
def test_business_references_and_dates_are_not_personnel_ids(text: str) -> None:
    block = ContentBlock("business", text)
    assert not [e for e in detect_custom(block) if e.entity_type == "EMPLOYEE_ID"]
    assert not [e for e in independent_residual_checks([block]) if e.entity_type == "EMPLOYEE_ID"]


@pytest.mark.parametrize("document", [
    _doc(ContentBlock("business", "Reference: QXR-48271")),
    _table("Project Code", "V8R52A"),
    _table("Staff ID", "ISS-2026-0112"),
    _table("Staff ID", "2026-06-11"),
    _table("Project Code", "482731"),
])
def test_business_values_do_not_trigger_independent_personnel_gate(monkeypatch, document: Document) -> None:
    monkeypatch.setattr("privacygate.validation.privacy_gate.detect_pii", lambda doc: [])
    assert not [e for e in independent_residual_checks(document.blocks) if e.entity_type == "EMPLOYEE_ID"]
    assert validate_privacy(document).status == "APPROVED"


def test_issued_personnel_placeholder_passes_and_unissued_one_blocks(monkeypatch) -> None:
    monkeypatch.setattr("privacygate.validation.privacy_gate.detect_pii", lambda doc: [])
    document = _doc(ContentBlock("prose", "Staff ID: [EMPLOYEE_ID_001]"))
    assert validate_privacy(document, issued_tokens=frozenset({"[EMPLOYEE_ID_001]"})).status == "APPROVED"
    assert validate_privacy(document).status == "BLOCKED"
    assert validate_privacy(_doc(ContentBlock("legacy", "Staff ID: [EMPLOYEE_ID]"))).status == "APPROVED"
