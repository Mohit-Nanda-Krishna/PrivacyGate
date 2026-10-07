"""Semantic PII redaction replacing detected entities with structured placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
from privacygate.models import ContentBlock, Document, PIIEntity


@dataclass
class RedactionRecord:
    """Audit-safe record of an applied redaction, containing no raw PII."""

    block_id: str
    entity_type: str
    placeholder: str
    source_location: dict[str, int | str] = field(default_factory=dict)


def get_placeholder(entity_type: str) -> str:
    """Return the standardized semantic placeholder for an entity type."""
    clean_type = entity_type.strip().upper()
    return f"[{clean_type}]"


def redact_text(text: str, entities: Sequence[PIIEntity]) -> tuple[str, list[RedactionRecord]]:
    """Redact entities from a text string in reverse offset order to maintain index integrity."""
    if not text or not entities:
        return text, []

    # Sort entities in descending order of start offset
    # In case of equal start, sort by descending end
    sorted_entities = sorted(entities, key=lambda e: (e.start, e.end), reverse=True)

    sanitized = text
    records: list[RedactionRecord] = []

    for entity in sorted_entities:
        # Bounds check
        if entity.start < 0 or entity.end > len(text) or entity.start >= entity.end:
            continue

        placeholder = get_placeholder(entity.entity_type)
        # Splice sanitized string
        sanitized = sanitized[:entity.start] + placeholder + sanitized[entity.end:]

        records.append(
            RedactionRecord(
                block_id=entity.block_id,
                entity_type=entity.entity_type,
                placeholder=placeholder,
                source_location=dict(entity.source_location),
            )
        )

    # Return sanitized text and chronological records
    records.reverse()
    return sanitized, records


def redact_document(
    document: Document,
    entities: Sequence[PIIEntity],
) -> tuple[Document, list[RedactionRecord]]:
    """Generate a sanitized Document replacing all detected PII with semantic placeholders.

    The original document is not mutated. All structural metadata and coordinates are preserved.
    """
    # Group entities by block_id
    by_block: dict[str, list[PIIEntity]] = {}
    for entity in entities:
        by_block.setdefault(entity.block_id, []).append(entity)

    sanitized_blocks: list[ContentBlock] = []
    all_records: list[RedactionRecord] = []

    for block in document.blocks:
        block_entities = by_block.get(block.block_id, [])
        if block_entities:
            clean_text, records = redact_text(block.text, block_entities)
            all_records.extend(records)
        else:
            clean_text = block.text

        sanitized_blocks.append(
            ContentBlock(
                block_id=block.block_id,
                text=clean_text,
                page_number=block.page_number,
                slide_number=block.slide_number,
                paragraph_number=block.paragraph_number,
                extraction_method=block.extraction_method,
                metadata=dict(block.metadata),
            )
        )

    sanitized_metadata = dict(document.metadata)
    sanitized_metadata["redacted"] = True
    sanitized_metadata["redaction_count"] = len(all_records)

    sanitized_doc = Document(
        document_id=f"{document.document_id}_sanitized",
        filename=document.filename,
        file_type=document.file_type,
        metadata=sanitized_metadata,
        blocks=sanitized_blocks,
    )

    return sanitized_doc, all_records
