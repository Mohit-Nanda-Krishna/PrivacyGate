"""Risk classification module."""

from privacygate.risk.classifier import (
    classify_entity_risk,
    classify_risks,
    get_risk_level,
    summarize_risks,
)

__all__ = [
    "get_risk_level",
    "classify_entity_risk",
    "classify_risks",
    "summarize_risks",
]
