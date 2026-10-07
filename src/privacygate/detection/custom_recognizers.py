"""Centralized labelled enterprise rules; spans include only the identifier."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from privacygate.detection.common import make_entity
from privacygate.models import ContentBlock, PIIEntity

# Label plus colon, equals, or hash is required per PRD Section 13 and project architecture
CUSTOM_RULES: tuple[tuple[str, str, str], ...] = (
    ("EMPLOYEE_ID", r"employee[ \t]+(?:id|no\.?|number)", r"(?:EMP-\d{4,10}|\d{5,10})"),
    ("CLIENT_ID", r"client[ \t]+id", r"(?:(?:CLI|C)-\d{4,10}|\d{5,10})"),
    ("CUSTOMER_ID", r"customer[ \t]+id", r"(?:CUST-\d{4,10}|\d{5,10})"),
    ("PORTFOLIO_ID", r"portfolio[ \t]+id", r"(?:(?:PF|AX)-\d{4,10}|\d{5,10})"),
    ("ACCOUNT_NUMBER", r"account(?:[ \t]+(?:no\.?|number|#))?", r"(?:ACC-\d{4,12}|\d{5,12})"),
)

# Personnel identifiers that are distinctive enough to need no label. OCR often
# turns I into 1/l/| and 0 into O, so those swaps are tolerated.
_OCR_DIGIT = "[0-9OoIl|]"
# Alphanumeric boundaries rather than \b: OCR leaves "EMP-37655_" where \b fails.
_START, _END = "(?<![0-9A-Za-z])", "(?![0-9A-Za-z])"
STANDALONE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Employee IDs: EMP-38104, EMP100245, OCR "EMF-38104".
    ("EMPLOYEE_ID", re.compile(rf"{_START}E[MW][PF]-?\s?(?=(?:{_OCR_DIGIT}*\d){{3}}){_OCR_DIGIT}{{5,8}}{_END}")),
    # Director IDs: DIR-0042, OCR "D1R-0042".
    ("EMPLOYEE_ID", re.compile(rf"{_START}D[I1l|]R-(?=(?:{_OCR_DIGIT}*\d){{2}}){_OCR_DIGIT}{{4}}{_END}")),
    # Vendor personnel IDs: MER-IN-4471, MER-PL-1187 (may wrap after "MER-").
    ("EMPLOYEE_ID", re.compile(rf"{_START}MER-\s*[A-Z]{{2}}-\d{{4}}{_END}")),
)

CUSTOM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        entity_type,
        re.compile(
            rf"\b{label}[ \t]*(?::|=|#)[ \t]*(?P<value>{value})(?![\w-])",
            re.IGNORECASE,
        ),
    )
    for entity_type, label, value in CUSTOM_RULES
)


@dataclass(frozen=True)
class EnterprisePattern:
    """A configurable enterprise-specific pattern rule."""

    name: str
    entity_type: str
    pattern: re.Pattern[str]
    confidence: float = 0.95
    capture_group: int = 0


class CustomRecognizer:
    """Configurable custom enterprise recognizer."""

    def __init__(self, patterns: Sequence[EnterprisePattern] | None = None) -> None:
        self.dynamic_patterns = list(patterns or [])

    def add_pattern(self, pattern: EnterprisePattern) -> None:
        self.dynamic_patterns.append(pattern)

    def detect(self, block: ContentBlock | str, block_id: str = "") -> list[PIIEntity]:
        return detect_custom(block, block_id=block_id, extra_patterns=self.dynamic_patterns)


_DEFAULT_RECOGNIZER = CustomRecognizer()


def detect_custom(
    block: ContentBlock | str,
    block_id: str = "",
    extra_patterns: Sequence[EnterprisePattern] | None = None,
) -> list[PIIEntity]:
    """Scan block for enterprise PII rules."""
    if isinstance(block, str):
        content_block = ContentBlock(block_id=block_id or "block", text=block)
    else:
        content_block = block

    if not content_block.text or not content_block.text.strip():
        return []

    entities: list[PIIEntity] = []
    seen_spans: set[tuple[int, int]] = set()

    # 1. Labelled enterprise rules (captures value only)
    for entity_type, pattern in CUSTOM_PATTERNS:
        for match in pattern.finditer(content_block.text):
            span = match.span("value")
            if span not in seen_spans:
                seen_spans.add(span)
                entities.append(
                    make_entity(
                        content_block,
                        entity_type,
                        span[0],
                        span[1],
                        0.95,
                        "custom:" + entity_type.lower(),
                    )
                )

    # 2. Unlabelled personnel identifiers
    for entity_type, pattern in STANDALONE_RULES:
        for match in pattern.finditer(content_block.text):
            span = match.span()
            if span not in seen_spans:
                seen_spans.add(span)
                entities.append(
                    make_entity(content_block, entity_type, span[0], span[1], 0.9, "custom:personnel_id")
                )

    # 3. Dynamic user-added patterns (if any)
    if extra_patterns:
        for rule in extra_patterns:
            for match in rule.pattern.finditer(content_block.text):
                if rule.capture_group > 0 and len(match.groups()) >= rule.capture_group:
                    start = match.start(rule.capture_group)
                    end = match.end(rule.capture_group)
                else:
                    start = match.start()
                    end = match.end()
                span = (start, end)
                if span not in seen_spans and end > start:
                    seen_spans.add(span)
                    entities.append(
                        make_entity(
                            content_block,
                            rule.entity_type,
                            start,
                            end,
                            rule.confidence,
                            "custom:" + rule.entity_type.lower(),
                        )
                    )

    return sorted(entities, key=lambda e: (e.start, e.end))
