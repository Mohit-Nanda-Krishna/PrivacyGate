"""Native PDF extraction with page-level local OCR fallback."""

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import os
from pathlib import Path
import time
from uuid import uuid4

import pymupdf

from privacygate.extraction.embedded import EmbeddedImage, ocr_embedded_images
from privacygate.extraction.errors import ExtractionError, OCRRequiredError
from privacygate.extraction.figures import Figure, extract_figures
from privacygate.extraction.ocr import MIN_TEXT_CHARACTERS, OCR_DPI, recognize_image, render_page
from privacygate.models import ContentBlock, Document

# Deterministic per-page heuristic, not proof of scanned-page classification
# or complete extraction. Native pages below this threshold require OCR.
MIN_NATIVE_TEXT_CHARACTERS = MIN_TEXT_CHARACTERS
# Pages OCR'd concurrently. Each Tesseract process is single-threaded
# (OMP_THREAD_LIMIT=1), and at most this many rendered pages are held in memory.
OCR_WORKERS = max(1, min(4, os.cpu_count() or 1))


def _figure_blocks(figures: list[Figure], page_number: int) -> tuple[list[ContentBlock], list[dict]]:
    """Figure OCR lines as blocks, plus per-figure metadata (region, readability, photos)."""
    blocks, regions = [], []
    for figure in figures:
        regions.append({
            "page": page_number, "figure": figure.index, "bbox_pixels": list(figure.bbox),
            "render_dpi": OCR_DPI, "confidence": round(figure.confidence, 1), "readable": figure.readable,
            "photos": [list(photo) for photo in figure.photos], "variant": figure.variant,
        })
        for order, line in enumerate(figure.lines, start=1):
            blocks.append(ContentBlock(
                block_id=f"page_{page_number}_figure_{figure.index}_line_{order}",
                text=line.text, page_number=page_number, extraction_method="figure_ocr",
                metadata={
                    "kind": "figure", "figure": figure.index, "block_order": order,
                    "region_bbox_pixels": list(figure.bbox), "bbox_pixels": line.bbox,
                    "word_boxes_pixels": line.word_boxes, "render_dpi": OCR_DPI,
                    "ocr_confidence": round(line.confidence, 1),
                },
            ))
    return blocks, regions


def _timed_recognition(image, page_number: int):
    started = time.perf_counter()
    try:
        # Figures first: recognize_image closes the rendered page image.
        try:
            figures = extract_figures(image, page_number)
        except OCRRequiredError:
            raise
        except ExtractionError:
            figures = []
            figure_failed = True
        else:
            figure_failed = False
        blocks, attempts = recognize_image(image, page_number)
        figure_blocks, regions = _figure_blocks(figures, page_number)
        if figure_failed:
            regions.append({"page": page_number, "figure": 0, "bbox_pixels": None, "render_dpi": OCR_DPI,
                            "confidence": 0.0, "readable": False, "photos": [], "variant": "failed"})
        return blocks + figure_blocks, regions, attempts, time.perf_counter() - started, None
    except OCRRequiredError:
        raise
    except ExtractionError as error:
        return [], [], 2 if "after a retry" in str(error) else 1, time.perf_counter() - started, error


def extract_pdf(path: str | Path) -> Document:
    """Extract native text with 1-based pages/order and original block numbers.

    Pages with fewer than 20 native alphanumeric characters use local OCR, run
    concurrently with results kept in page order. A page whose OCR fails is
    recorded as failed in metadata["page_report"] / ["ocr_failed_pages"] and the
    other pages are kept; the privacy gate must block such a document. If no
    page yields text, the first page failure is raised. Missing Tesseract always
    raises OCRRequiredError.

    Pages with sufficient native text extract native text blocks and also
    enumerate and locally OCR embedded raster images (extraction_method
    "embedded_image_ocr"). Full-page scanned pages do not extract embedded
    images redundantly. Embedded image extraction/OCR failures are recorded
    in metadata["embedded_images_failed"] so the privacy gate fails closed.
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
            figure_regions: list[dict] = []
            embedded_images: list[EmbeddedImage] = []
            embedded_failures: list[str] = []
            embedded_reports: list[dict] = []
            extracted_by_xref: dict[int, dict] = {}
            failed_xrefs: set[int] = set()

            def collect(done) -> None:
                for future in done:
                    number = pending.pop(future)
                    res = future.result()
                    if len(res) == 5:
                        blocks, regions, attempts, seconds, error = res
                    else:
                        blocks, attempts, seconds, error = res
                        regions = []
                    page_blocks[number] = blocks
                    figure_regions.extend(regions)
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
                            try:
                                raw_images = page.get_images(full=True)
                            except Exception:
                                fail_id = f"page_{page_number}_img_enum"
                                if fail_id not in embedded_failures:
                                    embedded_failures.append(fail_id)
                                    embedded_reports.append(
                                        {"image": fail_id, "status": "failed", "reason": "could not enumerate images"}
                                    )
                                raw_images = []

                            seen_xrefs_on_page: set[int] = set()
                            for img_index, img_info in enumerate(raw_images, start=1):
                                try:
                                    xref = img_info[0]
                                    if xref in seen_xrefs_on_page:
                                        continue
                                    seen_xrefs_on_page.add(xref)
                                    img_id = f"page_{page_number}_img_{img_index}_xref_{xref}"
                                    if xref <= 0:
                                        if img_id not in embedded_failures:
                                            embedded_failures.append(img_id)
                                            embedded_reports.append(
                                                {"image": img_id, "status": "failed", "reason": "invalid image xref"}
                                            )
                                        continue
                                    if xref in failed_xrefs:
                                        continue
                                    if xref in extracted_by_xref:
                                        extracted = extracted_by_xref[xref]
                                    else:
                                        extracted = source.extract_image(xref)
                                        extracted_by_xref[xref] = extracted
                                    if not extracted or not extracted.get("image"):
                                        failed_xrefs.add(xref)
                                        if img_id not in embedded_failures:
                                            embedded_failures.append(img_id)
                                            embedded_reports.append(
                                                {"image": img_id, "status": "failed", "reason": "empty extracted image"}
                                            )
                                        continue
                                    ext = extracted.get("ext") or "png"
                                    embedded_images.append(EmbeddedImage(
                                        name=f"{img_id}.{ext}",
                                        data=extracted["image"],
                                        block_prefix=img_id,
                                        location={
                                            "page_number": page_number,
                                            "xref": xref,
                                            "image_index": img_index,
                                        },
                                    ))
                                except Exception:
                                    fail_id = f"page_{page_number}_img_{img_index}"
                                    if fail_id not in embedded_failures:
                                        embedded_failures.append(fail_id)
                                        embedded_reports.append(
                                            {"image": fail_id, "status": "failed", "reason": "could not extract image"}
                                        )
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

            if embedded_images:
                embedded_result = ocr_embedded_images(embedded_images)
                for block in embedded_result.blocks:
                    p_num = block.page_number
                    if p_num is not None:
                        page_blocks.setdefault(p_num, []).append(block)
                embedded_failures.extend(embedded_result.failed)
                embedded_reports.extend(embedded_result.report)
                extraction_warnings = embedded_result.warnings
            else:
                extraction_warnings = []

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
                "embedded_images": embedded_reports,
                "embedded_images_failed": embedded_failures,
                "extraction_warnings": extraction_warnings,
                "figure_regions": sorted(figure_regions, key=lambda r: (r["page"], r["figure"])),
            }
            return document
    except ExtractionError:
        raise
    except (FileNotFoundError, pymupdf.FileNotFoundError):
        raise ExtractionError("PDF file not found.") from None
    except Exception:
        # Parser messages can include input paths or document text.
        raise ExtractionError("Could not extract PDF. Check that the file is readable and valid.") from None
