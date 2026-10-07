"""Local hybrid PII detection; no risk classification or privacy approval."""

from privacygate.detection.common import DetectionError
from privacygate.detection.custom_recognizers import detect_custom
from privacygate.detection.merger import merge_entities
from privacygate.detection.presidio_detector import detect_presidio, get_analyzer
from privacygate.detection.regex_detector import detect_regex
from privacygate.models import Document, PIIEntity

__all__ = ["detect_pii", "DetectionError"]


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
        entities = []
        for block in document.blocks:
            if not block.text.strip():
                continue
            findings = detect_presidio(block) + detect_regex(block) + detect_custom(block)
            entities.extend(merge_entities(findings))
        return entities
    except DetectionError:
        raise
    except Exception:
        raise DetectionError("Hybrid PII detection failed; no complete result is available.") from None
