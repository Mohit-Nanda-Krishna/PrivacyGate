"""Native PDF text blocks in page order and PyMuPDF's coordinate-sorted order."""

from pathlib import Path
from uuid import uuid4

import pymupdf

from privacygate.extraction.errors import ExtractionError, OCRRequiredError
from privacygate.models import ContentBlock, Document

# A conservative text-availability check, not scanned-page detection or proof
# of extraction completeness. Even a valid very short PDF may need review.
MIN_NATIVE_TEXT_CHARACTERS = 20


def extract_pdf(path: str | Path) -> Document:
    """Extract native text with 1-based pages/order and original block numbers.

    Raise OCRRequiredError below 20 alphanumeric characters across the file.
    Report pages without text in metadata; never infer that they are scanned.
    Images, annotations, and forms are not extracted. No OCR is attempted.
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
                document.blocks.extend(page_blocks)

            character_count = sum(
                character.isalnum() for block in document.blocks for character in block.text
            )
            if character_count < MIN_NATIVE_TEXT_CHARACTERS:
                raise OCRRequiredError(
                    "PDF has insufficient native text (fewer than 20 alphanumeric characters). "
                    "OCR may be required; OCR was not attempted."
                )
            document.metadata = {
                "page_count": source.page_count,
                "native_text_character_count": character_count,
                "pages_without_native_text": pages_without_text,
            }
            return document
    except ExtractionError:
        raise
    except (FileNotFoundError, pymupdf.FileNotFoundError):
        raise ExtractionError("PDF file not found.") from None
    except Exception:
        # Parser messages can include input paths or document text.
        raise ExtractionError("Could not extract PDF. Check that the file is readable and valid.") from None
