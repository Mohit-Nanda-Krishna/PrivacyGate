"""Targeted regex detection for structured formats and labelled patterns."""

from __future__ import annotations

import re

from privacygate.detection.common import make_entity
from privacygate.models import ContentBlock, PIIEntity


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
    r"(?<![\w.@%+-])[A-Z0-9_%+-]+(?:\.[A-Z0-9_%+-]+)*@"
    r"[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?)*\.[A-Z]{2,63}(?![\w@-])",
    re.IGNORECASE,
)

# Labelled phone pattern
PHONE_LABELLED_PATTERN = re.compile(
    r"\b(?:phone|telephone|mobile|tel)[ \t]*:[ \t]*"
    r"(?P<value>(?:\+[1-9]\d{0,2}[ -])?(?:\(\d{2,4}\)|\d{2,4})"
    r"(?:[ -]\d{2,4}){2,3}|\+[1-9]\d{9,14})(?![\w-])",
    re.IGNORECASE,
)

# Standard international/US phone pattern
PHONE_STANDARD_PATTERN = re.compile(
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

CREDIT_CARD_CANDIDATE = re.compile(
    r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b|\b\d{13,19}\b"
)


def detect_regex(block: ContentBlock | str, block_id: str = "") -> list[PIIEntity]:
    """Scan block for structured and labelled regex PII."""
    if isinstance(block, str):
        content_block = ContentBlock(block_id=block_id or "block", text=block)
    else:
        content_block = block

    if not content_block.text or not content_block.text.strip():
        return []

    text = content_block.text
    entities: list[PIIEntity] = []
    seen_spans: set[tuple[int, int]] = set()

    # 1. Email (including internal domain support)
    for match in EMAIL_PATTERN.finditer(text):
        span = (match.start(), match.end())
        seen_spans.add(span)
        entities.append(
            make_entity(content_block, "EMAIL_ADDRESS", span[0], span[1], 0.95, "regex:email")
        )

    # 2. Labelled phone numbers
    for match in PHONE_LABELLED_PATTERN.finditer(text):
        val = match["value"]
        if 10 <= sum(c.isdigit() for c in val) <= 15:
            span = match.span("value")
            seen_spans.add(span)
            entities.append(
                make_entity(content_block, "PHONE_NUMBER", span[0], span[1], 0.85, "regex:labelled_phone")
            )

    # 3. Standard phone numbers
    for match in PHONE_STANDARD_PATTERN.finditer(text):
        matched_str = match.group().strip()
        digits_only = re.sub(r"\D", "", matched_str)
        if 7 <= len(digits_only) <= 15:
            span = (match.start(), match.end())
            if span not in seen_spans:
                seen_spans.add(span)
                entities.append(
                    make_entity(content_block, "PHONE_NUMBER", span[0], span[1], 0.90, "regex:phone")
                )

    # 4. SSN
    for match in SSN_PATTERN.finditer(text):
        span = (match.start(), match.end())
        if span not in seen_spans:
            seen_spans.add(span)
            entities.append(
                make_entity(content_block, "US_SSN", span[0], span[1], 1.0, "regex:ssn")
            )

    # 5. IP Address
    for match in IP_PATTERN.finditer(text):
        span = (match.start(), match.end())
        if span not in seen_spans:
            seen_spans.add(span)
            entities.append(
                make_entity(content_block, "IP_ADDRESS", span[0], span[1], 0.95, "regex:ip")
            )

    # 6. IBAN
    for match in IBAN_PATTERN.finditer(text):
        span = (match.start(), match.end())
        if span not in seen_spans:
            seen_spans.add(span)
            entities.append(
                make_entity(content_block, "IBAN_CODE", span[0], span[1], 0.95, "regex:iban")
            )

    # 7. Credit Cards (Luhn verified)
    for match in CREDIT_CARD_CANDIDATE.finditer(text):
        val = match.group()
        if _luhn_checksum(val):
            span = (match.start(), match.end())
            if span not in seen_spans:
                seen_spans.add(span)
                entities.append(
                    make_entity(content_block, "CREDIT_CARD", span[0], span[1], 1.0, "regex:credit_card")
                )

    return entities
