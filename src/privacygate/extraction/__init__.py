"""Local extraction; extracted content has not passed privacy validation."""

from pathlib import Path

from privacygate.extraction.docx import extract_docx
from privacygate.extraction.errors import ExtractionError, OCRRequiredError
from privacygate.extraction.pdf import extract_pdf
from privacygate.extraction.pptx import extract_pptx
from privacygate.models import Document

__all__ = ["extract_document", "ExtractionError", "OCRRequiredError"]


def extract_document(path: str | Path) -> Document:
    """Dispatch a local PDF, DOCX, or PPTX path by case-insensitive extension.

    Parsers also validate the underlying format. PDF pages with insufficient
    native text use local OCR. No privacy approval or network access is performed.
    Errors never return a partially extracted file.
    """
    path = Path(path)
    extractors = {".pdf": extract_pdf, ".docx": extract_docx, ".pptx": extract_pptx}
    extractor = extractors.get(path.suffix.lower())
    if extractor is None:
        raise ExtractionError("Unsupported file type. Supported extensions: .pdf, .docx, .pptx.")
    return extractor(path)
