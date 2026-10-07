"""Masked PDF derivative, AI payload and mock model call (synthetic files only)."""

from pathlib import Path

import pymupdf
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from privacygate.derivatives import REVIEW_WATERMARK, redact_pdf, redacted_spans
from privacygate.extraction import extract_document, ocr
from privacygate.llm import GateRefusedError, build_llm_payload, mock_llm_call
from privacygate.models import ContentBlock, Document, ValidationResult
from privacygate.pipeline import run_pipeline

APP_PATH = Path(__file__).parents[1] / "app.py"


def _native_pdf(path: Path) -> Path:
    with pymupdf.open() as pdf:
        for text in ("Contact Quentin R. Abernathy at q.abernathy@example.test today.",
                     "Second page with ordinary policy wording and no personal data."):
            page = pdf.new_page()
            page.insert_text((72, 100), text, fontsize=11)
        pdf.set_metadata({"author": "Quentin R. Abernathy", "title": "Synthetic policy"})
        pdf.save(path)
    return path


def _text(data: bytes) -> str:
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        return "\n".join(page.get_text() for page in pdf)


def test_redacted_spans_follow_the_final_sanitized_text():
    original = "Owner Quentin Abernathy, mail q.a@example.test."
    sanitized = "Owner [PERSON_001], mail [EMAIL_001]."
    spans = [original[s:e] for s, e in redacted_spans(original, sanitized)]
    # Whole words are masked; no character of a value stays visible between masks.
    assert spans == ["Quentin Abernathy,", "q.a@example.test."]


def test_native_pdf_values_removed_layout_and_page_count_kept(tmp_path):
    source = _native_pdf(tmp_path / "policy.pdf")
    result = run_pipeline(source)
    masked = redact_pdf(source, result.document, result.sanitized_document)
    text = _text(masked.data)
    assert masked.page_count == 2 and masked.unlocated == 0
    assert "Abernathy" not in text and "example.test" not in text
    assert "Contact" in text and "ordinary policy wording" in text
    with pymupdf.open(stream=masked.data, filetype="pdf") as pdf:
        assert pdf.page_count == 2
        assert not pdf.metadata.get("author") and not pdf.metadata.get("title")


def test_later_pass_replacements_are_masked_too(tmp_path):
    source = _native_pdf(tmp_path / "policy.pdf")
    document = extract_document(source)
    sanitized = Document(document.document_id, document.filename, "pdf", blocks=[
        ContentBlock(b.block_id, b.text.replace("today", "[DATE_001]"), page_number=b.page_number,
                     extraction_method=b.extraction_method, metadata=dict(b.metadata))
        for b in document.blocks
    ])
    masked = redact_pdf(source, document, sanitized)
    assert "today" not in _text(masked.data)


def test_scanned_page_pixels_under_masks_are_destroyed(tmp_path, monkeypatch):
    path = tmp_path / "scan.pdf"
    image = Image.new("RGB", (2550, 3300), "white")
    stream_path = tmp_path / "page.png"
    image.save(stream_path)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_image(page.rect, filename=str(stream_path))
        pdf.save(path)
    words = ["Escalate", "to", "q.abernathy@example.test", "for", "approval", "of", "widgets"]
    data = {"text": words, "block_num": [1] * 7, "par_num": [1] * 7, "line_num": [1] * 7,
            "left": [300 + 400 * i for i in range(7)], "top": [600] * 7, "width": [350] * 7, "height": [60] * 7}
    monkeypatch.setattr(ocr.shutil, "which", lambda command: "tesseract")
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", lambda *a, **k: data)
    result = run_pipeline(path)
    masked = redact_pdf(path, result.document, result.sanitized_document)
    assert masked.by_method == {"ocr": 1}
    with pymupdf.open(stream=masked.data, filetype="pdf") as pdf:
        pixmap = pdf[0].get_pixmap(dpi=300)
        inside = pixmap.pixel(1100 + 175, 630)  # centre of the e-mail word box
        outside = pixmap.pixel(300 + 175, 630)  # "Escalate" stays
    assert inside == (0, 0, 0)
    assert outside == (255, 255, 255)


def test_review_watermark(tmp_path):
    source = _native_pdf(tmp_path / "policy.pdf")
    result = run_pipeline(source)
    masked = redact_pdf(source, result.document, result.sanitized_document, watermark=REVIEW_WATERMARK)
    assert _text(masked.data).count("REVIEW COPY") == 2


def _sanitized_doc():
    return Document("d", "s.pdf", "pdf", blocks=[
        ContentBlock("a", "Owner [PERSON_001] approved."), ContentBlock("b", "   "),
        ContentBlock("c", "Mail [EMAIL_001] and [PERSON_001]."),
    ])


def test_payload_is_exactly_the_sanitized_blocks():
    assert build_llm_payload(_sanitized_doc()) == "Owner [PERSON_001] approved.\nMail [EMAIL_001] and [PERSON_001]."


def test_mock_llm_refuses_unless_approved():
    with pytest.raises(GateRefusedError):
        mock_llm_call(_sanitized_doc(), ValidationResult(status="BLOCKED", reason="x"), "Summarise")
    reply = mock_llm_call(_sanitized_doc(), ValidationResult(status="APPROVED", reason="ok"), "Summarise")
    assert reply.tokens_seen == 3 and "[PERSON_001]" in reply.text
    assert reply.characters_sent == len(build_llm_payload(_sanitized_doc()))


def _app_with(result, masked):
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.session_state["redacted_pdf"] = masked
    return app.run(timeout=60)


def test_app_ai_tab_and_redacted_download_for_approved(tmp_path):
    source = _native_pdf(tmp_path / "policy.pdf")
    result = run_pipeline(source)
    assert result.validation.status == "APPROVED"
    app = _app_with(result, redact_pdf(source, result.document, result.sanitized_document))
    assert not app.exception
    assert any("What the AI Model Sees" in str(s.value) for s in app.subheader)
    payload = next(t for t in app.text_area if t.label == "Sanitized payload").value
    assert "Abernathy" not in payload and "[PERSON_" in payload
    send = next(b for b in app.button if b.label == "Send to mock LLM")
    send.click().run(timeout=60)
    assert any("[mock model]" in str(s.value) for s in app.success)


def test_app_blocked_document_refuses_and_gates_review_copy(tmp_path):
    source = _native_pdf(tmp_path / "policy.pdf")
    result = run_pipeline(source)
    result.validation = ValidationResult(status="BLOCKED", reason="synthetic block")
    app = _app_with(result, redact_pdf(source, result.document, result.sanitized_document,
                                       watermark=REVIEW_WATERMARK))
    assert not app.exception
    assert any("may still contain personal data" in str(w.value) for w in app.warning)
    review = next(c for c in app.checkbox if c.label.startswith("I understand"))
    assert review.value is False
    send = next(b for b in app.button if b.label == "Send to mock LLM")
    send.click().run(timeout=60)
    assert any("Refused" in str(e.value) for e in app.error)
