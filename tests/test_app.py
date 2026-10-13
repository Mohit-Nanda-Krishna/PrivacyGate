"""Tests for Streamlit user interface."""

from pathlib import Path
import re
import runpy

import pytest
import pytesseract
import streamlit as st
from streamlit.testing.v1 import AppTest

from privacygate.audit import audit_report_to_json
from privacygate.extraction import ocr
from privacygate.models import AuditReport, ContentBlock, Document, ValidationResult
from privacygate.pipeline import PipelineResult, run_pipeline

APP_PATH = Path(__file__).parents[1] / "app.py"
FIXTURES = Path(__file__).parent / "fixtures"


def test_streamlit_app_loads_successfully() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
    assert not app.exception
    assert any("PrivacyGate" in str(m.value) for m in app.markdown)
    assert len(app.file_uploader) == 1
    assert len(app.selectbox) == 1


def test_results_render_page_report_and_failed_page_warning(tmp_path, monkeypatch) -> None:
    runpy.run_path(str(FIXTURES / "generate_fixtures.py"))["generate_ocr_fixtures"](tmp_path)
    monkeypatch.setattr(ocr.shutil, "which", lambda command: "tesseract")

    def failing_engine(*args, **kwargs):
        raise pytesseract.TesseractError(1, "engine failed")

    monkeypatch.setattr(ocr.pytesseract, "image_to_data", failing_engine)
    result = run_pipeline(tmp_path / "mixed.pdf")

    serialized_reports = []
    audit_downloads = []
    original_download = st.download_button

    def capture_serializer(report):
        serialized_reports.append(report)
        return audit_report_to_json(report)

    def capture_download(*args, **kwargs):
        if kwargs.get("label") == "📥 Export Audit Report (JSON)":
            audit_downloads.append(kwargs["data"])
        return original_download(*args, **kwargs)

    monkeypatch.setattr("privacygate.audit.audit_report_to_json", capture_serializer)
    monkeypatch.setattr(st, "download_button", capture_download)

    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=60)
    assert not app.exception
    assert any("Per-Page Extraction Report" in str(m.value) for m in app.markdown)
    assert any("OCR failed on page(s) 2" in str(e.value) for e in app.error)
    assert any(metric.label == "Failed Pages" and metric.value == "1" for metric in app.metric)
    assert serialized_reports == [result.audit_report]
    assert audit_downloads == [audit_report_to_json(result.audit_report)]


@pytest.mark.parametrize("texts, badges, unique, occurrences", [
    (
        ["[PERSON] [EMAIL] [PERSON_001] [EMAIL_002] [ACCOUNT_NUMBER_010] [ACCOUNT_NUMBER_1000]"],
        ["[PERSON]", "[EMAIL]", "[PERSON_001]", "[EMAIL_002]", "[ACCOUNT_NUMBER_010]", "[ACCOUNT_NUMBER_1000]"],
        4, 4,
    ),
    (
        ["[ordinary text] [NOTES] [NOTES_001] [PERSON_01] [PERSON_abc] [person_001] "
         "[[PERSON_001]] [PERSON_001_extra] [PERSON__001] <script>secret</script>"],
        [], 0, 0,
    ),
    (
        ["[PERSON_001] [EMAIL_001]"] + ["[PERSON]"] * 9 + ["[PERSON_001] [PERSON_002]"],
        ["[PERSON_001]", "[EMAIL_001]"] + ["[PERSON]"] * 9,
        3, 4,
    ),
])
def test_sanitized_preview_highlights_tokens_and_counts_document_pseudonyms(
    texts, badges, unique, occurrences,
) -> None:
    original = Document("source", "synthetic.pdf", "pdf", blocks=[
        ContentBlock(f"b{index}", "Original preview [PERSON_999]") for index in range(len(texts))
    ])
    sanitized = Document("sanitized", "synthetic.pdf", "pdf", blocks=[
        ContentBlock(f"b{index}", text) for index, text in enumerate(texts)
    ])
    validation = ValidationResult("APPROVED")
    result = PipelineResult(original, [], sanitized, validation, AuditReport("audit", validation=validation))
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result

    app.run(timeout=30)

    assert not app.exception
    cards = [str(item.value) for item in app.markdown if "<div class='preview-card'>" in str(item.value)]
    rendered = cards[1]
    assert re.findall(r'<span style="background-color: #ECFDF5;[^>]*>(.*?)</span>', rendered) == badges
    assert "<script>" not in rendered
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Unique pseudonyms"] == str(unique)
    assert metrics["Pseudonym occurrences"] == str(occurrences)
    assert any(item.value == "Stable pseudonyms remove identity while preserving relationships for downstream AI."
               for item in app.caption)


def test_results_render_embedded_images_report_and_uninspected_warning() -> None:
    doc = Document("doc1", "deck.pptx", "pptx", blocks=[
        ContentBlock("b1", "Slide text", slide_number=1, extraction_method="pptx_native")
    ], metadata={
        "slide_count": 1,
        "embedded_images": [
            {"image": "image1.png", "status": "skipped_tiny", "reason": "tiny image (48x48) not inspected"},
            {"image": "image2.png", "status": "ocr", "lines": 2},
            {"image": "image3.png", "status": "failed", "reason": "corrupted stream"},
        ],
        "embedded_images_failed": ["image1.png", "image3.png"],
        "extraction_warnings": [{"image": "image1.png", "reason": "tiny image (48x48) not OCR'd"}],
    })
    sanitized = Document("sanitized", "deck.pptx", "pptx", blocks=[
        ContentBlock("b1", "Slide text", slide_number=1, extraction_method="pptx_native")
    ], metadata=dict(doc.metadata))
    validation = ValidationResult(
        "BLOCKED",
        reason="Extraction incomplete: OCR failed for 2 embedded image(s). Their content was not inspected.",
    )
    result = PipelineResult(doc, [], sanitized, validation, AuditReport("audit", validation=validation))

    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=30)

    assert not app.exception
    assert any("Embedded Images" in str(m.value) for m in app.markdown)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Images OCR'd"] == "1"
    assert metrics["Images Skipped (Uninspected)"] == "1"
    assert metrics["Images Failed"] == "1"
    assert any("inspection incomplete: 1 failed and 1 skipped (uninspected)" in str(e.value) for e in app.error)
    assert any("image1.png: tiny image (48x48) not OCR'd" in str(c.value) for c in app.caption)


def test_results_render_skipped_tiny_image_blocks_gate_warning() -> None:
    doc = Document("doc1", "Cadence_Financial_Group_Organizational_Pack.pptx", "pptx", blocks=[
        ContentBlock("b1", "Title", slide_number=1, extraction_method="pptx_native")
    ], metadata={
        "slide_count": 1,
        "embedded_images": [
            {"image": "image1.png", "status": "skipped_tiny", "reason": "tiny image (48x48) not inspected"},
        ],
        "embedded_images_failed": ["image1.png"],
        "extraction_warnings": [{"image": "image1.png", "reason": "tiny image (48x48) not OCR'd"}],
    })
    sanitized = Document("sanitized", "Cadence_Financial_Group_Organizational_Pack.pptx", "pptx", blocks=[
        ContentBlock("b1", "Title", slide_number=1, extraction_method="pptx_native")
    ], metadata=dict(doc.metadata))
    validation = ValidationResult(
        "BLOCKED",
        reason="Extraction incomplete: OCR failed for 1 embedded image(s). Their content was not inspected.",
    )
    result = PipelineResult(doc, [], sanitized, validation, AuditReport("audit", validation=validation))

    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=30)

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Images OCR'd"] == "0"
    assert metrics["Images Skipped (Uninspected)"] == "1"
    assert metrics["Images Failed"] == "0"
    assert any("skipped without inspection (tiny or vector formats)" in str(e.value) for e in app.error)


def test_results_render_48x48_image_approved_gate() -> None:
    doc = Document("doc1", "deck.pptx", "pptx", blocks=[
        ContentBlock("b1", "Slide text", slide_number=1, extraction_method="pptx_native"),
        ContentBlock("b2", "Icon label", slide_number=1, extraction_method="embedded_image_ocr"),
    ], metadata={
        "slide_count": 1,
        "embedded_images": [
            {"image": "image1.png", "status": "ocr", "lines": 1, "attempts": 1},
        ],
        "embedded_images_failed": [],
        "extraction_warnings": [],
    })
    sanitized = Document("sanitized", "deck.pptx", "pptx", blocks=[
        ContentBlock("b1", "Slide text", slide_number=1, extraction_method="pptx_native"),
        ContentBlock("b2", "Icon label", slide_number=1, extraction_method="embedded_image_ocr"),
    ], metadata=dict(doc.metadata))
    validation = ValidationResult(
        "APPROVED",
        reason="Sanitized document passed secondary privacy scan with zero residual PII.",
    )
    result = PipelineResult(doc, [], sanitized, validation, AuditReport("audit", validation=validation))

    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=30)

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Images OCR'd"] == "1"
    assert metrics["Images Skipped (Uninspected)"] == "0"
    assert metrics["Images Failed"] == "0"
    assert any("status-badge-approved" in str(m.value) for m in app.markdown)


def test_results_render_48x48_image_ocr_failure_blocks_gate() -> None:
    doc = Document("doc1", "deck.pptx", "pptx", blocks=[
        ContentBlock("b1", "Slide text", slide_number=1, extraction_method="pptx_native"),
    ], metadata={
        "slide_count": 1,
        "embedded_images": [
            {"image": "image1.png", "status": "failed", "attempts": 2, "reason": "OCR failed for image image1.png"},
        ],
        "embedded_images_failed": ["image1.png"],
        "extraction_warnings": [],
    })
    sanitized = Document("sanitized", "deck.pptx", "pptx", blocks=[
        ContentBlock("b1", "Slide text", slide_number=1, extraction_method="pptx_native"),
    ], metadata=dict(doc.metadata))
    validation = ValidationResult(
        "BLOCKED",
        reason="Extraction incomplete: OCR failed for 1 embedded image(s). Their content was not inspected.",
    )
    result = PipelineResult(doc, [], sanitized, validation, AuditReport("audit", validation=validation))

    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=30)

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Images OCR'd"] == "0"
    assert metrics["Images Skipped (Uninspected)"] == "0"
    assert metrics["Images Failed"] == "1"
    assert any("OCR failed for 1 embedded image(s)" in str(e.value) for e in app.error)
    assert any("status-badge-blocked" in str(m.value) for m in app.markdown)


def test_results_render_cadence_pptx_approved_with_ocr_image() -> None:
    cadence_path = Path("docs/Cadence_Financial_Group_Organizational_Pack.pptx")
    if not cadence_path.exists():
        pytest.skip("Cadence PPTX not present in docs/")
    result = run_pipeline(cadence_path)
    assert result.validation.status == "APPROVED"

    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=30)

    assert not app.exception
    assert any("status-badge-approved" in str(m.value) for m in app.markdown)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Images OCR'd"] == "1"
    assert metrics["Images Skipped (Uninspected)"] == "0"
    assert metrics["Images Failed"] == "0"
    assert len(app.error) == 0
