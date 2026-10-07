"""Local Tesseract OCR for individual PDF pages; no external services."""

import shutil

import pymupdf
import pytesseract
from PIL import Image

from privacygate.extraction.errors import ExtractionError, OCRRequiredError
from privacygate.models import ContentBlock

OCR_DPI = 300
OCR_TIMEOUT_SECONDS = 30
MIN_TEXT_CHARACTERS = 20


def extract_page_ocr(page: pymupdf.Page) -> list[ContentBlock]:
    """Render RGB at 300 DPI and emit lines in Tesseract's returned reading order.

    English, automatic page segmentation (PSM 3), and a 30-second engine timeout
    are used. Bounding boxes are pixels in the rendered (possibly rotated) page,
    not PDF coordinates. Fewer than 20 alphanumeric characters is unusable.
    pytesseract's temporary input/output files are cleaned up by its context
    manager on success and failure; PrivacyGate keeps no image artifacts.
    """
    page_number = page.number + 1
    missing_message = (
        f"Page {page_number} requires OCR, but Tesseract is unavailable. "
        "Install the Tesseract executable with English language data and add it to PATH."
    )
    if shutil.which("tesseract") is None:
        raise OCRRequiredError(missing_message)
    try:
        pixmap = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    except Exception:
        raise ExtractionError(f"Could not render page {page_number} for OCR.") from None

    try:
        data = pytesseract.image_to_data(
            image, lang="eng", config=f"--psm 3 --dpi {OCR_DPI}",
            output_type=pytesseract.Output.DICT, timeout=OCR_TIMEOUT_SECONDS,
        )
    except pytesseract.TesseractNotFoundError:
        raise OCRRequiredError(missing_message) from None
    except Exception:
        # Never expose Tesseract stderr, paths, or recognized text in errors.
        raise ExtractionError(
            f"OCR failed for page {page_number}. Check Tesseract and English language data; "
            "the engine may have failed or timed out."
        ) from None
    finally:
        image.close()

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

        blocks = [
            ContentBlock(
                block_id=f"page_{page_number}_ocr_block_{order}",
                text=" ".join(line["words"]), page_number=page_number,
                extraction_method="ocr",
                metadata={
                    "block_order": order, "source_block_number": key[0],
                    "source_paragraph_number": key[1], "source_line_number": key[2],
                    "bbox_pixels": line["bbox"], "render_dpi": OCR_DPI,
                },
            )
            for order, (key, line) in enumerate(lines.items(), start=1)
        ]
    except Exception:
        raise ExtractionError(f"OCR returned malformed output for page {page_number}.") from None
    if sum(character.isalnum() for block in blocks for character in block.text) < MIN_TEXT_CHARACTERS:
        raise ExtractionError(
            f"OCR produced unusable text for page {page_number} "
            "(fewer than 20 alphanumeric characters). Extraction is incomplete."
        )
    return blocks
