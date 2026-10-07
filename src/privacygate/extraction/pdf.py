"""Native PDF extraction with page-level local OCR fallback."""

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import os
from pathlib import Path
import time
from uuid import uuid4

import pymupdf

from privacygate.extraction.errors import ExtractionError, OCRRequiredError
from privacygate.extraction.ocr import MIN_TEXT_CHARACTERS, recognize_image, render_page
from privacygate.models import ContentBlock, Document

# Deterministic per-page heuristic, not proof of scanned-page classification
# or complete extraction. Native pages below this threshold require OCR.
MIN_NATIVE_TEXT_CHARACTERS = MIN_TEXT_CHARACTERS
# Pages OCR'd concurrently. Each Tesseract process is single-threaded
# (OMP_THREAD_LIMIT=1), and at most this many rendered pages are held in memory.
OCR_WORKERS = max(1, min(4, os.cpu_count() or 1))


def _timed_recognition(image, page_number: int):
    started = time.perf_counter()
    try:
        blocks, attempts = recognize_image(image, page_number)
        return blocks, attempts, time.perf_counter() - started, None
    except OCRRequiredError:
        raise
    except ExtractionError as error:
        return [], 2 if "after a retry" in str(error) else 1, time.perf_counter() - started, error


def extract_pdf(path: str | Path) -> Document:
    """Extract native text with 1-based pages/order and original block numbers.

    Pages with fewer than 20 native alphanumeric characters use local OCR, run
    concurrently with results kept in page order. A page whose OCR fails is
    recorded as failed in metadata["page_report"] / ["ocr_failed_pages"] and the
    other pages are kept; the privacy gate must block such a document. If no
    page yields text, the first page failure is raised. Missing Tesseract always
    raises OCRRequiredError. Native and OCR text are never combined for a page.
    """
    path = Path(path)
    try:
        with pymupdf.open(path) as source:
            if not source.is_pdf:
                raise ExtractionError("Input is not a PDF document.")
            if source.needs_pass:
                raise ExtractionError("Password-protected PDFs are not supported.")

            document = Document(str(uuid4()), path.name, "pdf")
            pages_without_text = []
            character_count = 0
            page_blocks: dict[int, list[ContentBlock]] = {}
            report: dict[int, dict] = {}
            failures: dict[int, ExtractionError] = {}
            pending: dict[Future, int] = {}

            def collect(done) -> None:
                for future in done:
                    number = pending.pop(future)
                    blocks, attempts, seconds, error = future.result()
                    page_blocks[number] = blocks
                    report[number].update(
                        status="failed" if error else "ocr", attempts=attempts, seconds=round(seconds, 2),
                    )
                    if error:
                        failures[number] = error
                        report[number]["reason"] = str(error)

            with ThreadPoolExecutor(max_workers=OCR_WORKERS) as executor:
                try:
                    for page_number, page in enumerate(source, start=1):
                        started = time.perf_counter()
                        native = []
                        for block in page.get_text("blocks", sort=True):
                            x0, y0, x1, y1, text, source_number, block_type = block
                            if block_type != 0 or not text.strip():
                                continue
                            order = len(native) + 1
                            native.append(ContentBlock(
                                block_id=f"page_{page_number}_block_{order}",
                                text=text.strip(), page_number=page_number,
                                extraction_method="pdf_native",
                                metadata={
                                    "block_order": order,
                                    "source_block_number": source_number,
                                    "bbox": [x0, y0, x1, y1],
                                },
                            ))
                        if not native:
                            pages_without_text.append(page_number)
                        page_character_count = sum(
                            character.isalnum() for block in native for character in block.text
                        )
                        character_count += page_character_count
                        if page_character_count >= MIN_NATIVE_TEXT_CHARACTERS:
                            page_blocks[page_number] = native
                            report[page_number] = {
                                "page": page_number, "status": "native", "attempts": 0,
                                "seconds": round(time.perf_counter() - started, 2),
                            }
                            continue
                        report[page_number] = {"page": page_number, "status": "pending"}
                        if len(pending) >= OCR_WORKERS:
                            done, _ = wait(pending, return_when=FIRST_COMPLETED)
                            collect(done)
                        try:
                            image = render_page(page)
                        except OCRRequiredError:
                            raise
                        except ExtractionError as error:
                            page_blocks[page_number] = []
                            failures[page_number] = error
                            report[page_number].update(
                                status="failed", attempts=0, seconds=0.0, reason=str(error),
                            )
                            continue
                        pending[executor.submit(_timed_recognition, image, page_number)] = page_number
                    collect(wait(pending).done)
                finally:
                    for future in pending:
                        future.cancel()

            for page_number in sorted(page_blocks):
                document.blocks.extend(page_blocks[page_number])
            if not document.blocks:
                if failures:
                    raise failures[min(failures)]
                raise ExtractionError("PDF contains no extractable pages or text.")
            page_report = [report[number] for number in sorted(report)]
            document.metadata = {
                "page_count": source.page_count,
                "native_text_character_count": character_count,
                "pages_without_native_text": pages_without_text,
                "ocr_pages": [entry["page"] for entry in page_report if entry["status"] != "native"],
                "ocr_failed_pages": sorted(failures),
                "page_report": page_report,
            }
            return document
    except ExtractionError:
        raise
    except (FileNotFoundError, pymupdf.FileNotFoundError):
        raise ExtractionError("PDF file not found.") from None
    except Exception:
        # Parser messages can include input paths or document text.
        raise ExtractionError("Could not extract PDF. Check that the file is readable and valid.") from None
