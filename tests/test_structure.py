"""Extraction fidelity against XML references and hand transcriptions (synthetic files only)."""

from dataclasses import replace

import pytest
from docx import Document as WordDocument
from pptx import Presentation
from pptx.util import Inches

from privacygate.extraction import extract_document
from privacygate.models import ContentBlock, Document
from privacygate.structure import (
    character_coverage,
    docx_reference,
    load_transcriptions,
    office_fidelity,
    page_fidelity,
    pptx_reference,
    reading_order,
    scanned_fidelity,
    substring_distance,
)


@pytest.fixture
def docx_file(tmp_path):
    document = WordDocument()
    document.sections[0].header.paragraphs[0].text = "Synthetic Policy Header"
    document.add_heading("Purpose of the synthetic policy", level=1)
    document.add_paragraph("Quillon Ferrant owns the register and reviews it every quarter.")
    table = document.add_table(rows=2, cols=2)
    for (row, column), text in {(0, 0): "Owner", (0, 1): "Contact",
                                (1, 0): "Zelda Quark", (1, 1): "z.quark@example.test"}.items():
        table.cell(row, column).text = text
    document.add_paragraph("Closing paragraph after the table, with nothing personal in it.")
    path = tmp_path / "policy.docx"
    document.save(path)
    return path


@pytest.fixture
def pptx_file(tmp_path):
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    box.text_frame.text = "Quarterly risk briefing for the synthetic board"
    rows = slide.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(6), Inches(1)).table
    rows.cell(0, 0).text, rows.cell(0, 1).text = "Lead", "Mobile"
    rows.cell(1, 0).text, rows.cell(1, 1).text = "Ismay Corvell", "+1 555 0100"
    slide.notes_slide.notes_text_frame.text = "Speaker notes mention the escalation path."
    path = tmp_path / "deck.pptx"
    deck.save(path)
    return path


def test_docx_reference_is_read_from_xml_in_order(docx_file):
    reference = docx_reference(docx_file)
    assert reference.paragraphs[:3] == ["Purpose of the synthetic policy",
                                        "Quillon Ferrant owns the register and reviews it every quarter.", "Owner"]
    assert reference.paragraphs[-1] == "Synthetic Policy Header"  # header parts after the body
    assert (("docx", 1), 2, 1, "Zelda Quark") in reference.cells


def test_pptx_reference_has_shapes_tables_and_notes(pptx_file):
    reference = pptx_reference(pptx_file)
    assert "Quarterly risk briefing for the synthetic board" in reference.paragraphs
    assert reference.paragraphs[-1] == "Speaker notes mention the escalation path."
    assert (("pptx", 1), 2, 2, "+1 555 0100") in reference.cells


@pytest.mark.parametrize("fixture", ["docx_file", "pptx_file"])
def test_faithful_extraction_scores_full_marks(fixture, request):
    path = request.getfixturevalue(fixture)
    fidelity = office_fidelity(path, extract_document(path))
    assert fidelity.character_coverage == 1.0
    assert fidelity.reading_order == 1.0
    assert fidelity.table_cells == 1.0


def test_dropped_moved_and_damaged_blocks_lower_the_scores(docx_file):
    document = extract_document(docx_file)
    blocks = [block for block in document.blocks if "Closing paragraph" not in block.text]  # dropped
    cell = next(i for i, block in enumerate(blocks) if block.text == "Zelda Quark")
    blocks[cell] = replace(blocks[cell], text="Zelda")  # damaged cell
    blocks.insert(0, blocks.pop(next(i for i, b in enumerate(blocks) if b.text.startswith("Quillon"))))  # moved
    fidelity = office_fidelity(docx_file, Document(document.document_id, document.filename, "docx", blocks=blocks))
    assert fidelity.character_coverage < 1.0
    assert fidelity.reading_order < 1.0
    assert fidelity.table_cells == pytest.approx(3 / 4)


def test_coverage_and_order_helpers():
    assert character_coverage(["alpha beta", "gamma"], ["gamma alpha beta"]) == 1.0
    assert character_coverage(["alpha beta"], ["alpha"]) == pytest.approx(5 / 9)
    order, located = reading_order(["first paragraph here", "second paragraph here", "third paragraph here"],
                                   ["second paragraph here", "first paragraph here", "third paragraph here"])
    assert located == 3 and order == pytest.approx(1 / 2)


def test_substring_distance_ignores_text_around_the_match():
    assert substring_distance("Okonjo", "maintained by Delphine R. Okonjo today") == 0
    assert substring_distance("Okonjo", "maintained by Delphine R. 0konjo today") == 1


def test_scanned_page_cer_and_line_order():
    reference = ["Risk owner The named individual accountable for management.",
                 "Control owner The named individual accountable for design."]
    perfect = page_fidelity(5, reference, reference)
    assert perfect.cer == 0 and perfect.line_order == 1.0
    misread = page_fidelity(5, reference, [reference[0].replace("owner", "0wner"), reference[1]])
    assert misread.errors == 1
    # OCR read the term column first, then the definitions: no misread characters, order lost.
    columns = page_fidelity(5, reference, ["Risk owner", "Control owner",
                                           "The named individual accountable for management.",
                                           "The named individual accountable for design."])
    assert columns.cer == 0 and columns.line_order < 1.0
    lines = [reference[0], "Escalation follows within five business days."]
    missing = page_fidelity(5, lines, [reference[0]])
    assert missing.found_lines == 1 and missing.errors == sum(not c.isspace() for c in lines[1])


def test_transcriptions_load_and_score_the_ocr_pages(tmp_path):
    folder = tmp_path / "scan"
    folder.mkdir()
    (folder / "page_02.txt").write_text("# comment\nFirst line of page two\n\nSecond line of page two\n",
                                        encoding="utf-8")
    assert load_transcriptions(folder) == {2: ["First line of page two", "Second line of page two"]}
    document = Document("d", "scan.pdf", "pdf", blocks=[
        ContentBlock("a", "First line of page two", page_number=2, extraction_method="ocr"),
        ContentBlock("b", "Second line of page tw0", page_number=2, extraction_method="ocr"),
        ContentBlock("c", "Other page", page_number=3, extraction_method="ocr"),
    ])
    result = scanned_fidelity(document, load_transcriptions(folder))
    assert result["cer"] == pytest.approx(1 / 45, abs=1e-4) and result["line_order"] == 1.0
    assert result["pages"][0]["found_lines"] == 2
