"""Hybrid PII detection combining regex, custom enterprise, and Presidio NLP."""

from __future__ import annotations

from typing import Any
from privacygate.detection.custom_recognizers import (
    CustomRecognizer,
    EnterprisePattern,
    detect_custom,
)
from privacygate.detection.merger import merge_entities
from privacygate.detection.presidio_detector import PresidioDetector, detect_presidio
from privacygate.detection.regex_detector import detect_regex
from privacygate.models import ContentBlock, Document, PIIEntity

__all__ = [
    "detect_pii",
    "detect_pii_in_block",
    "detect_regex",
    "detect_custom",
    "detect_presidio",
    "merge_entities",
    "CustomRecognizer",
    "EnterprisePattern",
    "PresidioDetector",
]


def _build_source_location(block: ContentBlock) -> dict[str, int | str]:
    """Extract populated location fields into a source location dict."""
    loc: dict[str, int | str] = {}
    if block.page_number is not None:
        loc["page_number"] = block.page_number
    if block.slide_number is not None:
        loc["slide_number"] = block.slide_number
    if block.paragraph_number is not None:
        loc["paragraph_number"] = block.paragraph_number
    if block.extraction_method is not None:
        loc["extraction_method"] = block.extraction_method
    return loc


def detect_pii_in_block(block: ContentBlock) -> list[PIIEntity]:
    """Run all detection layers on a single ContentBlock and return merged entities."""
    if not block.text or not block.text.strip():
        return []

    source_loc = _build_source_location(block)

    # 1. Structured Regex Detector
    regex_entities = detect_regex(block.text, block_id=block.block_id)

    # 2. Custom Enterprise Recognizers
    custom_entities = detect_custom(block.text, block_id=block.block_id)

    # 3. Presidio NLP Analyzer
    presidio_entities = detect_presidio(block.text, block_id=block.block_id)

    raw_candidates = regex_entities + custom_entities + presidio_entities

    # Populate source location on raw candidates before merging
    for entity in raw_candidates:
        if not entity.source_location:
            entity.source_location = dict(source_loc)

    # 4. Deterministic Merger
    return merge_entities(raw_candidates)


def detect_pii(document: Document) -> list[PIIEntity]:
    """Run hybrid PII detection across all blocks in a Document and return merged PIIEntity list."""
    if not document.blocks:
        return []

    all_entities: list[PIIEntity] = []
    for block in document.blocks:
        block_entities = detect_pii_in_block(block)
        all_entities.extend(block_entities)

    return all_entities
