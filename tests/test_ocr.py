"""Page-level OCR routing, local Tesseract integration, and fail-closed errors."""

from pathlib import Path
import runpy
import shutil
import tempfile
from unittest.mock import Mock

import pymupdf
import pytest
import pytesseract
from PIL import Image

from privacygate.extraction import ExtractionError, OCRRequiredError, extract_document
from privacygate.extraction import ocr, pdf

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ocr_fixtures(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ocr-fixtures")
    generator = runpy.run_path(str(FIXTURES / "generate_fixtures.py"))["generate_ocr_fixtures"]
    generator(directory)
    return directory


def synthetic_data():
    # Deliberately distinct lines in a single Tesseract block/paragraph.
    return {
        "text": ["", "Synthetic", "scanned", "report.", "Sample", "widgets", "are", "ready."],
        "block_num": [0, 1, 1, 1, 1, 1, 1, 1],
        "par_num": [0, 1, 1, 1, 1, 1, 1, 1],
        "line_num": [0, 1, 1, 1, 2, 2, 2, 2],
        "left": [0, 100, 220, 320, 100, 210, 320, 390],
        "top": [0, 100, 100, 100, 200, 200, 200, 200],
        "width": [0, 100, 80, 70, 90, 90, 50, 90],
        "height": [0, 30, 30, 30, 30, 30, 30, 30],
    }


@pytest.fixture
def fake_engine(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda command: "tesseract")
    engine = Mock(return_value=synthetic_data())
    monkeypatch.setattr(ocr.pytesseract, "image_to_data", engine)
    return engine


def test_scanned_fixture_has_no_native_text_and_is_deterministic(ocr_fixtures, tmp_path):
    generator = runpy.run_path(str(FIXTURES / "generate_fixtures.py"))["generate_ocr_fixtures"]
    generator(tmp_path)
    for name in ["scanned.pdf", "mixed.pdf"]:
        assert (ocr_fixtures / name).read_bytes() == (tmp_path / name).read_bytes()
    with pymupdf.open(ocr_fixtures / "scanned.pdf") as source:
        assert source[0].get_text().strip() == ""
        assert source[0].get_images()


def test_scanned_page_becomes_ordered_canonical_ocr_blocks(ocr_fixtures, fake_engine):
    document = extract_document(ocr_fixtures / "scanned.pdf")
    assert [block.text for block in document.blocks] == [
        "Synthetic scanned report.", "Sample widgets are ready.",
    ]
    assert [block.block_id for block in document.blocks] == ["page_1_ocr_block_1", "page_1_ocr_block_2"]
    assert all(block.page_number == 1 and block.extraction_method == "ocr" for block in document.blocks)
    assert document.blocks[0].metadata["bbox_pixels"] == [100, 100, 390, 130]
    assert document.blocks[1].metadata["source_line_number"] == 2
    assert document.blocks[0].metadata["render_dpi"] == 300
    assert document.metadata["ocr_pages"] == [1]
    assert document.metadata["pages_without_native_text"] == [1]
    assert document.metadata["native_text_character_count"] == 0
    assert fake_engine.call_args.kwargs == {
        "lang": "eng", "config": "--psm 3 --dpi 300",
        "output_type": pytesseract.Output.DICT, "timeout": 30,
    }
    assert fake_engine.call_args.args[0].size == (1800, 900)


def test_mixed_pages_preserve_native_text_and_original_order(ocr_fixtures, fake_engine):
    document = extract_document(ocr_fixtures / "mixed.pdf")
    assert [block.page_number for block in document.blocks] == [1, 2, 2, 3]
    assert [block.extraction_method for block in document.blocks] == ["pdf_native", "ocr", "ocr", "pdf_native"]
    assert document.blocks[0].text == "Synthetic native first page."
    assert document.blocks[-1].text == "Synthetic native final page."
    assert document.metadata["ocr_pages"] == [2]
    assert document.metadata["pages_without_native_text"] == [2]
    assert len({block.block_id for block in document.blocks}) == 4
    fake_engine.assert_called_once()


def test_native_pdf_never_renders_or_invokes_ocr(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Native pages must not require OCR or rendering")

    monkeypatch.setattr(pdf, "render_page", forbidden)
    monkeypatch.setattr(pymupdf.Page, "get_pixmap", forbidden)
    document = extract_document(FIXTURES / "native.pdf")
    assert len(document.blocks) == 4
    assert document.metadata["ocr_pages"] == []


@pytest.mark.parametrize("text,requires_ocr", [("a" * 19, True), ("a" * 20, False), ("?" * 40, True)])
def test_threshold_is_per_page_and_ocr_replaces_sparse_native_text(tmp_path, fake_engine, text, requires_ocr):
    path = tmp_path / "threshold.pdf"
    with pymupdf.open() as source:
        source.new_page().insert_text((72, 72), "Meaningful native first page content.")
        source.new_page().insert_text((72, 72), text)
        source.save(path)
    document = extract_document(path)
    assert document.metadata["ocr_pages"] == ([2] if requires_ocr else [])
    assert fake_engine.call_count == int(requires_ocr)
    if requires_ocr:
        assert all(block.text != text for block in document.blocks)
        assert [block.extraction_method for block in document.blocks[1:]] == ["ocr", "ocr"]


def test_missing_tesseract_rejects_entire_mixed_document(ocr_fixtures, monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda command: None)
    with pytest.raises(OCRRequiredError, match="Page 2 requires OCR, but Tesseract is unavailable"):
        extract_document(ocr_fixtures / "mixed.pdf")


def test_render_failure_rejects_extraction(ocr_fixtures, fake_engine, monkeypatch):
    monkeypatch.setattr(pymupdf.Page, "get_pixmap", Mock(side_effect=RuntimeError("private detail")))
    with pytest.raises(ExtractionError, match="Could not render page 1") as error:
        extract_document(ocr_fixtures / "scanned.pdf")
    assert "private detail" not in str(error.value)
    fake_engine.assert_not_called()


@pytest.mark.parametrize("failure", [
    pytesseract.TesseractError(1, "private engine stderr"),
    RuntimeError("Tesseract process timeout"),
    OSError("private path"),
])
def test_engine_failure_marks_page_failed_keeps_other_pages_and_closes_image(ocr_fixtures, fake_engine, failure):
    fake_engine.side_effect = failure
    document = extract_document(ocr_fixtures / "mixed.pdf")
    assert [block.page_number for block in document.blocks] == [1, 3]
    assert document.metadata["ocr_failed_pages"] == [2]
    report = {entry["page"]: entry for entry in document.metadata["page_report"]}
    assert [report[n]["status"] for n in (1, 2, 3)] == ["native", "failed", "native"]
    assert report[2]["reason"].startswith("OCR failed for page 2")
    assert "private" not in report[2]["reason"]
    with pytest.raises(ValueError, match="closed"):
        fake_engine.call_args.args[0].getpixel((0, 0))


def test_engine_failure_on_only_page_still_rejects_document(ocr_fixtures, fake_engine):
    fake_engine.side_effect = pytesseract.TesseractError(1, "private engine stderr")
    with pytest.raises(ExtractionError, match="OCR failed for page 1") as error:
        extract_document(ocr_fixtures / "scanned.pdf")
    assert "private" not in str(error.value)


def test_timeout_is_retried_once_with_longer_timeout(ocr_fixtures, fake_engine):
    fake_engine.side_effect = [RuntimeError("Tesseract process timeout"), synthetic_data()]
    document = extract_document(ocr_fixtures / "scanned.pdf")
    assert [call.kwargs["timeout"] for call in fake_engine.call_args_list] == [30, 120]
    assert document.metadata["page_report"][0] | {"seconds": 0} == {
        "page": 1, "status": "ocr", "attempts": 2, "seconds": 0,
    }
    assert document.metadata["ocr_failed_pages"] == []


def test_timeout_twice_fails_page_after_two_attempts(ocr_fixtures, fake_engine):
    fake_engine.side_effect = RuntimeError("Tesseract process timeout")
    document = extract_document(ocr_fixtures / "mixed.pdf")
    report = {entry["page"]: entry for entry in document.metadata["page_report"]}
    assert report[2]["status"] == "failed" and report[2]["attempts"] == 2
    assert "timed out after a retry" in report[2]["reason"]
    assert fake_engine.call_count == 2


def test_non_timeout_errors_are_not_retried(ocr_fixtures, fake_engine):
    fake_engine.side_effect = OSError("private path")
    extract_document(ocr_fixtures / "mixed.pdf")
    assert fake_engine.call_count == 1


def test_parallel_ocr_keeps_deterministic_page_order(tmp_path, monkeypatch):
    import random
    import time

    monkeypatch.setattr(ocr.shutil, "which", lambda command: "tesseract")
    path = tmp_path / "many.pdf"
    with pymupdf.open() as source:
        for _ in range(9):
            source.new_page(width=200, height=200)
        source.save(path)
    rng = random.Random(7)

    def slow_engine(image, **kwargs):
        time.sleep(rng.random() * 0.03)  # finish out of order
        return synthetic_data()

    monkeypatch.setattr(ocr.pytesseract, "image_to_data", slow_engine)
    document = extract_document(path)
    assert [block.page_number for block in document.blocks] == [n for n in range(1, 10) for _ in (0, 1)]
    assert [entry["page"] for entry in document.metadata["page_report"]] == list(range(1, 10))
    assert document.metadata["ocr_pages"] == list(range(1, 10))


def test_tesseract_runs_single_threaded():
    import os

    assert os.environ.get("OMP_THREAD_LIMIT")


def test_failed_page_blocks_gate_even_with_multiple_passes(ocr_fixtures, fake_engine):
    from privacygate.audit import audit_report_to_dict
    from privacygate.pipeline import run_pipeline

    fake_engine.side_effect = pytesseract.TesseractError(1, "private engine stderr")
    result = run_pipeline(ocr_fixtures / "mixed.pdf", max_passes=3)
    assert result.validation.status == "BLOCKED"
    assert "OCR failed for page(s) 2" in result.validation.reason
    exported = audit_report_to_dict(result.audit_report)
    assert exported["extraction"]["failed_pages"] == [2]
    assert [entry["status"] for entry in exported["extraction"]["pages"]] == ["native", "failed", "native"]
    assert "private" not in str(exported)


def test_disappearing_executable_has_project_error(ocr_fixtures, fake_engine):
    fake_engine.side_effect = pytesseract.TesseractNotFoundError()
    with pytest.raises(OCRRequiredError, match="Tesseract is unavailable"):
        extract_document(ocr_fixtures / "scanned.pdf")


@pytest.mark.parametrize("text", ["", "   ", "!!! ----", "short", "a" * 19])
def test_unusable_ocr_output_is_rejected(ocr_fixtures, fake_engine, text):
    data = synthetic_data()
    data["text"] = [text]
    fake_engine.return_value = data
    with pytest.raises(ExtractionError, match="OCR produced unusable text for page 1"):
        extract_document(ocr_fixtures / "scanned.pdf")


def test_malformed_ocr_output_is_rejected(ocr_fixtures, fake_engine):
    fake_engine.return_value = {"text": ["Synthetic report text"]}
    with pytest.raises(ExtractionError, match="malformed output"):
        extract_document(ocr_fixtures / "scanned.pdf")


@pytest.fixture
def real_tesseract():
    if shutil.which("tesseract") is None:
        pytest.skip("Local Tesseract executable unavailable; mocked OCR tests still run")
    # Missing eng data or a broken executable must fail, not become a silent skip.
    return None


@pytest.mark.parametrize("name,ocr_page", [("scanned.pdf", 1), ("mixed.pdf", 2)])
def test_real_tesseract_reads_synthetic_scans(ocr_fixtures, real_tesseract, name, ocr_page, monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    document = extract_document(ocr_fixtures / name)
    blocks = [block for block in document.blocks if block.extraction_method == "ocr"]
    text = " ".join(block.text for block in blocks)
    assert "Synthetic scanned report." in text
    assert "Sample widgets are ready." in text
    assert all(block.page_number == ocr_page for block in blocks)
    assert document.metadata["ocr_pages"] == [ocr_page]
    assert list(tmp_path.iterdir()) == []  # pytesseract removed temporary images/TSV


def test_real_blank_page_fails_closed(real_tesseract, tmp_path, monkeypatch):
    path = tmp_path / "blank.pdf"
    with pymupdf.open() as source:
        source.new_page(width=216, height=216)
        source.save(path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with pytest.raises(ExtractionError, match="unusable text"):
        extract_document(path)
    assert list(tmp_path.iterdir()) == [path]


def test_pytesseract_cleans_temp_files_on_engine_error(tmp_path, monkeypatch):
    # Exercise the real wrapper's cleanup even on machines without Tesseract.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(pytesseract.pytesseract, "get_tesseract_version", lambda **kwargs: 5)
    monkeypatch.setattr(pytesseract.pytesseract, "TESSERACT_MIN_VERSION", 3)
    monkeypatch.setattr(pytesseract.pytesseract, "run_tesseract", Mock(side_effect=RuntimeError("engine failed")))
    with Image.new("RGB", (20, 20), "white") as image:
        with pytest.raises(RuntimeError, match="engine failed"):
            pytesseract.image_to_data(image)
    assert list(tmp_path.iterdir()) == []
