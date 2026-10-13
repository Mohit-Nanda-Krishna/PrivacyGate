"""Withhold the text of figures whose OCR was not trusted.

The redacted PDF masks every figure region whose OCR confidence was too low to
trust (derivatives.redact_pdf). The sanitized text must agree: every OCR line
inside such a region (the figure's own OCR lines and the page OCR lines that
fall inside it) is replaced by one [FIGURE_UNREADABLE_n] token per figure, so
unreliable text never reaches the model and nothing is left that the PDF hides.
"""

from __future__ import annotations

from dataclasses import replace

from privacygate.models import ContentBlock, Document
from privacygate.redaction.redactor import PseudonymSession

OCR_METHODS = frozenset({"ocr", "figure_ocr"})


def unreadable_regions(document: Document) -> list[dict]:
    """Figure regions of a scanned PDF that the redacted PDF masks as unreadable."""
    return [
        region for region in document.metadata.get("figure_regions", [])
        if not region.get("readable") and region.get("bbox_pixels")
    ]


def _inside(block: ContentBlock, region: dict) -> bool:
    if block.page_number != region["page"] or block.extraction_method not in OCR_METHODS:
        return False
    if block.extraction_method == "figure_ocr":
        return block.metadata.get("figure") == region["figure"]
    box = block.metadata.get("bbox_pixels")
    if not box:
        return False
    x0, y0, x1, y1 = region["bbox_pixels"]
    centre_x, centre_y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return x0 <= centre_x <= x1 and y0 <= centre_y <= y1


def withhold_unreadable_figures(
    document: Document, sanitized: Document, session: PseudonymSession,
) -> tuple[Document, int]:
    """Replace the sanitized text of every line inside an unreadable figure with that figure's token.

    document is the extracted document (its metadata holds the figure regions);
    sanitized is the redacted copy. Returns the new sanitized document and the
    number of figures withheld. Blocks keep their ids and locations.
    """
    regions = unreadable_regions(document)
    if not regions:
        return sanitized, 0
    tokens = {}
    blocks = []
    for block in sanitized.blocks:
        region = next((region for region in regions if _inside(block, region)), None)
        if region is None:
            blocks.append(block)
            continue
        key = (region["page"], region["figure"])
        if key not in tokens:
            tokens[key] = session.unreadable_figure_token()
        blocks.append(replace(block, text=tokens[key], metadata=dict(block.metadata)))
    return replace(sanitized, blocks=blocks), len(regions)
