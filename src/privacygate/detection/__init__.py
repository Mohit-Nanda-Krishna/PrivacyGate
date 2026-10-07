"""Local hybrid PII detection combining regex, enterprise rules, and Presidio NLP."""

from __future__ import annotations

import re

from privacygate.detection.common import DetectionError, make_entity, validate_entity
from privacygate.detection.custom_recognizers import (
    CustomRecognizer,
    EnterprisePattern,
    detect_custom,
)
from privacygate.detection.merger import merge_entities
from privacygate.detection.names import (
    DEFAULT_ALLOWLIST,
    NAME_WITH_INITIAL,
    ROLE_LABEL,
    NameRegistry,
    build_name_registry,
    clean_ner_entity,
    role_context_names,
    sweep_names,
)
from privacygate.detection.presidio_detector import (
    PresidioDetector,
    detect_presidio,
    get_analyzer,
)
from privacygate.detection.regex_detector import detect_regex
from privacygate.models import ContentBlock, Document, PIIEntity

__all__ = [
    "detect_pii",
    "detect_pii_with_registry",
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
    "NameRegistry",
    "DEFAULT_ALLOWLIST",
]

_PHONE_HEADER = re.compile(r"\b(?:mobile|phone|tel|telephone|cell|direct line|contact)\b", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"(?<![\w])\+?\(?\d[\d ().-]{5,}\d(?![\w])")
# A country code left at the end of a line whose number continues on the next line.
_TRAILING_COUNTRY_CODE = re.compile(r"(?<![\w+])\+\d{1,3}(?:[ \t]\(?\d{1,4}\)?)?[ \t]*$")
_IDENTIFIER_TYPES = frozenset({
    "EMAIL_ADDRESS", "PHONE_NUMBER", "EMPLOYEE_ID", "GOVERNMENT_ID", "US_SSN", "ACCOUNT_NUMBER",
})


def _stitched_country_codes(blocks: list[ContentBlock], findings: dict[str, list[PIIEntity]]) -> list[PIIEntity]:
    """Mark "+1" at a line end as phone when the next line on the page starts with a phone."""
    entities = []
    for block, following in zip(blocks, blocks[1:]):
        if block.page_number != following.page_number or block.slide_number != following.slide_number:
            continue
        match = _TRAILING_COUNTRY_CODE.search(block.text)
        if match and any(e.entity_type == "PHONE_NUMBER" and e.start <= 2 for e in findings[following.block_id]):
            entities.append(make_entity(block, "PHONE_NUMBER", match.start(), match.end() - (
                len(match.group()) - len(match.group().rstrip())), 0.8, "context:split_phone"))
    return entities


def detect_pii_in_block(block: ContentBlock) -> list[PIIEntity]:
    """Analyze a single block using all detection mechanisms and merge results."""
    if not block.text or not block.text.strip():
        return []
    findings = detect_presidio(block) + detect_regex(block) + detect_custom(block)
    return merge_entities(findings)


def _table_key(block: ContentBlock) -> tuple | None:
    meta = block.metadata
    if meta.get("kind") != "table_cell" or "row_number" not in meta or "column_number" not in meta:
        return None
    return (block.page_number, block.slide_number, meta.get("table_number"), meta.get("shape_id"))


def _header_phone_entities(blocks: list[ContentBlock]) -> list[PIIEntity]:
    """Number-shaped cells under a Mobile/Phone column header are phone numbers."""
    headers = {}
    for block in blocks:
        key = _table_key(block)
        if key is not None and block.metadata["row_number"] == 1:
            headers[(key, block.metadata["column_number"])] = block.text
    entities = []
    for block in blocks:
        key = _table_key(block)
        if key is None or block.metadata["row_number"] == 1:
            continue
        if not _PHONE_HEADER.search(headers.get((key, block.metadata["column_number"]), "")):
            continue
        for match in _DIGIT_RUN.finditer(block.text):
            if sum(character.isdigit() for character in match.group()) >= 7:
                entities.append(make_entity(block, "PHONE_NUMBER", *match.span(), 0.85, "context:table_header"))
    return entities


_INLINE_ROLE = re.compile(
    r"\b(?:created by|prepared by|led by|attested by|signed by|reviewed by|owner|author\(s\)|authors?|"
    r"client contact|contact)\s*[:\-]?\s*(?=[A-Z])",
    re.IGNORECASE,
)


def _role_context(blocks: list[ContentBlock], allowlist: frozenset[str]) -> tuple[set[str], list[PIIEntity]]:
    """Blocks that hold people, and the names in them.

    A table cell is a role context when its column header (row 1) or its row
    label (column 1 of the same row) is a role word such as "Users",
    "Author(s)" or "Created by". Elsewhere only the text right after an inline
    label ("Created by Zelda Quark", "Owner: ...") counts.
    """
    cells = {}
    for block in blocks:
        key = _table_key(block)
        if key is not None:
            cells[(key, block.metadata["row_number"], block.metadata["column_number"])] = block.text
    role_blocks: set[str] = set()
    entities: list[PIIEntity] = []
    for block in blocks:
        key = _table_key(block)
        if key is not None:
            row, column = block.metadata["row_number"], block.metadata["column_number"]
            header = cells.get((key, 1, column), "") if row > 1 else ""
            label = cells.get((key, row, 1), "") if column > 1 else ""
            # Row labels are short ("Author(s)", "Peer Reviewer"); long cells are content, not labels.
            short_label = label.strip().rstrip(":")
            if ROLE_LABEL.search(header) or (len(short_label) <= 30 and ROLE_LABEL.search(short_label)):
                found = role_context_names(block, allowlist)
                if found:
                    role_blocks.add(block.block_id)
                    entities.extend(found)
            continue
        for label in _INLINE_ROLE.finditer(block.text):
            tail = ContentBlock(block.block_id, block.text[:label.end() + 60], page_number=block.page_number,
                                slide_number=block.slide_number, paragraph_number=block.paragraph_number,
                                extraction_method=block.extraction_method, metadata=block.metadata)
            for entity in role_context_names(tail, allowlist):
                if entity.start == label.end():
                    role_blocks.add(block.block_id)
                    entities.append(make_entity(block, "PERSON", entity.start, entity.end, 0.8, entity.detector))
    return role_blocks, entities


def detect_pii_with_registry(
    document: Document, allowlist: frozenset[str] | set[str] | None = None,
) -> tuple[list[PIIEntity], NameRegistry]:
    """Detect PII and return the document's name registry alongside the entities.

    1. Presidio, regex and enterprise rules per block.
    2. NER PERSON/LOCATION spans are trimmed/filtered (allowlist, name shape).
    3. People named with two or more tokens, e-mail local parts and honorifics
       form a per-document registry; single-token NER names survive only if
       the registry confirms them.
    4. Every block is swept for registered names and their variants.
    """
    allowed = frozenset(DEFAULT_ALLOWLIST | {word.lower() for word in (allowlist or ())})
    try:
        block_ids = [block.block_id for block in document.blocks]
        if any(not block_id for block_id in block_ids) or len(set(block_ids)) != len(block_ids):
            raise DetectionError("Detection requires nonempty, unique content block IDs.")

        get_analyzer()  # Missing NLP must fail even on an empty document.

        blocks = [block for block in document.blocks if block.text.strip()]
        findings: dict[str, list[PIIEntity]] = {block.block_id: [] for block in blocks}
        for block in blocks:
            for entity in detect_presidio(block):
                findings[block.block_id].extend(clean_ner_entity(block, entity, allowed))
            findings[block.block_id].extend(detect_regex(block) + detect_custom(block))
            for match in NAME_WITH_INITIAL.finditer(block.text):
                candidate = make_entity(block, "PERSON", *match.span(), 0.8, "pattern:name_with_initial")
                findings[block.block_id].extend(clean_ner_entity(block, candidate, allowed))
        role_blocks, role_names = _role_context(blocks, allowed)
        for entity in _header_phone_entities(blocks) + _stitched_country_codes(blocks, findings) + role_names:
            findings[entity.block_id].append(entity)

        texts = {block.block_id: block.text for block in blocks}

        def is_single_token(entity: PIIEntity) -> bool:
            return len(texts[entity.block_id][entity.start:entity.end].split()) == 1

        person_spans = [
            (entity.block_id, entity.start, entity.end)
            for found in findings.values() for entity in found
            if entity.entity_type == "PERSON" and not is_single_token(entity)
        ]
        identifier_blocks = [
            block_id for block_id, found in findings.items()
            if any(entity.entity_type in _IDENTIFIER_TYPES for entity in found)
        ] + sorted(role_blocks)
        registry = build_name_registry(blocks, person_spans, allowed, identifier_blocks)
        for block_id, found in findings.items():
            findings[block_id] = [
                entity for entity in found
                if entity.entity_type != "PERSON" or not entity.detector.startswith("presidio")
                or not is_single_token(entity)
                or registry.find(texts[block_id][entity.start:entity.end])
            ]
        for entity in sweep_names(blocks, registry):
            findings[entity.block_id].append(entity)

        entities: list[PIIEntity] = []
        for block in blocks:
            entities.extend(merge_entities(findings[block.block_id]))
        return entities, registry
    except DetectionError:
        raise
    except Exception as exc:
        raise DetectionError(f"Hybrid PII detection failed: {type(exc).__name__}") from None


def detect_pii(document: Document, allowlist: frozenset[str] | set[str] | None = None) -> list[PIIEntity]:
    """Return entities in document block order, then increasing start offset.

    Offsets index the original block text, never a concatenated document.
    A failure in any source aborts detection instead of returning partial results.
    """
    return detect_pii_with_registry(document, allowlist)[0]
