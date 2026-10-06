from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_foundation_starts_without_processing():
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=20)
    assert not app.exception
    assert app.title[0].value == "PrivacyGate"
    assert "foundation initialized" in app.info[0].value
    assert "not available yet" in app.info[0].value
    assert not app.get("file_uploader")
