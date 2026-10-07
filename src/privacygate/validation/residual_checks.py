"""Gate checks that do not depend on the NER model or the primary detectors.

Re-running the same detectors on their own output cannot reveal what they
miss. These deliberately blunt checks look for PII-shaped text left in the
sanitized document; any hit blocks approval regardless of the pass count.
Detector names start with "gate:" so the pipeline can tell them apart.
"""

from __future__ import annotations

import re
from typing import Sequence

from privacygate.detection.common import make_entity
from privacygate.detection.names import NameRegistry
from privacygate.models import ContentBlock, PIIEntity

GATE_DETECTOR_PREFIX = "gate:"

# 7+ digits possibly separated by spaces, dots, hyphens or brackets, not glued
# to letters (so "ISS-2026-0112" or "2026-06-11T08" are not counted). Dates in
# YYYY-MM-DD form are excluded; "/" and "," separators never join a run.
DIGIT_RUN = re.compile(r"(?<![\w-])\+?\(?\d[\d ().-]*\d(?![\w-])")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_SHAPE = re.compile(r"[A-Za-z0-9._%+|-]+\s?@\s?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
ID_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:EMP|DIR|MER|CUST|CLI|ACC)-?\s?(?:[A-Z]{2}-)?\d{4,10}\b"),  # personnel / customer IDs
    re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b"),  # Indian PAN
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN / ITIN shape
)
PLACEHOLDER = re.compile(r"\[[A-Z_]+(?:_\d+)?\]")


def _digit_runs(text: str) -> list[tuple[int, int]]:
    spans = []
    for match in DIGIT_RUN.finditer(text):
        value = match.group().strip(" .()-")
        if sum(c.isdigit() for c in value) >= 7 and not ISO_DATE.match(value):
            spans.append(match.span())
    return spans


def independent_residual_checks(
    blocks: Sequence[ContentBlock], name_registry: NameRegistry | None = None,
) -> list[PIIEntity]:
    """Return residual PII candidates found by checks independent of the NER model."""
    residuals: list[PIIEntity] = []
    for block in blocks:
        text = block.text
        if not text.strip():
            continue
        placeholders = [m.span() for m in PLACEHOLDER.finditer(text)]

        def inside_placeholder(start: int, end: int) -> bool:
            return any(s <= start and end <= e for s, e in placeholders)

        candidates: list[tuple[str, int, int, str]] = []
        if name_registry is not None:
            candidates += [("PERSON", s, e, "name_registry") for s, e in name_registry.find(text)]
        candidates += [("PHONE_NUMBER", s, e, "digit_run") for s, e in _digit_runs(text)]
        candidates += [("EMAIL_ADDRESS", *m.span(), "email_shape") for m in EMAIL_SHAPE.finditer(text)]
        for pattern in ID_SHAPES:
            candidates += [("GOVERNMENT_ID", *m.span(), "id_shape") for m in pattern.finditer(text)]
        seen: set[tuple[int, int]] = set()
        for entity_type, start, end, check in candidates:
            if (start, end) in seen or inside_placeholder(start, end):
                continue
            seen.add((start, end))
            residuals.append(make_entity(block, entity_type, start, end, 1.0, GATE_DETECTOR_PREFIX + check))
    return residuals
