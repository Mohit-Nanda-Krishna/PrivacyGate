"""Local Tesseract OCR for individual PDF pages; no external services."""

import os
import shutil

import pymupdf
import pytesseract
from PIL import Image

from privacygate.extraction.errors import ExtractionError, OCRRequiredError
from privacygate.models import ContentBlock

# Tesseract's OpenMP threading oversubscribes CPUs when pages run in parallel
# and can stall a single page past its timeout. One thread per engine process.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

OCR_DPI = 300
OCR_TIMEOUT_SECONDS = 30
OCR_RETRY_TIMEOUT_SECONDS = 120
MIN_TEXT_CHARACTERS = 20


def _missing_message(page_number: int) -> str:
    return (
        f"Page {page_number} requires OCR, but Tesseract is unavailable. "
        "Install the Tesseract executable with English language data and add it to PATH."
    )


def render_page(page: pymupdf.Page) -> Image.Image:
    """Render one page to an RGB image at OCR_DPI. Not thread-safe (PyMuPDF)."""
    page_number = page.number + 1
    if shutil.which("tesseract") is None:
        raise OCRRequiredError(_missing_message(page_number))
    try:
        pixmap = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csRGB, alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    except Exception:
        raise ExtractionError(f"Could not render page {page_number} for OCR.") from None


def _run_engine(image: Image.Image, timeout: int) -> dict:
    return pytesseract.image_to_data(
        image, lang="eng", config=f"--psm 3 --dpi {OCR_DPI}",
        output_type=pytesseract.Output.DICT, timeout=timeout,
    )


def _is_timeout(error: Exception) -> bool:
    # pytesseract signals its subprocess timeout as RuntimeError("Tesseract process timeout").
    return isinstance(error, RuntimeError) and "timeout" in str(error).lower()


def run_ocr(image: Image.Image, label: str, dpi: int | None = OCR_DPI) -> tuple[dict, int]:
    """Run Tesseract with one longer retry on timeout; returns (data, attempts).

    label names the source in errors ("page 3", "image image7.png"). Errors
    never include Tesseract stderr, paths or recognized text. Does not close
    the image. Safe to call from worker threads.
    """
    attempts = 0
    for timeout in (OCR_TIMEOUT_SECONDS, OCR_RETRY_TIMEOUT_SECONDS):
        attempts += 1
        try:
            if dpi is None:
                data = pytesseract.image_to_data(
                    image, lang="eng", config="--psm 3",
                    output_type=pytesseract.Output.DICT, timeout=timeout,
                )
            else:
                data = _run_engine(image, timeout)
            return data, attempts
        except pytesseract.TesseractNotFoundError:
            raise OCRRequiredError(
                f"{label[0].upper()}{label[1:]} requires OCR, but Tesseract is unavailable. "
                "Install the Tesseract executable with English language data and add it to PATH."
            ) from None
        except Exception as error:
            if _is_timeout(error) and timeout != OCR_RETRY_TIMEOUT_SECONDS:
                continue
            reason = "timed out after a retry" if _is_timeout(error) else "the engine failed"
            raise ExtractionError(
                f"OCR failed for {label} ({reason}). Check Tesseract and English language data."
            ) from None
    raise AssertionError("unreachable")


def group_lines(data: dict, label: str) -> list[tuple[tuple[int, int, int], str, list[int]]]:
    """Group Tesseract words into (block/paragraph/line key, text, pixel bbox) lines."""
    try:
        lines = {}
        for index, text in enumerate(data["text"]):
            if not text.strip():
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            left, top = data["left"][index], data["top"][index]
            right, bottom = left + data["width"][index], top + data["height"][index]
            if key not in lines:
                lines[key] = {"words": [], "bbox": [left, top, right, bottom]}
            line = lines[key]
            line["words"].append(text.strip())
            box = line["bbox"]
            line["bbox"] = [min(box[0], left), min(box[1], top), max(box[2], right), max(box[3], bottom)]
        return [(key, " ".join(line["words"]), line["bbox"]) for key, line in lines.items()]
    except Exception:
        raise ExtractionError(f"OCR returned malformed output for {label}.") from None


def recognize_image(image: Image.Image, page_number: int) -> tuple[list[ContentBlock], int]:
    """OCR a rendered page; returns (blocks, attempts). Always closes the image.

    A timeout is retried once with OCR_RETRY_TIMEOUT_SECONDS; other engine
    failures are not retried. Safe to call from worker threads.
    """
    try:
        data, attempts = run_ocr(image, f"page {page_number}")
    finally:
        image.close()
    return _blocks_from_data(data, page_number), attempts


def _blocks_from_data(data: dict, page_number: int) -> list[ContentBlock]:
    blocks = [
        ContentBlock(
            block_id=f"page_{page_number}_ocr_block_{order}",
            text=text, page_number=page_number,
            extraction_method="ocr",
            metadata={
                "block_order": order, "source_block_number": key[0],
                "source_paragraph_number": key[1], "source_line_number": key[2],
                "bbox_pixels": bbox, "render_dpi": OCR_DPI,
            },
        )
        for order, (key, text, bbox) in enumerate(group_lines(data, f"page {page_number}"), start=1)
    ]
    if sum(character.isalnum() for block in blocks for character in block.text) < MIN_TEXT_CHARACTERS:
        raise ExtractionError(
            f"OCR produced unusable text for page {page_number} "
            "(fewer than 20 alphanumeric characters). Extraction is incomplete."
        )
    return blocks


def extract_page_ocr(page: pymupdf.Page) -> list[ContentBlock]:
    """Render RGB at 300 DPI and emit lines in Tesseract's returned reading order.

    English, automatic page segmentation (PSM 3), and a 30-second engine timeout
    (one retry at 120 seconds on timeout) are used. Bounding boxes are pixels in
    the rendered (possibly rotated) page, not PDF coordinates. Fewer than 20
    alphanumeric characters is unusable. pytesseract's temporary input/output
    files are cleaned up by its context manager on success and failure;
    PrivacyGate keeps no image artifacts.
    """
    blocks, _ = recognize_image(render_page(page), page.number + 1)
    return blocks
