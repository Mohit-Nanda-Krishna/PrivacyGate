"""Shared in-memory data contracts; no document processing or persistence."""

from dataclasses import dataclass, field
from typing import Any, Literal

RiskLevel = Literal["CRITICAL", "HIGH", "MEDIUM"]
PrivacyStatus = Literal["APPROVED", "BLOCKED"]


@dataclass
class ContentBlock:
    """Text and its source position; non-applicable locations remain None."""

    block_id: str
    text: str = field(repr=False)
    page_number: int | None = None
    slide_number: int | None = None
    paragraph_number: int | None = None
    extraction_method: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Document:
    """Canonical document shared by all future extraction modules."""

    document_id: str
    filename: str = field(repr=False)
    file_type: str
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)
    blocks: list[ContentBlock] = field(default_factory=list, repr=False)


@dataclass
class PIIEntity:
    """A detection with block-relative [start, end) offsets, without raw PII."""

    entity_type: str
    start: int
    end: int
    confidence: float
    detector: str
    block_id: str
    source_location: dict[str, int | str] = field(default_factory=dict)
    risk_level: RiskLevel | None = None


@dataclass
class ValidationResult:
    """A result container, not a validator. Unvalidated content is blocked."""

    status: PrivacyStatus = "BLOCKED"
    reason: str = "Privacy validation has not been performed."
    residual_entities: list[PIIEntity] = field(default_factory=list)


@dataclass
class AuditReport:
    """Summary counts and decision only; no document text or raw PII values."""

    document_id: str
    detected_count: int = 0
    redacted_count: int = 0
    counts_by_category: dict[str, int] = field(default_factory=dict)
    counts_by_risk: dict[RiskLevel, int] = field(default_factory=dict)
    validation: ValidationResult = field(default_factory=ValidationResult)
    # Per-page extraction status (native / ocr / failed, attempts, seconds); PDFs only.
    page_report: list[dict[str, Any]] = field(default_factory=list)
    # Detected entity counts by where the text lives (body, table, header, image, ...).
    counts_by_location: dict[str, int] = field(default_factory=dict)
    # Embedded image OCR status (ocr / skipped_tiny / skipped_vector / failed) and warnings.
    embedded_images: list[dict[str, Any]] = field(default_factory=list)
    extraction_warnings: list[dict[str, str]] = field(default_factory=list)
