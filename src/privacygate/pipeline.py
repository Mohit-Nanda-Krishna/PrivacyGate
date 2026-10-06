"""Pipeline entry point reserved for future processing phases."""

from pathlib import Path

from privacygate.models import AuditReport


def process_document(file_path: str | Path) -> AuditReport:
    """Eventually orchestrate extraction through audit; Phase 0 cannot process files."""
    raise NotImplementedError(
        "Document processing is unavailable in Phase 0. No privacy approval was issued."
    )
