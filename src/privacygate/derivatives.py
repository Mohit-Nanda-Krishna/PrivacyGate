"""Masked derivatives of source files built from pipeline results.

redact_pdf() returns a copy of a PDF in which every span replaced in the
final sanitized text (all passes) is blacked out and the underlying content
removed, keeping the page count and layout:

* native text: the detected value is located with page.search_for() inside
  its source block's rectangle and removed with a true redaction (the text is
  deleted from the content stream, not just covered);
* scanned (OCR) pages and their figures: the Tesseract word boxes overlapping
  the detection are converted from rendered pixels to PDF coordinates and
  redacted with PDF_REDACT_IMAGE_PIXELS, so the image pixels underneath are
  destroyed;
* figures on scanned pages (document.metadata["figure_regions"]): in strict
  mode (mask_all_figures, the default) every figure region is masked whole,
  because OCR may not have extracted every value in it. Otherwise photo and
  barcode regions are masked, and a figure whose OCR was not confident enough
  to trust is masked whole, so no figure is left readable that was not
  scanned for PII;
* document metadata (title, author, ...) and XMP metadata are cleared.

Detections that cannot be located on the page, and pages whose figure scan
failed, are counted in the report; the caller must not treat such a
derivative as fully masked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
import re

import pymupdf

from privacygate.models import ContentBlock, Document, PIIEntity


@dataclass
class RedactedPdf:
    data: bytes
    page_count: int
    boxes: int = 0
    unlocated: int = 0  # detections that could not be placed on the page
    by_method: dict[str, int] = field(default_factory=dict)
    unreadable_figures: int = 0  # figure regions masked whole because their OCR was not trusted
    photos: int = 0  # photo and barcode regions masked
    figure_scan_failures: int = 0  # pages whose figure scan failed (figures there may be unmasked)
    strict_figures: int = 0  # figure regions masked whole because of strict mode (mask_all_figures)


def _pixel_rect(page: pymupdf.Page, box: list[int], dpi: int) -> pymupdf.Rect:
    """Rendered-page pixels -> unrotated page coordinates."""
    scale = 72.0 / dpi
    return pymupdf.Rect(box[0] * scale, box[1] * scale, box[2] * scale, box[3] * scale) * page.derotation_matrix


def _word_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of the space-joined words of an OCR line."""
    spans, position = [], 0
    for word in text.split(" "):
        spans.append((position, position + len(word)))
        position += len(word) + 1
    return spans


def _ocr_rects(page: pymupdf.Page, block: ContentBlock, entity: PIIEntity) -> list[pymupdf.Rect]:
    boxes = block.metadata.get("word_boxes_pixels")
    dpi = block.metadata.get("render_dpi")
    if not boxes or not dpi:
        return []
    spans = _word_spans(block.text)
    if len(spans) != len(boxes):
        return []
    return [
        _pixel_rect(page, box, dpi)
        for (start, end), box in zip(spans, boxes)
        if start < entity.end and end > entity.start
    ]


def _native_rects(page: pymupdf.Page, block: ContentBlock, value: str) -> list[pymupdf.Rect]:
    bbox = block.metadata.get("bbox")
    clip = pymupdf.Rect(bbox) + (-1, -1, 1, 1) if bbox else None
    hits = page.search_for(value, clip=clip)
    if hits:
        return hits
    # Values broken over lines or with odd spacing: redact each word inside the block.
    rects = []
    for word in value.split():
        rects.extend(page.search_for(word, clip=clip))
    return rects


def redacted_spans(original: str, sanitized: str) -> list[tuple[int, int]]:
    """Spans of the original text that were replaced in the sanitized text.

    Diffing the final sanitized text (rather than first-pass detections) covers
    replacements from every sanitization pass, so the masked PDF hides exactly
    what the sanitized text hides.
    """
    # Diff whole words (and whitespace runs), not characters: a character diff can
    # align a "." or a capital letter of the original with the same character in a
    # token, leaving it visible between two masks.
    original_parts = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+|\s+", original)]
    sanitized_parts = [m.group() for m in re.finditer(r"\S+|\s+", sanitized)]
    matcher = SequenceMatcher(None, [part for _, _, part in original_parts], sanitized_parts, autojunk=False)
    spans = []
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag in ("replace", "delete") and i2 > i1:
            spans.append((original_parts[i1][0], original_parts[i2 - 1][1]))
    return spans


REVIEW_WATERMARK = "REVIEW COPY - NOT APPROVED BY THE PRIVACY GATE - MAY CONTAIN PERSONAL DATA"


def redact_pdf(
    source: str | Path, document: Document, sanitized: Document, watermark: str | None = None,
    mask_all_figures: bool = True,
) -> RedactedPdf:
    """Black out every replaced span of the final sanitized text in a copy of the source PDF.

    watermark, if given, is stamped in red at the top of every page (used for
    review copies of documents the privacy gate blocked).

    mask_all_figures (strict mode, the default) masks every detected figure
    region whole, whatever its OCR confidence: values that OCR could not read
    in a figure are then hidden too. With False, only unreadable figures are
    masked whole; readable figures keep their text, with the detected values
    and photo/barcode regions masked.
    """
    blocks = {block.block_id: block for block in document.blocks}
    final = {block.block_id: block.text for block in sanitized.blocks}
    targets: list[PIIEntity] = []
    for block in document.blocks:
        if block.block_id in final and final[block.block_id] != block.text:
            for start, end in redacted_spans(block.text, final[block.block_id]):
                if block.text[start:end].strip():
                    targets.append(PIIEntity("REDACTED", start, end, 1.0, "derivative", block.block_id))
    with pymupdf.open(source) as pdf:
        page_count = pdf.page_count
        report = RedactedPdf(b"", page_count)
        touched: set[int] = set()
        for entity in targets:
            block = blocks.get(entity.block_id)
            if block is None or block.page_number is None:
                report.unlocated += 1
                continue
            page = pdf[block.page_number - 1]
            if block.extraction_method in ("ocr", "figure_ocr"):
                rects = _ocr_rects(page, block, entity)
            else:
                rects = _native_rects(page, block, block.text[entity.start:entity.end])
            if not rects:
                report.unlocated += 1
                continue
            for rect in rects:
                page.add_redact_annot(rect, fill=(0, 0, 0))
            report.boxes += len(rects)
            method = block.extraction_method or "unknown"
            report.by_method[method] = report.by_method.get(method, 0) + 1
            touched.add(page.number)
        for region in document.metadata.get("figure_regions", []):
            page = pdf[region["page"] - 1]
            if region["bbox_pixels"] is None:
                report.figure_scan_failures += 1
                continue
            whole = mask_all_figures or not region["readable"]
            masks = [region["bbox_pixels"]] if whole else []
            # Inside a figure masked whole, the figure mask already covers the photos.
            photos = [] if whole else region["photos"]
            for box in masks + photos:
                page.add_redact_annot(_pixel_rect(page, box, region["render_dpi"]), fill=(0, 0, 0))
                touched.add(page.number)
            report.unreadable_figures += not region["readable"]
            report.strict_figures += bool(mask_all_figures)
            report.photos += len(photos)
            report.boxes += len(masks) + len(photos)
        for number in sorted(touched):
            pdf[number].apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
        if watermark:
            for page in pdf:
                box = pymupdf.Rect(page.rect.x0 + 18, page.rect.y0 + 4, page.rect.x1 - 18, page.rect.y0 + 22)
                page.insert_textbox(box, watermark, fontsize=9, color=(0.8, 0, 0), align=pymupdf.TEXT_ALIGN_CENTER)
        pdf.set_metadata({})
        pdf.del_xml_metadata()
        report.data = pdf.tobytes(garbage=4, deflate=True)
    with pymupdf.open(stream=report.data, filetype="pdf") as check:
        if check.page_count != page_count:
            raise RuntimeError("Redacted PDF page count changed.")
    return report
