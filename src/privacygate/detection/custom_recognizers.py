"""Configurable enterprise-specific custom PII recognizers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from privacygate.models import PIIEntity


@dataclass(frozen=True)
class EnterprisePattern:
    """A configurable enterprise-specific pattern rule."""

    name: str
    entity_type: str
    pattern: re.Pattern[str]
    confidence: float = 0.95
    capture_group: int = 0  # 0 for entire match, 1+ for specific group


DEFAULT_ENTERPRISE_PATTERNS: tuple[EnterprisePattern, ...] = (
    # Employee ID: EMP-12345 or "Employee ID: 38291"
    EnterprisePattern(
        name="Employee ID Code",
        entity_type="EMPLOYEE_ID",
        pattern=re.compile(r"\bEMP-\d{4,8}\b", re.IGNORECASE),
        confidence=0.98,
    ),
    EnterprisePattern(
        name="Employee ID Labelled",
        entity_type="EMPLOYEE_ID",
        pattern=re.compile(r"\bEmployee\s+ID\s*[:#]?\s*([A-Za-z0-9-]+)\b", re.IGNORECASE),
        confidence=0.95,
        capture_group=1,
    ),
    # Client ID: C-839201 or "Client ID: C-839201"
    EnterprisePattern(
        name="Client ID Code",
        entity_type="CLIENT_ID",
        pattern=re.compile(r"\bC-\d{5,8}\b", re.IGNORECASE),
        confidence=0.95,
    ),
    EnterprisePattern(
        name="Client ID Labelled",
        entity_type="CLIENT_ID",
        pattern=re.compile(r"\bClient\s+ID\s*[:#]?\s*([A-Za-z0-9-]+)\b", re.IGNORECASE),
        confidence=0.95,
        capture_group=1,
    ),
    # Portfolio ID: AX-9832 or "Portfolio ID: AX-9832"
    EnterprisePattern(
        name="Portfolio ID Code",
        entity_type="PORTFOLIO_ID",
        pattern=re.compile(r"\bAX-\d{4,6}\b", re.IGNORECASE),
        confidence=0.95,
    ),
    EnterprisePattern(
        name="Portfolio ID Labelled",
        entity_type="PORTFOLIO_ID",
        pattern=re.compile(r"\bPortfolio\s+ID\s*[:#]?\s*([A-Za-z0-9-]+)\b", re.IGNORECASE),
        confidence=0.95,
        capture_group=1,
    ),
    # Customer Reference: CR-19382 or "Customer Reference: CR-19382"
    EnterprisePattern(
        name="Customer Reference Code",
        entity_type="CUSTOMER_REF",
        pattern=re.compile(r"\bCR-\d{4,8}\b", re.IGNORECASE),
        confidence=0.95,
    ),
    EnterprisePattern(
        name="Customer Reference Labelled",
        entity_type="CUSTOMER_REF",
        pattern=re.compile(r"\bCustomer\s+Ref(?:erence)?\s*[:#]?\s*([A-Za-z0-9-]+)\b", re.IGNORECASE),
        confidence=0.95,
        capture_group=1,
    ),
    # Account Number: ACC-123456 or "Account Number: 12345678"
    EnterprisePattern(
        name="Account ID Code",
        entity_type="ACCOUNT_NUMBER",
        pattern=re.compile(r"\bACC-\d{4,12}\b", re.IGNORECASE),
        confidence=0.98,
    ),
    EnterprisePattern(
        name="Account Number Labelled",
        entity_type="ACCOUNT_NUMBER",
        pattern=re.compile(r"\bAccount\s+(?:No|Number|#)\s*[:#]?\s*([A-Za-z0-9-]+)\b", re.IGNORECASE),
        confidence=0.95,
        capture_group=1,
    ),
)


class CustomRecognizer:
    """Engine executing custom enterprise recognizers."""

    def __init__(self, patterns: Sequence[EnterprisePattern] | None = None) -> None:
        self.patterns = list(patterns if patterns is not None else DEFAULT_ENTERPRISE_PATTERNS)

    def add_pattern(self, pattern: EnterprisePattern) -> None:
        """Add an additional enterprise pattern rule."""
        self.patterns.append(pattern)

    def detect(self, text: str, block_id: str = "") -> list[PIIEntity]:
        """Scan text with enterprise patterns and return PIIEntity objects."""
        if not text:
            return []

        results: list[PIIEntity] = []
        for rule in self.patterns:
            for match in rule.pattern.finditer(text):
                if rule.capture_group > 0 and len(match.groups()) >= rule.capture_group:
                    start = match.start(rule.capture_group)
                    end = match.end(rule.capture_group)
                else:
                    start = match.start()
                    end = match.end()

                if end > start:
                    results.append(
                        PIIEntity(
                            entity_type=rule.entity_type,
                            start=start,
                            end=end,
                            confidence=rule.confidence,
                            detector="custom_enterprise",
                            block_id=block_id,
                        )
                    )
        return results


# Global singleton instance
_DEFAULT_RECOGNIZER = CustomRecognizer()


def detect_custom(text: str, block_id: str = "") -> list[PIIEntity]:
    """Scan text using default enterprise recognizers."""
    return _DEFAULT_RECOGNIZER.detect(text, block_id=block_id)
