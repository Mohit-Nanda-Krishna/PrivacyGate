"""Complete detections that OCR left partly outside their span.

A value is only safe when every character of it is redacted. In OCR'd text the
detectors often find most of a value and miss a piece next to it: an initial on
its own line, a country code that wrapped onto the line above, a misread first
name, a stray digit glued to a phone number, the same value read again by page
OCR. These rules add the missing pieces. They are general: each one starts
from an existing detection (or from what the existing detectors accept for a
joined value) and only extends it, so they cannot introduce a new kind of PII.

All rules apply to OCR'd blocks only ("ocr", "figure_ocr", "embedded_image_ocr").
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Sequence

from privacygate.detection.common import make_entity
from privacygate.detection.custom_recognizers import detect_custom
from privacygate.detection.names import NameRegistry
from privacygate.detection.ocr_text import OCR_METHODS, _container, _words
from privacygate.detection.regex_detector import detect_regex
from privacygate.models import ContentBlock, PIIEntity

WRAP_LINES = 6  # how far below a dangling prefix its continuation may be (OCR lines)
FIRST_NAME_SIMILARITY = 0.8
SURNAME_SIMILARITY = 0.85
ID_TYPES = frozenset({"EMPLOYEE_ID", "CLIENT_ID", "CUSTOMER_ID", "PORTFOLIO_ID", "ACCOUNT_NUMBER", "GOVERNMENT_ID"})

_INITIAL_TOKEN = re.compile(r"^\(?(?:[A-Z][.,]?|(?:[A-Z]\.){2,3})$")


def _only_initials(text: str) -> bool:
    """"M", "D.", "A. P.", "A.P." - not words such as "HR" or "To"."""
    tokens = text.split()
    return 0 < len(tokens) <= 3 and all(_INITIAL_TOKEN.match(token) for token in tokens)


_TRAILING_INITIALS = re.compile(r"(?<![\w.])(?:[A-Z][.,][ \t]?){1,3}$")
# "+44 20", "+1 (212)": country code and an optional area code.
_PHONE_HEAD = re.compile(r"(?<![\w+])(?P<country>\+\d{1,3})(?:[ \t]+(?P<area>\(\d{1,4}\)|\d{1,4}))?(?![\d])")
_ID_HEAD = re.compile(r"(?<![\w-])[A-Z]{2,5}-(?=[\s)]|$)")
_ID_TAIL = re.compile(r"(?<![\w-])[A-Z0-9]{1,5}-\d{3,}(?![\w-])")
_DIGITS_AT_START = re.compile(r"^[ \t(]*(\d[\d \t-]{2,}\d)(?![\w])")
_EMAIL_INITIAL = re.compile(r"(?<![\w.])[a-z][ \t]$")
_TRAILING_PUNCTUATION = ",.;:)]}'\""


def _ocr(block: ContentBlock) -> bool:
    return block.extraction_method in OCR_METHODS


def _by_block(entities: Sequence[PIIEntity]) -> dict[str, list[PIIEntity]]:
    grouped: dict[str, list[PIIEntity]] = {}
    for entity in entities:
        grouped.setdefault(entity.block_id, []).append(entity)
    return grouped


def _lines(blocks: Sequence[ContentBlock]) -> list[list[ContentBlock]]:
    """OCR blocks grouped by image / figure / page, in reading order."""
    groups: dict[tuple, list[ContentBlock]] = {}
    for block in blocks:
        if _ocr(block):
            groups.setdefault(_container(block), []).append(block)
    return list(groups.values())


def attached_characters(blocks: Sequence[ContentBlock], entities: Sequence[PIIEntity]) -> list[PIIEntity]:
    """Extend a detection over characters glued to it: a stray digit ("5555 0121" found as
    "555 0121"), OCR junk on a name ("Bnghtwe'!l"), and an initial in front of an e-mail
    whose dot OCR read as a space ("t lindavist@...")."""
    texts = {block.block_id: block for block in blocks if _ocr(block)}
    found = []
    for entity in entities:
        block = texts.get(entity.block_id)
        if block is None:
            continue
        text = block.text
        start, end = entity.start, entity.end
        while start > 0 and text[start - 1].isalnum():
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
        while end > entity.end and text[end - 1] in _TRAILING_PUNCTUATION:
            end -= 1
        if entity.entity_type == "EMAIL_ADDRESS" and _EMAIL_INITIAL.search(text[:start]):
            start -= 2
        if (start, end) != (entity.start, entity.end):
            found.append(make_entity(block, entity.entity_type, start, end, entity.confidence, entity.detector))
    return found


def _registered(person_last: str, token: str) -> bool:
    return SequenceMatcher(None, person_last, token, autojunk=False).ratio() >= SURNAME_SIMILARITY


def wrapped_initials(
    blocks: Sequence[ContentBlock], entities: Sequence[PIIEntity], registry: NameRegistry,
) -> list[PIIEntity]:
    """Initials separated from their surname by a line break.

    - A line that is only initials ("M", "D") before a line that starts with a
      detected name, or with a word within OCR distance of a registered
      surname ("zewczyk" for Szewczyk): both are PERSON.
    - A line ending in dotted initials ("... (A. P.") before a line that starts
      with a detected name ("Brightwell)"): the initials are PERSON.
    """
    people = {block_id: [e for e in found if e.entity_type == "PERSON"]
              for block_id, found in _by_block(entities).items()}
    surnames = {re.sub(r"[^a-z]", "", person.last.lower()) for person in registry.people}
    found = []
    for lines in _lines(blocks):
        for line, following in zip(lines, lines[1:]):
            head = following.text.lstrip(" (")
            offset = len(following.text) - len(head)
            starts_with_name = any(e.start <= offset + 1 for e in people.get(following.block_id, []))
            first = re.match(r"[A-Za-z][A-Za-z'’-]+", head)
            damaged_surname = bool(first) and any(
                _registered(surname, re.sub(r"[^a-z]", "", first.group().lower())) for surname in surnames
                if len(surname) >= 5)
            if _only_initials(line.text) and (starts_with_name or damaged_surname):
                found.append(make_entity(line, "PERSON", len(line.text) - len(line.text.lstrip()),
                                         len(line.text.rstrip()), 0.8, "name_sweep_ocr"))
                if damaged_surname and not starts_with_name:
                    found.append(make_entity(following, "PERSON", offset + first.start(), offset + first.end(),
                                             0.8, "name_sweep_ocr"))
                continue
            trailing = _TRAILING_INITIALS.search(line.text.rstrip())
            if trailing and starts_with_name:
                found.append(make_entity(line, "PERSON", trailing.start(), trailing.end(), 0.8, "name_sweep_ocr"))
    return found


def registered_first_names(
    blocks: Sequence[ContentBlock], entities: Sequence[PIIEntity], registry: NameRegistry,
) -> list[PIIEntity]:
    """A misread first name, or one with the middle initial glued on ("lfeoma", "CalebA."),
    in front of a detected surname of a registered person."""
    texts = {block.block_id: block for block in blocks if _ocr(block)}
    by_last: dict[str, list[str]] = {}
    for person in registry.people:
        if person.first:
            by_last.setdefault(person.last.replace("-", "").lower(), []).append(person.first.lower())
    found = []
    for entity in entities:
        block = texts.get(entity.block_id)
        if block is None or entity.entity_type != "PERSON":
            continue
        span = block.text[entity.start:entity.end]
        last = re.findall(r"[A-Za-z][A-Za-z'’-]+", span)
        previous = re.search(r"(\S+)[ \t]+$", block.text[:entity.start])
        if not last or not previous:
            continue
        candidate = re.sub(r"[A-Z]\.$", "", previous.group(1)).lower()  # "CalebA." -> "caleb"
        firsts = by_last.get(last[-1].replace("-", "").lower(), [])
        if candidate.isalpha() and any(
                SequenceMatcher(None, candidate, first, autojunk=False).ratio() >= FIRST_NAME_SIMILARITY
                for first in firsts):
            found.append(make_entity(block, "PERSON", previous.start(1), entity.end, entity.confidence,
                                     "name_sweep_ocr"))
    return found


def _joined_type(text: str, wanted: frozenset[str]) -> str | None:
    """The type the regular detectors give the whole of text, if any."""
    probe = ContentBlock("probe", text)
    for entity in detect_regex(probe) + detect_custom(probe):
        if entity.entity_type in wanted and entity.start <= 1 and entity.end >= len(text) - 1:
            return entity.entity_type
    return None


PHONE = frozenset({"PHONE_NUMBER"})


def wrapped_prefixes(blocks: Sequence[ContentBlock], entities: Sequence[PIIEntity]) -> list[PIIEntity]:
    """The other piece of a value that wrapped inside a table cell.

    OCR reads a table row across all its columns, so a wrapped value's pieces
    are separated by other cells' text. A piece is added only if the regular
    detectors accept the joined value as one phone number or identifier:

    - "+1 (212)" / "+44 20" with no detection, followed within WRAP_LINES lines
      by a phone detection without a country code ("555-0136"). A bare area
      code is kept only if the continuation has none of its own: "+1 14 Mar"
      before "(212) 555-0108" is "+1" and a date.
    - A detected phone ("+91 98860") whose remaining digits start one of the
      next lines ("55107").
    - "MER-" before a later line containing "PH-2214" (identifier pieces).
    """
    grouped = _by_block(entities)
    found = []
    for lines in _lines(blocks):
        for index, line in enumerate(lines):
            covered = grouped.get(line.block_id, [])
            later = lines[index + 1:index + 1 + WRAP_LINES]

            def free(start: int, end: int) -> bool:
                return not any(e.start < end and e.end > start for e in covered)

            for head in _PHONE_HEAD.finditer(line.text):
                if not free(head.start(), head.end("country")):
                    continue
                for following in later:
                    tails = [e for e in grouped.get(following.block_id, [])
                             if e.entity_type == "PHONE_NUMBER" and not following.text[e.start:e.end].startswith("+")]
                    if not tails:
                        continue
                    tail = following.text[tails[0].start:tails[0].end]
                    bare_area = head.group("area") and not head.group("area").startswith("(")
                    end = head.end("country") if bare_area and tail.lstrip().startswith("(") else head.end()
                    if _joined_type(f"{line.text[head.start():end]} {tail}", PHONE):
                        found.append(make_entity(line, "PHONE_NUMBER", head.start(), end, 0.8, "context:wrapped_value"))
                    break
            for phone in (e for e in covered if e.entity_type == "PHONE_NUMBER"):
                rest = line.text[phone.end:]
                if re.match(r"[ \t]*\d", rest):
                    continue  # the number goes on on this line
                for following in later[:3]:
                    digits = _DIGITS_AT_START.match(following.text)
                    if digits and _joined_type(f"{line.text[phone.start:phone.end]} {digits.group(1)}", PHONE):
                        found.append(make_entity(following, "PHONE_NUMBER", *digits.span(1), 0.8,
                                                 "context:wrapped_value"))
                        break
            for head in _ID_HEAD.finditer(line.text):
                if not free(*head.span()):
                    continue
                for following in later[:3]:
                    tail = next((t for t in _ID_TAIL.finditer(following.text)
                                 if _joined_type(head.group() + t.group(), ID_TYPES)), None)
                    if tail:
                        entity_type = _joined_type(head.group() + tail.group(), ID_TYPES)
                        found.append(make_entity(line, entity_type, *head.span(), 0.8, "context:wrapped_value"))
                        found.append(make_entity(following, entity_type, *tail.span(), 0.8, "context:wrapped_value"))
                        break
    return found


def _overlap(a: list[int], b: list[int]) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return width * height / max(1, smaller)


WORD_SIMILARITY = 0.6


def _letters(text: str) -> str:
    return "".join(character.lower() for character in text if character.isalnum())


def figure_duplicates(blocks: Sequence[ContentBlock], entities: Sequence[PIIEntity]) -> list[PIIEntity]:
    """Page-OCR words printed on the same pixels as a detected figure-OCR word get its type.

    A figure is read twice: by page OCR and by figure OCR. When only the figure
    reading is detected ("28 Februa" / "1979" under a date-of-birth label), the
    page reading of the same pixels ("28 February 1979") must be redacted too.
    A page word qualifies when it overlaps a detected figure word and reads
    similarly; consecutive qualifying words on one line become one span.
    """
    grouped = _by_block(entities)
    detected_boxes: dict[int | None, list[tuple[list[int], str, str]]] = {}
    for block in blocks:
        if block.extraction_method != "figure_ocr":
            continue
        words = _words(block)
        for entity in grouped.get(block.block_id, []):
            for start, end, box in words or []:
                if start < entity.end and end > entity.start:
                    detected_boxes.setdefault(block.page_number, []).append(
                        (box, entity.entity_type, _letters(block.text[start:end])))

    def same_word(word: str, box: list[int], page: int | None) -> str | None:
        # Same pixels and a similar reading: OCR noise over a figure is not the value.
        letters = _letters(word)
        for other, kind, other_letters in detected_boxes[page]:
            if (_overlap(box, other) >= 0.5 and letters
                    and SequenceMatcher(None, letters, other_letters, autojunk=False).ratio() >= WORD_SIMILARITY):
                return kind
        return None

    found = []
    for block in blocks:
        if block.extraction_method != "ocr" or block.page_number not in detected_boxes:
            continue
        run: list[tuple[int, int, str]] = []
        for start, end, box in (_words(block) or []) + [(None, None, None)]:
            match = None if box is None else same_word(block.text[start:end], box, block.page_number)
            if match and (not run or run[-1][2] == match):
                run.append((start, end, match))
                continue
            if run:
                found.append(make_entity(block, run[0][2], run[0][0], run[-1][1], 0.8, "context:figure_duplicate"))
            run = [(start, end, match)] if match else []
    return found


def repair_spans(
    blocks: Sequence[ContentBlock], entities: Sequence[PIIEntity], registry: NameRegistry,
) -> list[PIIEntity]:
    """All span repairs for one document; the caller merges them with the detections."""
    repaired = (wrapped_prefixes(blocks, entities) + wrapped_initials(blocks, entities, registry)
                + registered_first_names(blocks, entities, registry) + figure_duplicates(blocks, entities))
    # Glued characters are absorbed last, so repaired spans get them too.
    return repaired + attached_characters(blocks, list(entities) + repaired)
