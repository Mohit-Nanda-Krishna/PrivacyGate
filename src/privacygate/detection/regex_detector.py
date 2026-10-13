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


# Issuer prefix ranges and lengths of the major card schemes. Luhn alone accepts
# about 1 in 10 random digit strings; requiring a real issuer prefix and length
# keeps long reference and account numbers from being read as card numbers.
_CARD_SCHEMES: tuple[tuple[tuple[str, ...], tuple[int, ...]], ...] = (
    (("4",), (13, 16, 19)),  # Visa
    (tuple(str(p) for p in range(51, 56)) + tuple(str(p) for p in range(2221, 2721)), (16,)),  # Mastercard
    (("34", "37"), (15,)),  # American Express
    (("6011", "65") + tuple(str(p) for p in range(644, 650)), (16, 17, 18, 19)),  # Discover
    (tuple(str(p) for p in range(3528, 3590)), (16, 17, 18, 19)),  # JCB
    (("36", "38", "39") + tuple(str(p) for p in range(300, 306)), (14, 15, 16, 17, 18, 19)),  # Diners
    (("62",), (16, 17, 18, 19)),  # UnionPay
)


def _card_issuer_ok(card_number: str) -> bool:
    digits = "".join(c for c in card_number if c.isdigit())
    return any(
        len(digits) in lengths and digits.startswith(prefixes)
        for prefixes, lengths in _CARD_SCHEMES
    )


_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def _pesel_valid(value: str) -> bool:
    """PESEL check digit and an encodable birth date (century is carried in the month)."""
    if len(value) != 11 or not value.isdigit():
        return False
    if (10 - sum(int(d) * w for d, w in zip(value, _PESEL_WEIGHTS)) % 10) % 10 != int(value[10]):
        return False
    month, day = int(value[2:4]), int(value[4:6])
    return month % 20 in range(1, 13) and month // 20 in range(5) and 1 <= day <= 31


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
    # US TIN/EIN only with a label: "12-3456789" alone is indistinguishable from
    # reference numbers. ITINs (9xx-xx-xxxx) are already caught by the SSN rule.
    ("GOVERNMENT_ID", re.compile(r"(?i:\b(?:TIN|EIN|FEIN|tax\s*(?:payer\s*)?(?:id(?:entification)?)"
                                 r"(?:\s*(?:no\.?|number|#))?)\b)[\s:#.-]*(?P<value>\d{2}-?\d{7})(?![\d-])"),
     0.95, "regex:tin"),  # above the generic phone match (0.90) on the same digits
    # "last four digits of your social security number (8827)".
    ("GOVERNMENT_ID", re.compile(r"(?i:\blast\s+(?:four|4)\s+digits\b)[^.\n]{0,60}?\(?(?P<value>\d{4})\)?(?![\d-])"),
     0.85, "regex:ssn_last4"),
    ("GOVERNMENT_ID", re.compile(r"(?i:\b(?:social\s+security(?:\s+number)?|SSN)\s*)\((?P<value>\d{4})\)"),
     0.85, "regex:ssn_last4"),
    # OCR-damaged SSN next to its label: dots or spaces for hyphens, a dropped digit
    # ("SSN 90.42.7781"). Only with the label, so plain number groups are untouched.
    ("GOVERNMENT_ID", re.compile(r"(?i:\b(?:SSN|social\s+security(?:\s+(?:no\.?|number))?)\b)[\s:#]*"
                                 r"(?P<value>\d{2,3}[\s.,-]{1,2}\d{2}[\s.,-]{1,2}\d{3,4})(?![\d])"),
     0.9, "regex:ssn_ocr"),
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
# "m" is often read as "rn", "r" or "n" at a line end: ".com" -> ".cor", ".con".
_OCR_CONFUSIONS = {"c": "[ce(]", "f": "[ft]", "o": "[o0]", "l": "[l1I|]", "i": "[il1|]", "m": "(?:m|rn|r|n)",
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
    typed_spans: set[tuple[tuple[int, int], str]] = set()

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
            # Label-confirmed identifiers (TIN, PESEL, passport ...) must not be shadowed by a
            # generic phone match on the same digits; the merger keeps the more specific type.
            if span not in seen_spans or (entity_type != "PHONE_NUMBER" and (span, entity_type) not in typed_spans):
                seen_spans.add(span)
                typed_spans.add((span, entity_type))
                entities.append(make_entity(content_block, entity_type, span[0], span[1], confidence, detector))

    # 8. OCR-damaged organisation e-mail addresses
    for match in OCR_EMAIL_PATTERN.finditer(text):
        span = match.span("value")
        if span not in seen_spans and not any(s <= span[0] and span[1] <= e for s, e in seen_spans):
            seen_spans.add(span)
            entities.append(make_entity(content_block, "EMAIL_ADDRESS", span[0], span[1], 0.8, "regex:email_ocr"))

    # 9. Unlabelled PESEL: 11 digits passing the PESEL checksum and date rules
    for match in re.finditer(r"(?<![\d-])\d{11}(?![\d-])", text):
        span = match.span()
        if _pesel_valid(match.group()) and (span, "GOVERNMENT_ID") not in typed_spans:
            seen_spans.add(span)
            typed_spans.add((span, "GOVERNMENT_ID"))
            # Above the generic phone match (0.90) on the same digits, so the merger keeps PESEL.
            entities.append(make_entity(content_block, "GOVERNMENT_ID", span[0], span[1], 0.95, "regex:pesel_checksum"))

    # 10. Credit Cards (Luhn verified, real issuer prefix and length)
    for match in CREDIT_CARD_CANDIDATE.finditer(text):
        val = match.group()
        if _luhn_checksum(val) and _card_issuer_ok(val):
            span = (match.start(), match.end())
            if span not in seen_spans:
                seen_spans.add(span)
                entities.append(
                    make_entity(content_block, "CREDIT_CARD", span[0], span[1], 1.0, "regex:credit_card")
                )

    return entities
