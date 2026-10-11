"""Audit reporting module."""

from privacygate.audit.report import (
    audit_report_to_dict,
    audit_report_to_json,
    generate_audit_report,
)
from privacygate.audit.residual_diagnostics import (
    build_residual_diagnostics,
)

__all__ = [
    "generate_audit_report",
    "audit_report_to_dict",
    "audit_report_to_json",
    "build_residual_diagnostics",
]
