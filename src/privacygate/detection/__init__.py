"""Local hybrid PII detection combining regex, enterprise rules, and Presidio NLP."""

from __future__ import annotations

from privacygate.detection.common import DetectionError, make_entity, validate_entity
from privacygate.detection.custom_recognizers import (
    CustomRecognizer,
    EnterprisePattern,
    detect_custom,
)
from privacygate.detection.merger import merge_entities
from privacygate.detection.presidio_detector import (
    PresidioDetector,
    detect_presidio,
    get_analyzer,
)
from privacygate.detection.regex_detector import detect_regex
from privacygate.models import ContentBlock, Document, PIIEntity

__all__ = [
    "detect_pii",
    "detect_pii_in_block",
    "detect_presidio",
    "detect_regex",
    "detect_custom",
    "merge_entities",
    "get_analyzer",
    "DetectionError",
    "CustomRecognizer",
    "EnterprisePattern",
    "PresidioDetector",
]


def detect_pii_in_block(block: ContentBlock) -> list[PIIEntity]:
    """Analyze a single block using all detection mechanisms and merge results."""
    if not block.text or not block.text.strip():
        return []
    findings = detect_presidio(block) + detect_regex(block) + detect_custom(block)
    return merge_entities(findings)


def detect_pii(document: Document) -> list[PIIEntity]:
    """Return entities in document block order, then increasing start offset.

    Offsets index the original block text, never a concatenated document.
    A failure in any source aborts detection instead of returning partial results.
    """
    try:
        block_ids = [block.block_id for block in document.blocks]
        if any(not block_id for block_id in block_ids) or len(set(block_ids)) != len(block_ids):
            raise DetectionError("Detection requires nonempty, unique content block IDs.")

        get_analyzer()  # Missing NLP must fail even on an empty document.

        entities: list[PIIEntity] = []
        for block in document.blocks:
            if not block.text.strip():
                continue
            findings = detect_presidio(block) + detect_regex(block) + detect_custom(block)
            entities.extend(merge_entities(findings))
        return entities
    except DetectionError:
        raise
    except Exception as exc:
        raise DetectionError(f"Hybrid PII detection failed: {type(exc).__name__}") from None
