"""Headers/footers, text boxes, speaker notes and embedded-image OCR (synthetic files only)."""

import io
import shutil

import pytest
from docx import Document as DocxDocument
from docx.oxml import parse_xml
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches

from privacygate.audit import audit_report_to_dict
from privacygate.extraction import OCRRequiredError, embedded, extract_document
from privacygate.pipeline import run_pipeline

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
V_NS = "urn:schemas-microsoft-com:vml"


def _png(width=800, height=300, text=None) -> io.BytesIO:
    image = Image.new("RGB", (width, height), "white")
    if text:
        ImageDraw.Draw(image).text((20, 20), text, fill="black")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    return stream


def _ocr_data(*lines):
    data = {k: [] for k in ("text", "block_num", "par_num", "line_num", "left", "top", "width", "height")}
    for number, line in enumerate(lines, start=1):
        for index, word in enumerate(line.split()):
            data["text"].append(word)
            data["block_num"].append(1)
            data["par_num"].append(1)
            data["line_num"].append(number)
            data["left"].append(10 + 60 * index)
            data["top"].append(30 * number)
            data["width"].append(50)
            data["height"].append(20)
    return data


@pytest.fixture
def fake_image_ocr(monkeypatch):
    calls = []

    def run(image, label, dpi=None):
        calls.append(label)
        return _ocr_data("Created by Zelda Quark", "Contact z.quark@example.test"), 1

    monkeypatch.setattr(embedded.shutil, "which", lambda command: "tesseract")
    monkeypatch.setattr(embedded, "run_ocr", run)
    return calls


def _docx(tmp_path, *, picture=True, tiny=False, emf=False):
    path = tmp_path / "embedded.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body paragraph about widgets.")
    section = doc.sections[0]
    section.header.paragraphs[0].text = "Header owner Ottoline Quarrington"
    section.footer.paragraphs[0].text = "Footer page marker"
    box = parse_xml(
        f'<w:r xmlns:w="{W_NS}" xmlns:v="{V_NS}"><w:pict><v:shape><v:textbox><w:txbxContent>'
        "<w:p><w:r><w:t>Text box contact Hesper Vale</w:t></w:r></w:p>"
        "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
    )
    doc.add_paragraph()._p.append(box)
    if picture:
        doc.add_picture(_png(), width=Inches(4))
    if tiny:
        doc.add_picture(_png(120, 60), width=Inches(1))
    doc.save(path)
    if emf:
        # Re-label one media part as EMF to exercise the vector-image warning path.
        import zipfile
        with zipfile.ZipFile(path) as source:
            items = {name: source.read(name) for name in source.namelist()}
        media = [name for name in items if name.startswith("word/media/")][0]
        items[media.rsplit(".", 1)[0] + ".emf"] = items.pop(media)
        for name in list(items):
            if name.endswith(".rels") or name == "[Content_Types].xml":
                items[name] = items[name].replace(media.rsplit("/", 1)[-1].encode(),
                                                  media.rsplit("/", 1)[-1].rsplit(".", 1)[0].encode() + b".emf")
        items["[Content_Types].xml"] = items["[Content_Types].xml"].replace(
            b"</Types>", b'<Default Extension="emf" ContentType="image/x-emf"/></Types>')
        with zipfile.ZipFile(path, "w") as target:
            for name, data in items.items():
                target.writestr(name, data)
    return path


def test_docx_headers_footers_text_boxes_and_images(tmp_path, fake_image_ocr):
    document = extract_document(_docx(tmp_path))
    kinds = {block.metadata.get("kind"): block for block in document.blocks}
    assert kinds["header"].text == "Header owner Ottoline Quarrington"
    assert kinds["footer"].text == "Footer page marker"
    assert kinds["text_box"].text == "Text box contact Hesper Vale"
    image_blocks = [b for b in document.blocks if b.extraction_method == "embedded_image_ocr"]
    assert [b.text for b in image_blocks] == ["Created by Zelda Quark", "Contact z.quark@example.test"]
    assert image_blocks[0].metadata["image_name"].startswith("image")
    assert image_blocks[0].metadata["bbox_pixels"] == [10, 30, 240, 50]  # 4 words, 60 px apart, 50 wide
    assert document.metadata["embedded_images"][0]["status"] == "ocr"
    assert len({b.block_id for b in document.blocks}) == len(document.blocks)


def test_tiny_and_vector_images_are_skipped_with_warnings(tmp_path, fake_image_ocr):
    document = extract_document(_docx(tmp_path, picture=False, tiny=True))
    assert fake_image_ocr == []
    assert document.metadata["embedded_images"][0]["status"] == "skipped_tiny"
    assert "tiny image" in document.metadata["extraction_warnings"][0]["reason"]

    document = extract_document(_docx(tmp_path, emf=True))
    assert document.metadata["embedded_images"][0]["status"] == "skipped_vector"
    assert "vector image (emf)" in document.metadata["extraction_warnings"][0]["reason"]


def test_failed_image_ocr_blocks_gate_and_is_audited(tmp_path, monkeypatch):
    monkeypatch.setattr(embedded.shutil, "which", lambda command: "tesseract")

    def broken(image, label, dpi=None):
        raise embedded.ExtractionError(f"OCR failed for {label} (the engine failed). Check Tesseract.")

    monkeypatch.setattr(embedded, "run_ocr", broken)
    result = run_pipeline(_docx(tmp_path), max_passes=2)
    assert result.validation.status == "BLOCKED"
    assert "embedded image" in result.validation.reason
    exported = audit_report_to_dict(result.audit_report)
    assert exported["extraction"]["embedded_images"][0]["status"] == "failed"


def test_missing_tesseract_with_raster_images_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(embedded.shutil, "which", lambda command: None)
    with pytest.raises(OCRRequiredError, match="embedded image"):
        extract_document(_docx(tmp_path))


def test_pptx_notes_and_pictures(tmp_path, fake_image_ocr):
    path = tmp_path / "deck.pptx"
    deck = Presentation()
    for _ in range(2):
        slide = deck.slides.add_slide(deck.slide_layouts[5])
        slide.shapes.title.text = "Quarterly widgets"
        slide.notes_slide.notes_text_frame.text = "Speaker notes: call Zelda Quark"
        slide.shapes.add_picture(_png(), Inches(1), Inches(2))
    deck.save(path)
    document = extract_document(path)
    notes = [b for b in document.blocks if b.metadata.get("kind") == "notes"]
    assert [(b.slide_number, b.text) for b in notes] == [(1, "Speaker notes: call Zelda Quark"),
                                                         (2, "Speaker notes: call Zelda Quark")]
    images = [b for b in document.blocks if b.extraction_method == "embedded_image_ocr"]
    assert images and all(b.slide_number == 1 for b in images)
    assert len(fake_image_ocr) == 1  # the same media file on two slides is OCR'd once


def test_audit_counts_pii_by_location(tmp_path, fake_image_ocr):
    result = run_pipeline(_docx(tmp_path))
    locations = audit_report_to_dict(result.audit_report)["counts_by_location"]
    assert locations.get("image", 0) >= 1  # e-mail found only inside the screenshot


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Local Tesseract executable unavailable")
def test_real_tesseract_reads_embedded_screenshot(tmp_path):
    path = tmp_path / "real.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body text.")
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    try:
        from PIL import ImageFont
        font = ImageFont.load_default(size=48)
    except TypeError:
        font = None
    draw.text((30, 100), "Synthetic Screenshot Label", fill="black", font=font)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    doc.add_picture(stream, width=Inches(5))
    doc.save(path)
    document = extract_document(path)
    text = " ".join(b.text for b in document.blocks if b.extraction_method == "embedded_image_ocr")
    assert "Screenshot" in text
