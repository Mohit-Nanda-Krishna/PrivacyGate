"""End-to-end pipeline orchestrating extraction, detection, redaction, and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from privacygate.audit import generate_audit_report
from privacygate.detection import detect_pii
from privacygate.extraction import extract_document
from privacygate.models import AuditReport, Document, PIIEntity, ValidationResult
from privacygate.redaction import redact_document
from privacygate.risk import classify_risks
from privacygate.validation import validate_privacy


@dataclass
class PipelineResult:
    """Rich artifact container with all intermediate stages of the pipeline."""

    document: Document
    entities: list[PIIEntity]
    sanitized_document: Document
    validation: ValidationResult
    audit_report: AuditReport
    passes_executed: int = 1


def run_pipeline(file_path: str | Path, max_passes: int = 1) -> PipelineResult:
    """Execute the complete PrivacyGate firewall pipeline end-to-end.

    Stages:
    1. Extraction & structure preservation
    2. Hybrid PII detection
    3. Sensitivity risk classification
    4. Context-preserving semantic redaction
    5. Secondary fail-closed privacy scan
    6. Audit report generation

    Args:
        file_path: Path to document to process.
        max_passes: Maximum sanitization passes (default 1). If > 1, automatically
            attempts iterative cleaning of any residual PII detected in secondary scan.
    """
    path = Path(file_path)

    # 1. Extraction
    document = extract_document(path)

    # 2. PII Detection (Initial Pass)
    entities = detect_pii(document)

    # 3. Risk Classification
    classify_risks(entities)

    # 4. Semantic Redaction
    sanitized_doc, redactions = redact_document(document, entities)

    # 5. Secondary Privacy Scan
    validation = validate_privacy(sanitized_doc)
    passes_executed = 1

    # Optional Iterative Multi-Pass Sanitization if residuals exist and max_passes > 1
    if max_passes > 1 and validation.status != "APPROVED" and validation.residual_entities:
        for _ in range(1, max_passes):
            passes_executed += 1
            classify_risks(validation.residual_entities)
            sanitized_doc, extra_redactions = redact_document(
                sanitized_doc, validation.residual_entities
            )
            redactions.extend(extra_redactions)
            validation = validate_privacy(sanitized_doc)
            if validation.status == "APPROVED":
                break

    # 6. Audit Report
    audit_report = generate_audit_report(
        document=document,
        detected_entities=entities,
        redacted_count=len(redactions),
        validation_result=validation,
    )

    return PipelineResult(
        document=document,
        entities=entities,
        sanitized_document=sanitized_doc,
        validation=validation,
        audit_report=audit_report,
        passes_executed=passes_executed,
    )


def process_document(file_path: str | Path, max_passes: int = 1) -> AuditReport:
    """Pipeline entry point returning the canonical AuditReport."""
    result = run_pipeline(file_path, max_passes=max_passes)
    return result.audit_report

