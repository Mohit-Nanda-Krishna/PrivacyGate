"""Tests for Streamlit user interface."""

from pathlib import Path
import runpy

import pytesseract
from streamlit.testing.v1 import AppTest

from privacygate.extraction import ocr
from privacygate.pipeline import run_pipeline

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

    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=60)
    assert not app.exception
    assert any("Per-Page Extraction Report" in str(m.value) for m in app.markdown)
    assert any("OCR failed on page(s) 2" in str(e.value) for e in app.error)
    assert any(metric.label == "Failed Pages" and metric.value == "1" for metric in app.metric)
