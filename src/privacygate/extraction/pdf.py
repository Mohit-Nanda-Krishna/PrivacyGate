"""Native PDF extraction with page-level local OCR fallback."""

from pathlib import Path
from uuid import uuid4

import pymupdf

from privacygate.extraction.errors import ExtractionError
from privacygate.extraction.ocr import MIN_TEXT_CHARACTERS, extract_page_ocr
from privacygate.models import ContentBlock, Document

# Deterministic per-page heuristic, not proof of scanned-page classification
# or complete extraction. Native pages below this threshold require OCR.
MIN_NATIVE_TEXT_CHARACTERS = MIN_TEXT_CHARACTERS


def extract_pdf(path: str | Path) -> Document:
    """Extract native text with 1-based pages/order and original block numbers.

    Pages with fewer than 20 native alphanumeric characters use local OCR.
    A required OCR failure rejects the entire document, including blank pages.
    Native and OCR text are never combined for the same page. Native-rich pages
    may still contain image text; this heuristic does not guarantee coverage.
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
            ocr_pages = []
            character_count = 0
            for page_number, page in enumerate(source, start=1):
                page_blocks = []
                for block in page.get_text("blocks", sort=True):
                    x0, y0, x1, y1, text, source_number, block_type = block
                    if block_type != 0 or not text.strip():
                        continue
                    order = len(page_blocks) + 1
                    page_blocks.append(ContentBlock(
                        block_id=f"page_{page_number}_block_{order}",
                        text=text.strip(), page_number=page_number,
                        extraction_method="pdf_native",
                        metadata={
                            "block_order": order,
                            "source_block_number": source_number,
                            "bbox": [x0, y0, x1, y1],
                        },
                    ))
                if not page_blocks:
                    pages_without_text.append(page_number)
                page_character_count = sum(
                    character.isalnum() for block in page_blocks for character in block.text
                )
                character_count += page_character_count
                if page_character_count < MIN_NATIVE_TEXT_CHARACTERS:
                    page_blocks = extract_page_ocr(page)
                    ocr_pages.append(page_number)
                document.blocks.extend(page_blocks)

            if not document.blocks:
                raise ExtractionError("PDF contains no extractable pages or text.")
            document.metadata = {
                "page_count": source.page_count,
                "native_text_character_count": character_count,
                "pages_without_native_text": pages_without_text,
                "ocr_pages": ocr_pages,
            }
            return document
    except ExtractionError:
        raise
    except (FileNotFoundError, pymupdf.FileNotFoundError):
        raise ExtractionError("PDF file not found.") from None
    except Exception:
        # Parser messages can include input paths or document text.
        raise ExtractionError("Could not extract PDF. Check that the file is readable and valid.") from None
