"""Deterministic regular-expression PII detection for structured formats."""

from __future__ import annotations

import re
from privacygate.models import PIIEntity


def _luhn_checksum(card_number: str) -> bool:
    """Return True if card_number satisfies the Luhn algorithm."""
    digits = [int(c) for c in card_number if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for idx, d in enumerate(reverse_digits):
        if idx % 2 == 1:
            doubled = d * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += d
    return checksum % 10 == 0


EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

PHONE_PATTERN = re.compile(
    r"(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9])\s*\)|([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9]))\s*(?:[.-]\s*)?)?([2-9]1[02-9]|[2-9][02-9]1|[2-9][02-9]{2})\s*(?:[.-]\s*)?([0-9]{4})(?:\s*(?:#|x\.?|ext\.?|extension)\s*(\d+))?\b|\b(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b"
)

SSN_PATTERN = re.compile(
    r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"
)

IP_PATTERN = re.compile(
    r"\b(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
)

IBAN_PATTERN = re.compile(
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]{0,16})\b"
)

# Potential 13-19 digit card numbers separated by optional space or dash
CREDIT_CARD_CANDIDATE = re.compile(
    r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b|\b\d{13,19}\b"
)


def detect_regex(text: str, block_id: str = "") -> list[PIIEntity]:
    """Scan text for structured PII patterns and return normalized PIIEntity objects."""
    if not text:
        return []

    entities: list[PIIEntity] = []

    # 1. Email
    for match in EMAIL_PATTERN.finditer(text):
        entities.append(
            PIIEntity(
                entity_type="EMAIL",
                start=match.start(),
                end=match.end(),
                confidence=1.0,
                detector="regex",
                block_id=block_id,
            )
        )

    # 2. US SSN
    for match in SSN_PATTERN.finditer(text):
        entities.append(
            PIIEntity(
                entity_type="GOVERNMENT_ID",
                start=match.start(),
                end=match.end(),
                confidence=1.0,
                detector="regex",
                block_id=block_id,
            )
        )

    # 3. IP Address
    for match in IP_PATTERN.finditer(text):
        # Exclude standard local loopback if desirable, but PRD asks to identify IP addresses
        entities.append(
            PIIEntity(
                entity_type="IP_ADDRESS",
                start=match.start(),
                end=match.end(),
                confidence=0.95,
                detector="regex",
                block_id=block_id,
            )
        )

    # 4. IBAN
    for match in IBAN_PATTERN.finditer(text):
        entities.append(
            PIIEntity(
                entity_type="ACCOUNT_NUMBER",
                start=match.start(),
                end=match.end(),
                confidence=0.95,
                detector="regex",
                block_id=block_id,
            )
        )

    # 5. Credit Cards (verified with Luhn checksum)
    for match in CREDIT_CARD_CANDIDATE.finditer(text):
        val = match.group()
        if _luhn_checksum(val):
            entities.append(
                PIIEntity(
                    entity_type="CREDIT_CARD",
                    start=match.start(),
                    end=match.end(),
                    confidence=1.0,
                    detector="regex",
                    block_id=block_id,
                )
            )

    # 6. Phone Numbers (filter out pure dates or pure numbers that don't match phone structure)
    for match in PHONE_PATTERN.finditer(text):
        matched_str = match.group().strip()
        # Ensure it contains at least 7 digits to avoid matching short numbers or dates
        digits_only = re.sub(r"\D", "", matched_str)
        if len(digits_only) >= 7 and len(digits_only) <= 15:
            # Avoid duplicate if it overlaps with an already found SSN or card
            entities.append(
                PIIEntity(
                    entity_type="PHONE",
                    start=match.start(),
                    end=match.end(),
                    confidence=0.90,
                    detector="regex",
                    block_id=block_id,
                )
            )

    return entities
