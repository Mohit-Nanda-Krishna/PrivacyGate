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
