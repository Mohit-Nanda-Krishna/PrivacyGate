"""Span repairs for OCR'd text: pieces of a value left outside its detection (synthetic strings only)."""

from privacygate.detection import detect_pii, detect_regex
from privacygate.detection.common import make_entity
from privacygate.detection.names import NameRegistry, _Person
from privacygate.detection.span_repair import (
    attached_characters,
    figure_duplicates,
    registered_first_names,
    wrapped_initials,
    wrapped_prefixes,
)
from privacygate.models import ContentBlock, Document

REGISTRY = NameRegistry([_Person("Ismay", "Corvell"), _Person("Zelda", "Quarkington"), _Person(None, "Brightwell")])


def _line(block_id, text, page=1, method="ocr", **metadata):
    return ContentBlock(block_id, text, page_number=page, extraction_method=method, metadata=metadata)


def _person(block, value):
    start = block.text.index(value)
    return make_entity(block, "PERSON", start, start + len(value), 0.9, "name_sweep")


def _texts(entities, blocks):
    by_id = {block.block_id: block for block in blocks}
    return {(e.block_id, e.entity_type, by_id[e.block_id].text[e.start:e.end]) for e in entities}


def test_initials_on_their_own_line_before_a_name():
    blocks = [_line("a", "M"), _line("b", "Corvell"), _line("c", "D"), _line("d", "uarkington"),
              _line("e", "HR"), _line("f", "Corvell")]
    found = _texts(wrapped_initials(blocks, [_person(blocks[1], "Corvell"), _person(blocks[5], "Corvell")],
                                    REGISTRY), blocks)
    # "uarkington" is within OCR distance of a registered surname; "HR" is a word, not initials.
    assert found == {("a", "PERSON", "M"), ("c", "PERSON", "D"), ("d", "PERSON", "uarkington")}


def test_initials_at_the_end_of_a_line_before_a_wrapped_name():
    blocks = [_line("a", "reports to the Chair (A. P."), _line("b", "Brightwell)")]
    found = _texts(wrapped_initials(blocks, [_person(blocks[1], "Brightwell")], REGISTRY), blocks)
    assert found == {("a", "PERSON", "A. P.")}


def test_misread_or_glued_first_names_of_registered_people():
    blocks = [_line("a", "Internal Audit lsmay R. Corvell EMP-1"), _line("b", "Owner IsmayR. Corvell today"),
              _line("c", "Owner Maple Corvell today")]
    entities = [_person(blocks[0], "R. Corvell"), _person(blocks[1], "Corvell"), _person(blocks[2], "Corvell")]
    found = _texts(registered_first_names(blocks, entities, REGISTRY), blocks)
    assert found == {("a", "PERSON", "lsmay R. Corvell"), ("b", "PERSON", "IsmayR. Corvell")}


def test_glued_characters_are_absorbed():
    blocks = [_line("a", "+46 8 5555 0121 desk"), _line("b", "Chair: Ismay Corvell'!l next"),
              _line("c", "Analyst (t corvell@quarry.example, ext)"), _line("d", "+46 8 5555 0121 desk", method="pdf_native")]
    entities = [make_entity(blocks[0], "PHONE_NUMBER", 7, 15, 0.9, "regex:phone"),  # "555 0121"
                _person(blocks[1], "Ismay Corvell"),
                make_entity(blocks[2], "EMAIL_ADDRESS", 11, 32, 0.9, "regex:email"),
                make_entity(blocks[3], "PHONE_NUMBER", 7, 15, 0.9, "regex:phone")]
    found = _texts(attached_characters(blocks, entities), blocks)
    assert found == {("a", "PHONE_NUMBER", "5555 0121"), ("b", "PERSON", "Ismay Corvell'!l"),
                     ("c", "EMAIL_ADDRESS", "t corvell@quarry.example")}  # native text is left alone


def _with_regex(blocks):
    return [entity for block in blocks for entity in detect_regex(block)]


def test_wrapped_phone_prefix_is_joined_when_the_detectors_accept_the_whole_number():
    blocks = [_line("a", "Credit Risk q.ferrant@quarry.example, +1 (212) GRP-POL-002"),
              _line("b", "(EMP-48120) 555-0136"),
              _line("c", "NED z.quark@quarry.example, +1 14 Mar 2021"),
              _line("d", "(212) 555-0108"),
              _line("e", "Market Risk a.pill@quarry.example, +91 98860 GRP-POL-003"),
              _line("f", "55107")]
    found = _texts(wrapped_prefixes(blocks, _with_regex(blocks)), blocks)
    assert ("a", "PHONE_NUMBER", "+1 (212)") in found
    assert ("c", "PHONE_NUMBER", "+1") in found  # "14 Mar" is a date, not an area code
    assert ("f", "PHONE_NUMBER", "55107") in found


def test_wrapped_identifier_prefix_needs_a_valid_joined_identifier():
    blocks = [_line("a", "reported by Bienvenu Salcedo (MER-"), _line("b", "Manila desk PH-2214)"),
              _line("c", "see SEC-"), _line("d", "Section 4-1000 applies")]
    found = _texts(wrapped_prefixes(blocks, _with_regex(blocks)), blocks)
    assert found == {("a", "EMPLOYEE_ID", "MER-"), ("b", "EMPLOYEE_ID", "PH-2214")}


def test_page_ocr_of_a_detected_figure_word_is_redacted_too():
    figure = _line("f", "28 Februa 1979", method="figure_ocr", figure=1,
                   word_boxes_pixels=[[100, 100, 130, 120], [135, 100, 200, 120], [205, 100, 250, 120]])
    page = _line("p", "PHOTOGRAPH ON FILE 28 February 1979 ;", word_boxes_pixels=[
        [10, 100, 90, 120], [10, 130, 40, 150], [45, 130, 80, 150],
        [101, 101, 131, 121], [134, 101, 205, 121], [206, 101, 251, 121], [255, 100, 270, 120]])
    entity = make_entity(figure, "DATE_OF_BIRTH", 0, 14, 0.85, "pattern:ocr_dob")
    found = _texts(figure_duplicates([figure, page], [entity]), [figure, page])
    assert found == {("p", "DATE_OF_BIRTH", "28 February 1979")}


def test_chair_label_is_person_context():
    document = Document("d", "board.pdf", "pdf", blocks=[_line("a", "Chair: Quillon Ferrant", method="pdf_native")])
    values = {document.blocks[0].text[e.start:e.end] for e in detect_pii(document) if e.entity_type == "PERSON"}
    assert "Quillon Ferrant" in values
