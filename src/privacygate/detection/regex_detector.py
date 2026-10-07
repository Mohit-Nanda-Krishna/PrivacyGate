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

# Standard international/US phone pattern. The international branch must start at
# "+" itself: a leading \b can never match before "+", which used to drop the
# country code from every international number.
PHONE_STANDARD_PATTERN = re.compile(
    r"(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9])\s*\)|([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9]))\s*(?:[.-]\s*)?)?([2-9]1[02-9]|[2-9][02-9]1|[2-9][02-9]{2})\s*(?:[.-]\s*)?([0-9]{4})(?:\s*(?:#|x\.?|ext\.?|extension)\s*(\d+))?\b|(?<![\w+])\+\d{1,3}(?:[\s.-]?\(?\d{1,5}\)?){1,3}[\s.-]?\d{3,5}(?![\d/])|(?<![\w+])\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b"
)

# 9xx area numbers are ITINs/test SSNs; still personal identifiers, so detected.
SSN_PATTERN = re.compile(
    r"\b(?!000|666)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"
)

_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_DATE = (rf"(?:\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}|\d{{1,2}}\s+{_MONTH}\.?,?\s+\d{{4}}|"
         rf"{_MONTH}\.?\s+\d{{1,2}},?\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})")
_STREET = (r"(?:Street|St|Lane|Ln|Avenue|Ave|Road|Rd|Court|Ct|Crescent|Cres|Drive|Dr|Boulevard|Blvd|Way|"
           r"Place|Pl|Terrace|Ter|Parkway|Pkwy|Circle|Cir|Square|Sq)")

# (entity type, pattern with a "value" group, confidence, detector). Context words
# (labels such as "DOB" or "passport") are matched but never redacted.
CONTEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], float, str], ...] = (
    # Short or partial international numbers: "+1 (555) 0114", "M +1 (555) 0114".
    ("PHONE_NUMBER", re.compile(r"(?<![\w+])(?P<value>\+\d{1,3}[ \t]?\(\d{2,4}\)[ \t]?\d{3,4}(?:[ \t-]\d{3,4})?)"
                                r"(?![\d-])"), 0.85, "regex:phone_short"),
    # Labelled numbers without a country code: "Mobile 555 0114", "M: 555-0121".
    ("PHONE_NUMBER", re.compile(r"\b(?:M|T|Mob|Mobile|Cell|Phone|Tel|Telephone)\b\.?:?[ \t]*"
                                r"(?P<value>\(?\d{3}\)?[ .-]?\d{3,4}(?:[ .-]\d{3,4})?)(?![\d-])"), 0.8,
     "regex:labelled_phone"),
    # Indian PAN: 5 letters (4th = holder type), 4 digits, 1 letter.
    ("GOVERNMENT_ID", re.compile(r"\b(?P<value>[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z])\b"), 0.9, "regex:in_pan"),
    ("GOVERNMENT_ID", re.compile(r"(?i:\bpassport(?:\s+(?:no\.?|number|#))?)[\s:#]*(?P<value>[A-Z]{1,2}\d{6,8})\b"),
     0.9, "regex:passport"),
    ("GOVERNMENT_ID", re.compile(r"(?i:\bPESEL)[\s:#]*(?P<value>\d{6}[\dXx]{5})\b"), 0.9, "regex:pesel"),
    # "last four digits of your social security number (8827)".
    ("GOVERNMENT_ID", re.compile(r"(?i:\blast\s+(?:four|4)\s+digits\b)[^.\n]{0,60}?\(?(?P<value>\d{4})\)?(?![\d-])"),
     0.85, "regex:ssn_last4"),
    ("GOVERNMENT_ID", re.compile(r"(?i:\b(?:social\s+security(?:\s+number)?|SSN)\s*)\((?P<value>\d{4})\)"),
     0.85, "regex:ssn_last4"),
    ("DATE_OF_BIRTH", re.compile(rf"(?i:\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth|born(?:\s+on)?)\b)[\s:,-]*"
                                 rf"(?P<value>{_DATE})"), 0.9, "regex:dob"),
    # "card ending 2218", "savings account ending in 7741": only the digits are PII.
    ("ACCOUNT_NUMBER", re.compile(r"(?i:\b(?:card|account|acct|a/c)\b[^.\n]{0,40}?\b(?:ending|ends)"
                                  r"(?:\s+(?:in|with))?)\s+(?P<value>\d{4})\b"), 0.9, "regex:account_ending"),
    # US street address with optional apartment/suite and city, state ZIP.
    ("ADDRESS", re.compile(rf"(?P<value>\b\d{{1,5}}\s+(?:[A-Z][a-z]+\s+){{1,3}}{_STREET}\.?"
                           rf"(?:,?\s+(?:Apartment|Apt|Suite|Ste|Unit|Floor|Fl)\.?\s*#?\s*\w+)?"
                           rf",?\s+(?:[A-Z][a-z]+\s?){{1,3}},\s*[A-Z]{{2}}\s+\d{{5}}(?:-\d{{4}})?)\b"), 0.85,
     "regex:us_address"),
)

# Organisation e-mail domains whose OCR-damaged forms are still matched,
# e.g. "cadencetg.com" or a local part fused to the domain after a lost "@".
ORG_EMAIL_DOMAINS: tuple[str, ...] = ("cadencefg.com",)
_OCR_CONFUSIONS = {"c": "[ce(]", "f": "[ft]", "o": "[o0]", "l": "[l1I|]", "i": "[il1|]", "m": "(?:m|rn)",
                   "e": "[ec]", "g": "[gq9]", ".": r"[.,]"}


def _ocr_domain(domain: str) -> str:
    name, _, tld = domain.rpartition(".")
    fuzzy = "".join(_OCR_CONFUSIONS.get(character, re.escape(character)) for character in name)
    # OCR often truncates the line end: "cadencefg.c", "cadencefg.co".
    tail = "".join(f"(?:{_OCR_CONFUSIONS.get(c, re.escape(c))}" for c in tld) + ")?" * (len(tld) - 1) + ")"
    return fuzzy + r"[.,]\s?" + tail


OCR_EMAIL_PATTERN = re.compile(
    r"(?<![\w.@|])(?P<value>[A-Za-z0-9._|-]{2,40}\s?@?\s?(?:"
    + "|".join(_ocr_domain(domain) for domain in ORG_EMAIL_DOMAINS)
    + r"))(?![\w])",
    re.IGNORECASE,
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

    # 7. Context and labelled patterns (short phones, PAN, passport, DOB, ...)
    for entity_type, pattern, confidence, detector in CONTEXT_PATTERNS:
        for match in pattern.finditer(text):
            value = match["value"]
            if entity_type == "PHONE_NUMBER" and sum(c.isdigit() for c in value) < 7:
                continue
            span = match.span("value")
            if span not in seen_spans:
                seen_spans.add(span)
                entities.append(make_entity(content_block, entity_type, span[0], span[1], confidence, detector))

    # 8. OCR-damaged organisation e-mail addresses
    for match in OCR_EMAIL_PATTERN.finditer(text):
        span = match.span("value")
        if span not in seen_spans and not any(s <= span[0] and span[1] <= e for s, e in seen_spans):
            seen_spans.add(span)
            entities.append(make_entity(content_block, "EMAIL_ADDRESS", span[0], span[1], 0.8, "regex:email_ocr"))

    # 9. Credit Cards (Luhn verified)
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
