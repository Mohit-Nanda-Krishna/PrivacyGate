"""Detection that only makes sense for OCR'd text (scanned pages, figures, screenshots).

OCR damages exactly the characters the regular detectors anchor on: "@" goes
missing, domains lose letters ("acnecerp com"), surnames gain or lose one
("Vorsbermann", "zewczyk"), and a screenshot's table arrives as lines of words
with positions instead of cells. Three passes, all restricted to OCR blocks:

- ocr_emails: an e-mail domain already seen intact in the document, found
  approximately, with the local part attached in front of it;
- ocr_surnames: a token within one or two OCR errors of a registered surname;
- column_role_names: names under a "Name", "Owner", "Created by", ... column of
  an OCR'd table, using the word boxes to find the column.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from statistics import median
from typing import Iterable, Sequence

from privacygate.detection.common import make_entity
from privacygate.detection.names import NameRegistry, role_context_names
from privacygate.detection.regex_detector import _DATE
from privacygate.models import ContentBlock, PIIEntity

OCR_METHODS = frozenset({"ocr", "figure_ocr", "embedded_image_ocr"})

# --- damaged e-mail addresses ----------------------------------------------------
DOMAIN_SIMILARITY = 0.75
MIN_DOMAIN_LABEL = 6
_EMAIL_DOMAIN = re.compile(r"@([A-Za-z0-9-]+)\.([A-Za-z]{2,})\b")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._'’-]*")
# A top-level domain after a dot (or a comma OCR made of it), or what OCR makes of
# ".com" after a lost dot: " com", " cor", " con", " corn".
_TLD = re.compile(r"\.[ \t]?[a-z]{2,10}\b|,[a-z]{2,10}\b|[ \t](?:c[o0][a-z]{0,2}|org|net)\b", re.IGNORECASE)
_LOCAL_WORD = re.compile(r"^[a-z][a-z0-9._-]*$")


def _domain_labels(entities: Iterable[PIIEntity], texts: dict[str, str]) -> set[str]:
    labels = set()
    for entity in entities:
        if entity.entity_type != "EMAIL_ADDRESS":
            continue
        match = _EMAIL_DOMAIN.search(texts[entity.block_id][entity.start:entity.end])
        if match and len(match.group(1)) >= MIN_DOMAIN_LABEL:
            labels.add(match.group(1).lower())
    return labels


def ocr_emails(
    blocks: Sequence[ContentBlock], entities: Iterable[PIIEntity], allowlist: frozenset[str],
) -> list[PIIEntity]:
    """E-mail addresses whose domain matches a domain seen intact elsewhere in the document.

    The domain must be followed by something TLD-like or preceded by "@", and
    there must be a local part: letters attached to the domain or to "@", plus
    one lower-case word before them when the attached part has no separator
    ("enily martinez @acnecerp com"). Detector "pattern:ocr_email".
    """
    texts = {block.block_id: block.text for block in blocks}
    labels = _domain_labels(entities, texts)
    if not labels:
        return []
    found = []
    for block in blocks:
        if block.extraction_method not in OCR_METHODS:
            continue
        text = block.text
        lower = text.lower()
        for word in _WORD.finditer(text):
            token = lower[word.start():word.end()]
            for label in labels:
                hit = _find_label(token, label)
                if hit is None:
                    continue
                domain_start, domain_end = word.start() + hit[0], word.start() + hit[1]
                while domain_end < len(text) and text[domain_end].isalnum():  # "acnecer|p com"
                    domain_end += 1
                tld = _TLD.match(text, domain_end)
                at_before = text[max(0, domain_start - 2):domain_start].strip().endswith("@")
                if not tld and not at_before:
                    continue
                end = tld.end() if tld else domain_end
                start = _local_part_start(text, domain_start, allowlist)
                if start is None:
                    continue
                found.append(make_entity(block, "EMAIL_ADDRESS", start, end, 0.8, "pattern:ocr_email"))
                break
    return found


def _trigrams(word: str) -> set[str]:
    return {word[i:i + 3] for i in range(len(word) - 2)}


def _find_label(token: str, label: str) -> tuple[int, int] | None:
    """Offsets of the best approximate occurrence of label inside token."""
    if len(token) < len(label) - 1 or not _trigrams(token) & _trigrams(label):
        return None
    best = None
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(label)
    for size in range(len(label) - 1, len(label) + 2):
        for offset in range(0, len(token) - size + 1):
            window = token[offset:offset + size]
            if not window.replace("-", "").isalnum():
                continue
            matcher.set_seq1(window)
            if matcher.quick_ratio() < DOMAIN_SIMILARITY:
                continue
            ratio = matcher.ratio()
            if ratio >= DOMAIN_SIMILARITY and (best is None or ratio > best[0]):
                best = (ratio, offset, offset + size)
    return None if best is None else (best[1], best[2])


def _local_part_start(text: str, domain_start: int, allowlist: frozenset[str]) -> int | None:
    """Start of the local part in front of a domain found at domain_start, or None.

    The domain hit may start mid-token ("davis@oacmecorp": OCR noise after
    "@"), so letters attached to the domain are taken first, then an "@" with
    optional spaces around it ("berg @cadence"), then the letters before it.
    """
    def attached(position: int) -> int:
        while position > 0 and (text[position - 1].isalnum() or text[position - 1] in "._-"):
            position -= 1
        return position

    start = attached(domain_start)
    local = text[start:domain_start]
    probe = start
    while probe > 0 and text[probe - 1] in " \t":
        probe -= 1
    if probe > 0 and text[probe - 1] == "@":
        position = probe - 1
        while position > 0 and text[position - 1] in " \t":
            position -= 1
        start = attached(position)
        local = text[start:position]
        if position < probe - 1 and local.lower() in allowlist:
            return None  # "see @domain": an ordinary word, not a split address
    if not any(character.isalpha() for character in text[start:domain_start]):
        return None  # a bare domain is not an address
    # "s,marchetti": an initial whose dot OCR read as a comma.
    if start >= 2 and text[start - 1] == "," and text[start - 2].isalpha() and (
            start == 2 or not text[start - 3].isalnum()):
        return start - 2
    # "enily martinez @acne...": OCR split first.last at the dot; take one more word.
    if not re.search(r"[._-]", local) and start > 0 and text[start - 1] in " \t":
        previous = re.search(r"(?<![\w.@-])([a-z][a-z0-9._-]+)[ \t]$", text[:start])
        if previous and _LOCAL_WORD.match(previous.group(1)) and previous.group(1) not in allowlist:
            start = previous.start(1)
    return start


# --- damaged surnames -----------------------------------------------------------
SURNAME_SIMILARITY = 0.85
MIN_FUZZY_SURNAME = 6
_SURNAME_TOKEN = re.compile(r"(?<![\w-])[A-Z][A-Za-z'’-]{3,}(?![\w-])")
# OCR'd initials in front of a name: "H, ", "Y. O, ", "G. & " (a misread "F."), "KC ".
# A lower-case letter counts only at the start of a line ("m T. Achebe": OCR read "M." as "m").
_INITIALS_BEFORE = re.compile(r"(?:(?<![\w&.,])(?:(?:[A-Z][.,]|&|[A-Z]{1,2})[ \t]){1,3}|^[a-z][.,]?[ \t])$")


def ocr_surnames(blocks: Sequence[ContentBlock], registry: NameRegistry) -> list[PIIEntity]:
    """Capitalised OCR tokens within OCR distance of a registered surname (detector "name_sweep_ocr").

    Exact matches are left to the regular sweep. Surnames shorter than six
    letters are skipped: at that length one changed letter is another word.
    """
    surnames = {
        person.last.replace("-", "").lower()
        for person in registry.people
        if len(person.last.replace("-", "")) >= MIN_FUZZY_SURNAME
    }
    if not surnames:
        return []
    by_trigram: dict[str, set[str]] = {}
    for surname in surnames:
        for trigram in _trigrams(surname):
            by_trigram.setdefault(trigram, set()).add(surname)
    found = []
    for block in blocks:
        if block.extraction_method not in OCR_METHODS:
            continue
        for match in _SURNAME_TOKEN.finditer(block.text):
            token = re.sub(r"[^a-z]", "", match.group().lower())
            if token in surnames or len(token) < MIN_FUZZY_SURNAME - 1:
                continue
            candidates = {s for t in _trigrams(token) for s in by_trigram.get(t, ())}
            if not any(SequenceMatcher(None, token, surname, autojunk=False).ratio() >= SURNAME_SIMILARITY
                       for surname in candidates if abs(len(surname) - len(token)) <= 2):
                continue
            found.append(make_entity(block, "PERSON", match.start(), match.end(), 0.8, "name_sweep_ocr"))
    return found


def absorb_ocr_initials(blocks: Sequence[ContentBlock], entities: Sequence[PIIEntity]) -> list[PIIEntity]:
    """PERSON spans for OCR'd initials right before a detected name ("H, [Vorstermann]", "KC [Burney]").

    OCR turns "H." into "H," and "F." into "&", so the name patterns stop at the
    surname and leave the initials readable. Detector "name_sweep_ocr".
    """
    texts = {block.block_id: block for block in blocks}
    found = []
    for entity in entities:
        block = texts.get(entity.block_id)
        if entity.entity_type != "PERSON" or block is None or block.extraction_method not in OCR_METHODS:
            continue
        initials = _INITIALS_BEFORE.search(block.text[:entity.start])
        if initials:
            found.append(make_entity(block, "PERSON", initials.start(), entity.end, 0.8, "name_sweep_ocr"))
    return found


# --- labelled identifiers and IP addresses as OCR prints them ---------------------
# "Passpon TK4820913", "PAN AQERPR7741L": the label is damaged, the value shape is not.
_LABELLED_ID = re.compile(
    r"\b(?:(?i:pass\s?p[o0][a-z]{0,3}(?:\s+no\.?)?)|PAN)[\s:#]*(?P<value>[A-Z]{1,2}\d{6,9}|[A-Z]{5,6}\d{4}[A-Z])\b"
)
# "198.51,100.62": OCR reads some dots as commas. At least two real dots.
_OCR_IP = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{1,3}){3}(?![\d.,]?\d)")


# A form label alone at the end of a line, its value on the next line (ID badges, forms).
_DOB_LABEL_AT_END = re.compile(r"(?i:\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth))\s*:?\s*$")
_DATE_ANYWHERE = re.compile(rf"(?<!\w){_DATE}(?!\w)")
# "DOB 0912/1994": a numeric date after the label with one separator lost.
_DOB_DAMAGED = re.compile(r"(?i:\b(?:DOB|date\s+of\s+birth))[\s:]*(?P<value>\d{3,4}[/.-]\d{2,4}|\d{1,2}[/.-]\d{3,6})(?![\w/.-])")


def ocr_identifiers(blocks: Sequence[ContentBlock]) -> list[PIIEntity]:
    """OCR-only identifier rules (detectors "pattern:ocr_labelled_id", "pattern:ocr_ip", "pattern:ocr_dob").

    Passport/PAN numbers after a damaged label, comma-damaged IPv4 addresses,
    a damaged numeric date after a DOB label, a date on the line after a
    "Date of birth" label of the same image, figure or page, and a date printed
    under such a label (found by word position).
    """
    found = []
    previous: dict[tuple, ContentBlock] = {}
    for block in blocks:
        if block.extraction_method not in OCR_METHODS:
            continue
        container = _container(block)
        before = previous.get(container)
        previous[container] = block
        if before is not None and _DOB_LABEL_AT_END.search(before.text):
            date = _DATE_ANYWHERE.search(block.text)
            if date:
                found.append(make_entity(block, "DATE_OF_BIRTH", *date.span(), 0.85, "pattern:ocr_dob"))
        for match in _DOB_DAMAGED.finditer(block.text):
            found.append(make_entity(block, "DATE_OF_BIRTH", *match.span("value"), 0.85, "pattern:ocr_dob"))
        for match in _LABELLED_ID.finditer(block.text):
            found.append(make_entity(block, "GOVERNMENT_ID", *match.span("value"), 0.85, "pattern:ocr_labelled_id"))
        for match in _OCR_IP.finditer(block.text):
            octets = re.split(r"[.,]", match.group())
            if match.group().count(".") >= 2 and all(int(octet) <= 255 for octet in octets):
                found.append(make_entity(block, "IP_ADDRESS", *match.span(), 0.8, "pattern:ocr_ip"))
    found += _dob_below_label(blocks)
    return found


_BIRTH_WORD = re.compile(r"^(?:BIRTH|DOB)\W*$", re.IGNORECASE)
_DATE_WORD = re.compile(r"\d|^[A-Z][a-z]{2,8}\.?,?$")


def _dob_below_label(blocks: Sequence[ContentBlock]) -> list[PIIEntity]:
    """A date printed under a "DATE OF BIRTH" form label (ID badges), found by position.

    OCR splits such labels and values into separate lines ("DATE" / "IF BIRTH"
    / "28 Februa" / "1979"), so the label word's box is used: words starting
    within three label heights below it, in the label's column, that are
    digits or a month-like word form the value, if any of them has a digit.
    """
    groups: dict[tuple, list[tuple[ContentBlock, list]]] = {}
    for block in blocks:
        if block.extraction_method in OCR_METHODS:
            words = _words(block)
            if words:
                groups.setdefault(_container(block), []).append((block, words))
    found = []
    for lines in groups.values():
        every = [(block, start, end, box) for block, words in lines for start, end, box in words]
        for block, start, end, box in every:
            if not _BIRTH_WORD.match(block.text[start:end]):
                continue
            height = max(1, box[3] - box[1])
            # Extend the label left over "DATE OF" on the same line.
            left = min([b[0] for _, _, _, b in every if abs(b[1] - box[1]) <= height and box[0] - 12 * height <= b[0]
                        <= box[0]] + [box[0]])
            values: dict[str, list[tuple[int, int]]] = {}
            for other, s, e, b in every:
                if (box[3] < b[1] <= box[3] + 3 * height and left - 3 * height <= b[0] <= box[2] + 12 * height
                        and _DATE_WORD.search(other.text[s:e])):
                    values.setdefault(other.block_id, []).append((s, e))
            for block_id, spans in values.items():
                owner = next(b for b, _ in lines if b.block_id == block_id)
                text = owner.text[spans[0][0]:spans[-1][1]]
                if any(character.isdigit() for character in text):
                    found.append(make_entity(owner, "DATE_OF_BIRTH", spans[0][0], spans[-1][1], 0.85,
                                             "pattern:ocr_dob"))
    return found


# --- names under a person column of an OCR'd table -------------------------------
# Whole header cells that say "this column holds people".
_PERSON_HEADER = re.compile(
    r"^(?:(?:full |user |display )?names?|(?:risk |control |process |issue |data )?owners?|assignees?|users?|"
    r"created by|modified by|updated by|changed by|requested by|approved by|attested by|"
    r"reviewers?|approvers?|employees?|members?)$",
    re.IGNORECASE,
)
CELL_GAP_FACTOR = 1.5


def _words(block: ContentBlock) -> list[tuple[int, int, list[int]]] | None:
    """(start, end, box) per word, or None when text and word boxes disagree."""
    boxes = block.metadata.get("word_boxes_pixels")
    if not boxes:
        return None
    words, position = [], 0
    for word, box in zip(block.text.split(" "), boxes):
        words.append((position, position + len(word), box))
        position += len(word) + 1
    return words if len(words) == len(boxes) == len(block.text.split(" ")) else None


def _container(block: ContentBlock) -> tuple:
    meta = block.metadata
    return (meta.get("image_name"), block.page_number, block.slide_number, meta.get("figure"))


def _header_cells(block: ContentBlock, words) -> list[tuple[int, int, bool]] | None:
    """Column x-ranges (left, right, holds people) when the line is a table header with a person column."""
    if any(character.isdigit() for character in block.text) or block.text.rstrip().endswith("."):
        return None
    heights = [box[3] - box[1] for _, _, box in words]
    gap = CELL_GAP_FACTOR * median(heights) if heights else 0
    cells: list[list[tuple[int, int, list[int]]]] = []
    for word in words:
        if cells and word[2][0] - cells[-1][-1][2][2] <= gap:
            cells[-1].append(word)
        else:
            cells.append([word])
    if len(cells) < 3:
        return None
    columns = []
    for index, cell in enumerate(cells):
        label = " ".join(re.sub(r"[^A-Za-z]", "", block.text[s:e]) for s, e, _ in cell)
        right = cells[index + 1][0][2][0] if index + 1 < len(cells) else 10 ** 9
        columns.append((cell[0][2][0] - int(gap), right - int(gap / 2),
                        bool(_PERSON_HEADER.match(re.sub(r"\s+", " ", label).strip()))))
    return columns if any(person for _, _, person in columns) else None


def column_role_names(blocks: Sequence[ContentBlock], allowlist: frozenset[str]) -> list[PIIEntity]:
    """PERSON spans in OCR'd table rows under a person column header (detector "context:column_role").

    Header and rows are lines of the same image, figure or page; a row's cell is
    the words whose box centre lies inside the header cell's column. A row must
    have words in at least two columns; a line that does not and starts in the
    first column (a heading, prose) ends the table.
    Inside a cell the usual role-context name shape applies ("Mark Read").
    """
    groups: dict[tuple, list[ContentBlock]] = {}
    for block in blocks:
        if block.extraction_method in OCR_METHODS:
            groups.setdefault(_container(block), []).append(block)
    found = []
    for lines in groups.values():
        columns: list[tuple[int, int, bool]] = []
        header_bottom = 0
        for block in sorted(lines, key=lambda b: (b.metadata.get("bbox_pixels") or [0, 0])[1]):
            words = _words(block)
            if words is None:
                continue
            header = _header_cells(block, words)
            if header:
                columns, header_bottom = header, max(box[3] for _, _, box in words)
                continue
            if not columns or min(box[1] for _, _, box in words) < header_bottom:
                continue
            centres = [(box[0] + box[2]) / 2 for _, _, box in words]
            if sum(any(left <= c < right for c in centres) for left, right, _ in columns) < 2:
                # A heading or prose line starts in the first column and ends the table; a
                # sidebar line left of it or a clipped fragment on the right does not.
                if columns[0][0] <= min(centres) < columns[0][1]:
                    columns = []
                continue
            for left, right, person in columns:
                if not person:
                    continue
                inside = [(s, e) for s, e, box in words if left <= (box[0] + box[2]) / 2 < right]
                if not inside:
                    continue
                start, end = inside[0][0], inside[-1][1]
                cell = ContentBlock(block.block_id, block.text[:end], page_number=block.page_number,
                                    slide_number=block.slide_number, extraction_method=block.extraction_method,
                                    metadata=block.metadata)
                for entity in role_context_names(cell, allowlist):
                    if entity.start >= start:
                        found.append(make_entity(block, "PERSON", entity.start, entity.end, 0.85,
                                                 "context:column_role"))
    return found
