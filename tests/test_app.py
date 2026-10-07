"""Tests for Streamlit user interface."""

from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_streamlit_app_loads_successfully() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    assert not app.exception
    assert any("PrivacyGate" in str(m.value) for m in app.markdown)
    assert len(app.file_uploader) == 1
    assert len(app.selectbox) == 1
