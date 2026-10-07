"""Cross-file view of pseudonym tokens for one batch, kept in memory only.

The index lists, for every token issued in a batch, the files and locations
where it replaced PII ("PERSON_007: policy p.1, p.35; org pack slide 8"), and
links a person's e-mail tokens to that person's token. It holds tokens,
entity types and structural locations only, never the original values, and
must not be written to audit JSON or logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Sequence

from privacygate.detection.names import NameRegistry
from privacygate.models import ContentBlock, Document, PIIEntity
from privacygate.redaction import PseudonymSession
from privacygate.redaction.redactor import RedactionRecord, get_placeholder


@dataclass
class TokenSummary:
    token: str
    entity_type: str
    occurrences: list[tuple[str, str]] = field(default_factory=list)  # (file, location), ordered, unique
    linked_person: str | None = None  # for e-mail tokens
    linked_emails: list[str] = field(default_factory=list)  # for person tokens

    @property
    def files(self) -> list[str]:
        return list(dict.fromkeys(file for file, _ in self.occurrences))

    def locations_text(self) -> str:
        """'policy.pdf p.1, p.35; pack.pptx slide 8'."""
        return "; ".join(
            f"{name} " + ", ".join(location for file, location in self.occurrences if file == name)
            for name in self.files
        )


@dataclass
class BatchFile:
    """What the index needs from one processed file (all in memory)."""

    document: Document
    entities: Sequence[PIIEntity]  # first-pass detections on the original text
    redactions: Sequence[RedactionRecord]  # every applied replacement, all passes


def describe_location(block: ContentBlock) -> str:
    """Short human location for a block: p.3, slide 8, para 12, table 2, header, image image7.png."""
    image = block.metadata.get("image_name")
    kind = block.metadata.get("kind")
    if image:
        where = f"image {image}"
    elif kind in ("header", "footer", "text_box"):
        where = kind.replace("_", " ")
    elif kind == "notes":
        where = "notes"
    elif block.page_number is not None:
        return f"p.{block.page_number}"
    elif kind == "table_cell" and block.metadata.get("table_number") is not None and block.slide_number is None:
        return f"table {block.metadata['table_number']}"
    elif block.paragraph_number is not None:
        return f"para {block.paragraph_number}"
    else:
        where = ""
    if block.slide_number is not None:
        return f"slide {block.slide_number}" + (f" {where}" if where else "")
    return where or "body"


def _email_person(local_part: str, registry: NameRegistry) -> int | None:
    """Registry index of the single person an e-mail local part names (m.achebe, mary.achebe)."""
    parts = [part for part in re.split(r"[._-]", local_part) if part.isalpha()]
    if len(parts) < 2:
        return None
    surname, initial = parts[-1].casefold(), parts[0][0].casefold()
    matches = [
        index for index, person in enumerate(registry.people)
        if person.last.replace("-", "").casefold() == surname
        and ((person.first or person.initial or initial)[0].casefold() == initial)
    ]
    return matches[0] if len(matches) == 1 else None


def build_cross_file_index(
    files: Sequence[BatchFile], session: PseudonymSession, registry: NameRegistry,
) -> dict[str, TokenSummary]:
    """Token -> where it occurs across the batch, with e-mail tokens linked to their person.

    Calling session.placeholder_for() on a first-pass value returns the token
    that value already received; it issues nothing new because every
    first-pass entity was redacted with the same session.
    """
    summaries: dict[str, TokenSummary] = {}
    for item in files:
        blocks = {block.block_id: block for block in item.document.blocks}
        for record in item.redactions:
            block = blocks.get(record.block_id)
            summary = summaries.setdefault(
                record.placeholder, TokenSummary(record.placeholder, get_placeholder(record.entity_type)[1:-1]),
            )
            entry = (item.document.filename, describe_location(block) if block else "unknown")
            if entry not in summary.occurrences:
                summary.occurrences.append(entry)

    person_tokens: dict[int, str] = {}
    email_values: list[tuple[str, str]] = []
    for item in files:
        texts = {block.block_id: block.text for block in item.document.blocks}
        for entity in item.entities:
            value = texts.get(entity.block_id, "")[entity.start:entity.end]
            canonical = get_placeholder(entity.entity_type)[1:-1]
            if canonical == "PERSON":
                index = registry.resolve_person(value.strip())
                if index is not None:
                    person_tokens.setdefault(index, session.placeholder_for(entity.entity_type, value))
            elif canonical == "EMAIL" and "@" in value:
                email_values.append((session.placeholder_for(entity.entity_type, value), value))

    for email_token, value in email_values:
        index = _email_person(value.strip().rsplit("@", 1)[0], registry)
        person_token = person_tokens.get(index) if index is not None else None
        if person_token and email_token in summaries and person_token in summaries:
            summaries[email_token].linked_person = person_token
            if email_token not in summaries[person_token].linked_emails:
                summaries[person_token].linked_emails.append(email_token)
    return summaries
