"""Small public error contract for native extraction."""


class ExtractionError(Exception):
    """The file cannot be extracted; no partial Document is returned."""


class OCRRequiredError(ExtractionError):
    """Insufficient native PDF text; OCR may be required, but was not attempted."""
