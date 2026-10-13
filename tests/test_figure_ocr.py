"""Figures on scanned pages and OCR-only detection (synthetic images and strings only)."""

import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw

from privacygate.derivatives import redact_pdf
from privacygate.detection import detect_pii
from privacygate.detection.names import DEFAULT_ALLOWLIST, NameRegistry, _Person
from privacygate.detection.ocr_text import (
    absorb_ocr_initials,
    column_role_names,
    ocr_emails,
    ocr_identifiers,
    ocr_surnames,
)
from privacygate.detection.common import make_entity
from privacygate.extraction import figures, ocr
from privacygate.extraction.pdf import extract_pdf
from privacygate.models import ContentBlock, Document
from privacygate.pipeline import run_pipeline


def _page(width=1200, height=1600):
    return Image.new("RGB", (width, height), "white")


def _ocr_data(words, confidence=95, left=10, top=10, width=60, height=20):
    count = len(words)
    return {"text": words, "conf": [confidence] * count, "block_num": [1] * count, "par_num": [1] * count,
            "line_num": [1] * count, "left": [left + (width + 10) * i for i in range(count)],
            "top": [top] * count, "width": [width] * count, "height": [height] * count}


# --- finding figures ------------------------------------------------------------

def test_framed_figure_is_found_and_cropped_to_its_content():
    image = _page()
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 200, 1100, 600), outline=(200, 200, 200), width=2)
    draw.rectangle((300, 300, 700, 400), fill=(40, 40, 40))  # figure content
    boxes = figures.find_figures(np.asarray(image.convert("L")))
    assert len(boxes) == 1
    x0, y0, x1, y1 = boxes[0]
    assert (x0, y0) == (300, 300) and abs(x1 - 701) <= 1 and abs(y1 - 401) <= 1


def test_borderless_tinted_panel_is_found_but_text_lines_are_not():
    image = _page()
    draw = ImageDraw.Draw(image)
    draw.rectangle((200, 900, 800, 1300), fill=(225, 225, 230))  # pasted badge-like image
    for y in range(100, 400, 30):  # thin text-like strokes
        draw.rectangle((100, y, 1000, y + 3), fill=(0, 0, 0))
    boxes = figures.find_figures(np.asarray(image.convert("L")))
    assert boxes == [(200, 900, 800, 1300)]


def test_local_normalisation_turns_light_on_dark_into_dark_on_light():
    image = Image.new("L", (400, 200), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 199, 199), fill=30)  # dark sidebar
    draw.rectangle((60, 98, 140, 101), fill=230)  # a thin light stroke on it
    draw.rectangle((260, 98, 340, 101), fill=20)  # a thin dark stroke on the light half
    flat = np.asarray(figures.local_normalise(image))
    assert flat[100, 100] < flat[20, 20]  # sidebar text darker than sidebar background
    assert flat[100, 300] < flat[20, 380]


def test_figure_text_is_mapped_back_to_page_pixels_and_low_confidence_is_unreadable(monkeypatch):
    image = _page()
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 200, 1100, 600), outline=(200, 200, 200), width=2)
    draw.rectangle((300, 300, 700, 400), fill=(40, 40, 40))

    def fake(variant, label, dpi=None, config=""):
        return _ocr_data(["Quilla", "Marsh"], left=30, top=60), 1

    monkeypatch.setattr(figures, "run_ocr", fake)
    [figure] = figures.extract_figures(image, 1)
    assert figure.readable and figure.lines[0].text == "Quilla Marsh"
    left, top, _, _ = figure.lines[0].word_boxes[0]
    assert (left, top) == (300 + 30 // 3, 300 + 60 // 3)  # first variant is 3x

    monkeypatch.setattr(figures, "run_ocr", lambda *a, **k: (_ocr_data(["x", "~"], confidence=20), 1))
    [figure] = figures.extract_figures(image, 1)
    assert not figure.readable


def test_textured_area_without_text_is_reported_as_a_photo():
    rng = np.random.default_rng(7)
    gray = np.full((800, 800), 255, dtype=np.uint8)
    gray[200:400, 200:380] = rng.integers(0, 255, (200, 180), dtype=np.uint8)
    photos = figures._photo_regions(gray, (100, 100, 700, 700), [])
    assert len(photos) == 1
    x0, y0, x1, y1 = photos[0]
    assert x0 <= 200 and y0 <= 200 and x1 >= 370 and y1 >= 390


def test_barcode_is_found_and_text_lines_are_not():
    gray = np.full((600, 900), 255, dtype=np.uint8)
    for x in range(200, 500, 6):  # vertical bars of a 1D barcode
        gray[300:350, x:x + 3] = 0
    for y in range(100, 200, 20):  # text-like strokes: vary down the rows
        gray[y:y + 3, 100:800] = 0
    regions = figures._barcode_regions(gray, (50, 50, 850, 550))
    assert len(regions) == 1
    x0, y0, x1, y1 = regions[0]
    assert x0 <= 212 and x1 >= 488 and y0 <= 314 and y1 >= 360  # with the printed line under it
    assert y1 < 420


# --- scanned PDF integration ------------------------------------------------------

def _scanned_pdf(tmp_path, draw_figure):
    image = Image.new("RGB", (2550, 3300), "white")
    draw = ImageDraw.Draw(image)
    draw_figure(draw)
    image_path = tmp_path / "page.png"
    image.save(image_path)
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_image(page.rect, filename=str(image_path))
        pdf.save(path)
    return path


def _framed(draw):
    draw.rectangle((300, 1000, 2250, 1800), outline=(200, 200, 200), width=3)
    draw.rectangle((600, 1200, 1800, 1500), fill=(60, 60, 60))


def _fake_tesseract(page_words, figure_words, figure_confidence=95):
    def image_to_data(image, lang="eng", config="", output_type=None, timeout=0):
        if "--psm 3" in config:
            return _ocr_data(page_words, left=300, top=300, width=200, height=60)
        return _ocr_data(figure_words, confidence=figure_confidence, left=30, top=30)
    return image_to_data


def test_scanned_pdf_gets_figure_blocks_and_figure_metadata(tmp_path, monkeypatch):
    path = _scanned_pdf(tmp_path, _framed)
    monkeypatch.setattr(ocr.shutil, "which", lambda command: "tesseract")
    monkeypatch.setattr(ocr.pytesseract, "image_to_data",
                        _fake_tesseract(["Policy", "text", "for", "the", "risk", "register"],
                                        ["Owner", "Quilla", "Marsh"]))
    document = extract_pdf(path)
    figure_blocks = [b for b in document.blocks if b.extraction_method == "figure_ocr"]
    assert [b.text for b in figure_blocks] == ["Owner Quilla Marsh"]
    meta = figure_blocks[0].metadata
    assert meta["region_bbox_pixels"] == document.metadata["figure_regions"][0]["bbox_pixels"]
    assert len(meta["word_boxes_pixels"]) == 3 and meta["render_dpi"] == 300
    assert document.metadata["figure_regions"][0]["readable"] is True


def test_redacted_pdf_masks_unreadable_figures_and_reports_them(tmp_path, monkeypatch):
    path = _scanned_pdf(tmp_path, _framed)
    monkeypatch.setattr(ocr.shutil, "which", lambda command: "tesseract")
    monkeypatch.setattr(ocr.pytesseract, "image_to_data",
                        _fake_tesseract(["Policy", "text", "for", "the", "risk", "register"], ["~", "#"], 15))
    document = extract_pdf(path)
    [region] = document.metadata["figure_regions"]
    assert region["readable"] is False
    masked = redact_pdf(path, document, document)
    assert masked.unreadable_figures == 1 and masked.figure_scan_failures == 0
    x0, y0, x1, y1 = region["bbox_pixels"]
    with pymupdf.open(stream=masked.data, filetype="pdf") as pdf:
        pixmap = pdf[0].get_pixmap(dpi=300)
        assert pixmap.pixel((x0 + x1) // 2, y0 + 10) == (0, 0, 0)  # was dark grey: now masked
        assert pixmap.pixel(100, 3200) == (255, 255, 255)  # outside the figure untouched


def test_unreadable_figure_text_is_withheld_from_the_sanitized_text_too(tmp_path, monkeypatch):
    path = _scanned_pdf(tmp_path, _framed)

    def image_to_data(image, lang="eng", config="", output_type=None, timeout=0):
        if "--psm 3" in config:  # page OCR: one line above the figure, one inside it
            data = _ocr_data(["Policy", "text", "for", "the", "risk", "register"], left=300, top=300, width=200)
            inside = _ocr_data(["Qx", "Brennick", "7741"], left=700, top=1300, width=150)
            for key in ("text", "conf", "left", "top", "width", "height"):
                data[key] += inside[key]
            data["block_num"] += [2] * 3
            data["par_num"] += [1] * 3
            data["line_num"] += [1] * 3
            return data
        return _ocr_data(["Qx", "Brennick", "~#"], confidence=15, left=30, top=30)

    monkeypatch.setattr(ocr.shutil, "which", lambda command: "tesseract")
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", image_to_data)
    result = run_pipeline(path)
    text = {block.block_id: block.text for block in result.sanitized_document.blocks}
    inside = [b.block_id for b in result.document.blocks
              if b.extraction_method == "figure_ocr" or "Brennick" in b.text]
    assert len(inside) == 2 and all(text[block_id] == "[FIGURE_UNREADABLE_1]" for block_id in inside)
    assert not any("Brennick" in value for value in text.values())
    assert any(value == "Policy text for the risk register" for value in text.values())
    assert result.audit_report.unreadable_figures == 1
    assert result.validation.status == "APPROVED"  # the token is issued, not an unknown placeholder
    masked = redact_pdf(path, result.document, result.sanitized_document)
    assert masked.unreadable_figures == 1


def test_redacted_pdf_masks_detected_values_inside_readable_figures(tmp_path, monkeypatch):
    path = _scanned_pdf(tmp_path, _framed)
    monkeypatch.setattr(ocr.shutil, "which", lambda command: "tesseract")
    monkeypatch.setattr(ocr.pytesseract, "image_to_data",
                        _fake_tesseract(["Policy", "text", "for", "the", "risk", "register"],
                                        ["Mail", "q.marsh@example.test", "today"]))
    document = extract_pdf(path)
    block = next(b for b in document.blocks if b.extraction_method == "figure_ocr")
    sanitized = Document(document.document_id, document.filename, "pdf", blocks=[
        ContentBlock(b.block_id, b.text.replace("q.marsh@example.test", "[EMAIL_001]"), page_number=b.page_number,
                     extraction_method=b.extraction_method, metadata=dict(b.metadata))
        for b in document.blocks
    ])
    masked = redact_pdf(path, document, sanitized)
    assert masked.by_method == {"figure_ocr": 1} and masked.unreadable_figures == 0
    left, top, right, bottom = block.metadata["word_boxes_pixels"][1]
    with pymupdf.open(stream=masked.data, filetype="pdf") as pdf:
        assert pdf[0].get_pixmap(dpi=300).pixel((left + right) // 2, (top + bottom) // 2) == (0, 0, 0)


def test_photo_regions_are_masked_and_counted(tmp_path):
    path = _scanned_pdf(tmp_path, lambda draw: None)
    document = Document("d", "scan.pdf", "pdf", blocks=[], metadata={"figure_regions": [{
        "page": 1, "figure": 1, "bbox_pixels": [300, 300, 1500, 1500], "render_dpi": 300, "confidence": 90.0,
        "readable": True, "photos": [[400, 400, 700, 800]], "variant": "gray3x/psm6"}]})
    masked = redact_pdf(path, document, document)
    assert masked.photos == 1 and masked.unreadable_figures == 0
    with pymupdf.open(stream=masked.data, filetype="pdf") as pdf:
        pixmap = pdf[0].get_pixmap(dpi=300)
        assert pixmap.pixel(550, 600) == (0, 0, 0) and pixmap.pixel(1200, 1200) == (255, 255, 255)


def test_failed_figure_scan_is_reported(tmp_path):
    path = _scanned_pdf(tmp_path, lambda draw: None)
    document = Document("d", "scan.pdf", "pdf", blocks=[], metadata={"figure_regions": [{
        "page": 1, "figure": 0, "bbox_pixels": None, "render_dpi": 300, "confidence": 0.0,
        "readable": False, "photos": [], "variant": "failed"}]})
    assert redact_pdf(path, document, document).figure_scan_failures == 1


# --- OCR-only detection -----------------------------------------------------------

def _ocr_block(text, block_id="f1", method="figure_ocr", boxes=None, **meta):
    metadata = dict(meta)
    if boxes is not None:
        metadata["word_boxes_pixels"] = boxes
        metadata["bbox_pixels"] = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                                   max(b[2] for b in boxes), max(b[3] for b in boxes)]
    return ContentBlock(block_id, text, page_number=1, extraction_method=method, metadata=metadata)


def _seed():
    block = ContentBlock("seed", "Contact a.b@quarrytel.example now", page_number=1, extraction_method="pdf_native")
    return block, [make_entity(block, "EMAIL_ADDRESS", 8, 30, 1.0, "regex:email")]


@pytest.mark.parametrize("text,value", [
    ("Auditor enily martinez @quarnytel.example May", "enily martinez @quarnytel.example"),
    ("John Davis john davis@oquarrytel.example Admin", "john davis@oquarrytel.example"),
    ("Risk robert joonsondpquarrytel.example Manager", "robert joonsondpquarrytel.example"),
    ("user=p.raghavantquarrytei com src", "p.raghavantquarrytei com"),
    ("Head | s,marcheni@quarrytel.example | +1", "s,marcheni@quarrytel.example"),
    ("mail t.okoro@quarrytel, Head of Risk", "t.okoro@quarrytel"),  # ", Head" is not a TLD
])
def test_damaged_emails_on_a_domain_seen_intact_are_found(text, value):
    seed, entities = _seed()
    block = _ocr_block(text)
    found = [block.text[e.start:e.end] for e in ocr_emails([seed, block], entities, DEFAULT_ALLOWLIST)]
    assert found == [value]


@pytest.mark.parametrize("text,method", [
    ("Quarrytel Financial Group annual report", "figure_ocr"),  # the company name, no address
    ("see @quarrytel.example for details", "figure_ocr"),  # bare domain, no local part
    ("Risk robert joonsondpquarrytel.example Manager", "pdf_native"),  # native text: regular detectors only
])
def test_damaged_email_rule_needs_ocr_text_and_a_local_part(text, method):
    seed, entities = _seed()
    assert not ocr_emails([seed, _ocr_block(text, method=method)], entities, DEFAULT_ALLOWLIST)


def test_damaged_registered_surnames_are_found_only_capitalised_and_long_enough():
    registry = NameRegistry([_Person("Hedda", "Vorstermann"), _Person("Ola", "Bell")])
    block = _ocr_block("Owner Vorsbermann; also vorsbermann and Belk")
    assert [block.text[e.start:e.end] for e in ocr_surnames([block], registry)] == ["Vorsbermann"]


def test_ocr_initials_in_front_of_a_name_are_absorbed():
    block = _ocr_block("owner H, Vorstermann and KC Burney")
    people = [make_entity(block, "PERSON", 9, 20, 0.9, "name_sweep"),
              make_entity(block, "PERSON", 28, 34, 0.9, "name_sweep")]
    assert [block.text[e.start:e.end] for e in absorb_ocr_initials([block], people)] == [
        "H, Vorstermann", "KC Burney"]


@pytest.mark.parametrize("text,entity_type,value", [
    ("Passpon TK4820913", "GOVERNMENT_ID", "TK4820913"),
    ("PAN AQERPR7741L", "GOVERNMENT_ID", "AQERPR7741L"),
    ("src_ip-198.51,100.62 reason", "IP_ADDRESS", "198.51,100.62"),
    ("DOB 0912/1994", "DATE_OF_BIRTH", "0912/1994"),
])
def test_ocr_identifier_rules(text, entity_type, value):
    block = _ocr_block(text)
    assert [(e.entity_type, text[e.start:e.end]) for e in ocr_identifiers([block])] == [(entity_type, value)]


def test_dob_label_with_its_date_on_the_next_line():
    label, value = _ocr_block("DATE OF BIRTH", "l1"), _ocr_block("PHOTOGRAPH ON FILE 28 February 1979", "l2")
    found = ocr_identifiers([label, value])
    assert [(e.block_id, value.text[e.start:e.end]) for e in found] == [("l2", "28 February 1979")]


def test_date_printed_under_a_damaged_birth_label_on_a_badge():
    def word_line(block_id, words, top):
        boxes, x = [], words[0][0]
        for x, word in words:
            boxes.append([x, top, x + 9 * len(word), top + 10])
        return _ocr_block(" ".join(w for _, w in words), block_id, boxes=boxes, figure=1)
    blocks = [
        word_line("a", [(1146, "DATE")], 2774),
        word_line("b", [(1201, "IF"), (1220, "BIRTH")], 2774),
        word_line("c", [(898, "PHOTOGRAPH"), (1000, "ON"), (1030, "FILE")], 2796),
        word_line("d", [(1145, "28"), (1170, "Februa")], 2794),
        word_line("e", [(1286, "1979")], 2794),
        word_line("f", [(1146, "ISSUED"), (1220, "02"), (1245, "Jan")], 2840),  # too far below
    ]
    found = {(e.block_id, next(b for b in blocks if b.block_id == e.block_id).text[e.start:e.end])
             for e in ocr_identifiers(blocks)}
    assert found == {("d", "28 Februa"), ("e", "1979")}


def test_amounts_and_plain_numbers_are_not_ocr_ips():
    assert not ocr_identifiers([_ocr_block("Totals 1,234,567,890 and 12.5,3.4,999.1")])


def _screenshot():
    """A UI table: Group name | Number of users | Created by | Created date."""
    def line(block_id, cells, top):
        words, boxes = [], []
        for x, text in cells:
            for word in text.split():
                boxes.append([x, top, x + 12 * len(word), top + 18])
                words.append(word)
                x += 12 * len(word) + 8
        return _ocr_block(" ".join(words), block_id, method="embedded_image_ocr", boxes=boxes, image_name="i.png")
    return [
        line("h", [(100, "Group name"), (400, "Number of users"), (700, "Created by"), (1000, "Created date")], 50),
        line("r1", [(100, "App Assignment"), (400, "2"), (700, "OneTrust User"), (1000, "02/10/2024")], 100),
        line("r2", [(100, "Engineering"), (400, "401"), (700, "Tobin Read"), (1000, "05/10/2023")], 150),
        line("side", [(0, "Users")], 175),  # sidebar, left of the table
        line("r3", [(100, "Infra Team"), (400, "3"), (700, "Dayo Seton"), (1000, "05/24/2025")], 200),
        line("end", [(100, "Showing 1 to 3 Quinn Hale")], 300),  # ends the table
        line("after", [(100, "Ops Desk"), (400, "4"), (700, "Wren Abbott"), (1000, "05/24/2025")], 350),
    ]


def test_names_under_a_person_column_of_an_ocr_table():
    blocks = _screenshot()
    found = {(e.block_id, next(b for b in blocks if b.block_id == e.block_id).text[e.start:e.end])
             for e in column_role_names(blocks, DEFAULT_ALLOWLIST)}
    # "App Assignment" sits under "Group name" (not a person column); "OneTrust User" is a role.
    assert found == {("r2", "Tobin Read"), ("r3", "Dayo Seton")}


def test_screenshot_names_with_common_word_surnames_are_redacted_end_to_end():
    blocks = _screenshot()
    document = Document("d", "pack.docx", "docx", blocks=blocks)
    values = {next(b for b in blocks if b.block_id == e.block_id).text[e.start:e.end]
              for e in detect_pii(document) if e.entity_type == "PERSON"}
    assert {"Tobin Read", "Dayo Seton"} <= values
