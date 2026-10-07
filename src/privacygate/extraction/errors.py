"""Small public error contract for document extraction."""


class ExtractionError(Exception):
    """The file cannot be extracted; no partial Document is returned."""


class OCRRequiredError(ExtractionError):
    """A PDF page requires OCR but the local Tesseract executable is unavailable."""
