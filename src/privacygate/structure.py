"""Extraction fidelity: how much of a source file's structure the extracted text keeps.

Two measurements, both against references built independently of the extractors:

* DOCX/PPTX: a reference read straight from the file's XML (every paragraph of
  the body, tables, text boxes, shapes and groups, headers/footers and speaker
  notes, in document order) is compared with the extracted native blocks:
  - character coverage: share of the reference's letters and digits found in
    the extraction (word multiset, each word weighted by its length);
  - reading-order similarity: of consecutive reference paragraphs that are
    both found in the extracted text, the share found in the same order;
  - table-cell preservation: share of non-empty reference table cells whose
    text is extracted at the same row and column.
* Scanned PDF: hand transcriptions in eval/reference/<pdf stem>/page_NN.txt
  are compared with the OCR'd lines of those pages:
  - character error rate (CER): edit distance between each reference line and
    the best-matching stretch of an OCR line, over all reference characters;
  - line order: of consecutive reference lines, the share whose matches come
    in the same order in the extracted text.

These differ from redaction structure preservation (evaluation.py), which only
checks that sanitization kept the extracted blocks and their locations.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree

from privacygate.models import Document

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
NATIVE_METHODS = frozenset({"docx_native", "pptx_native", "pdf_native"})
# Paragraphs shorter than this (after normalisation) are too common to locate reliably.
MIN_LOCATABLE = 8
# A reference line counts as found when an OCR line matches at least this well.
MIN_LINE_MATCH = 0.5


@dataclass
class Reference:
    """Text of a source file in document order, plus its table cells."""

    paragraphs: list[str] = field(default_factory=list)
    # (container, row, column, text): container is ("docx", table number) or ("pptx", slide number).
    cells: list[tuple[tuple, int, int, str]] = field(default_factory=list)


def normalise(text: str) -> str:
    return "".join(character.lower() for character in text if character.isalnum())


def _words(text: str) -> list[str]:
    return [word.lower() for word in re.findall(r"[^\W_]+", text)]


# --- DOCX reference ---------------------------------------------------------------

def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    """Text of a w:p, excluding text boxes nested in it (they are their own paragraphs)."""
    parts = []

    def walk(element: ElementTree.Element) -> None:
        for child in element:
            if child.tag in (W + "txbxContent", MC_FALLBACK):
                continue
            if child.tag == W + "t":
                parts.append(child.text or "")
            elif child.tag in (W + "tab", W + "br", W + "cr"):
                parts.append(" ")
            else:
                walk(child)

    walk(paragraph)
    return "".join(parts).strip()


def _text_boxes(element: ElementTree.Element):
    """w:txbxContent elements inside a paragraph, skipping mc:Fallback copies and boxes inside boxes."""
    for child in element:
        if child.tag == MC_FALLBACK:
            continue
        if child.tag == W + "txbxContent":
            yield child
        else:
            yield from _text_boxes(child)


def _docx_walk(element: ElementTree.Element, reference: Reference, tables: list[int], top_level: bool) -> None:
    """Paragraphs, tables and text boxes in document order. tables[0] counts top-level tables."""
    for child in element:
        if child.tag == W + "p":
            text = _docx_paragraph_text(child)
            if text:
                reference.paragraphs.append(text)
            for box in _text_boxes(child):  # a text box is read where it is anchored
                _docx_walk(box, reference, tables, top_level=False)
        elif child.tag == W + "tbl":
            if top_level:
                tables[0] += 1
            for row_number, row in enumerate(child.findall(W + "tr"), start=1):
                before = row.find(f"{W}trPr/{W}gridBefore")
                column = 1 + (int(before.get(W + "val", "0")) if before is not None else 0)
                for cell in row.findall(W + "tc"):
                    contents = Reference()
                    _docx_walk(cell, contents, tables, top_level=False)  # nested tables are cell text
                    reference.paragraphs.extend(contents.paragraphs)
                    text = " ".join(contents.paragraphs)
                    if top_level and text:
                        reference.cells.append((("docx", tables[0]), row_number, column, text))
                    span = cell.find(f"{W}tcPr/{W}gridSpan")
                    column += int(span.get(W + "val", "1")) if span is not None else 1
        elif child.tag in (W + "sdt", W + "sdtContent", W + "customXml"):
            _docx_walk(child, reference, tables, top_level)


def docx_reference(path: str | Path) -> Reference:
    """Body (paragraphs, tables, text boxes) in order, then each header/footer part."""
    reference = Reference()
    with zipfile.ZipFile(path) as archive:
        body = ElementTree.fromstring(archive.read("word/document.xml")).find(W + "body")
        _docx_walk(body, reference, [0], top_level=True)
        # Header/footer tables are not numbered like body tables: their text counts, their cells do not.
        parts = sorted(name for name in archive.namelist()
                       if re.fullmatch(r"word/(header|footer)\d*\.xml", name))
        for name in parts:
            _docx_walk(ElementTree.fromstring(archive.read(name)), reference, [0], top_level=False)
    return reference


# --- PPTX reference ---------------------------------------------------------------

def _pptx_paragraphs(body: ElementTree.Element) -> list[str]:
    texts = []
    for paragraph in body.iter(A + "p"):
        parts = []
        for child in paragraph.iter():
            if child.tag == A + "t":
                parts.append(child.text or "")
            elif child.tag == A + "br":
                parts.append(" ")
        text = "".join(parts).strip()
        if text:
            texts.append(text)
    return texts


def _pptx_shapes(tree: ElementTree.Element, slide: int, reference: Reference) -> None:
    for shape in tree:
        if shape.tag == P + "grpSp":
            _pptx_shapes(shape, slide, reference)
        elif shape.tag == P + "sp":
            body = shape.find(P + "txBody")
            if body is not None:
                reference.paragraphs.extend(_pptx_paragraphs(body))
        elif shape.tag == P + "graphicFrame":
            for table in shape.iter(A + "tbl"):
                for row_number, row in enumerate(table.findall(A + "tr"), start=1):
                    for column, cell in enumerate(row.findall(A + "tc"), start=1):
                        body = cell.find(A + "txBody")
                        texts = _pptx_paragraphs(body) if body is not None else []
                        reference.paragraphs.extend(texts)
                        if texts:
                            reference.cells.append((("pptx", slide), row_number, column, " ".join(texts)))


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    folder, name = posixpath.split(part)
    rels = f"{folder}/_rels/{name}.rels"
    if rels not in archive.namelist():
        return {}
    root = ElementTree.fromstring(archive.read(rels))
    return {rel.get("Id"): posixpath.normpath(posixpath.join(folder, rel.get("Target")))
            for rel in root.iter(REL + "Relationship")}


def pptx_reference(path: str | Path) -> Reference:
    """Slides in presentation order: shapes (groups, tables) in z-order, then the slide's notes."""
    reference = Reference()
    with zipfile.ZipFile(path) as archive:
        presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
        targets = _relationships(archive, "ppt/presentation.xml")
        slide_ids = presentation.find(P + "sldIdLst")
        slides = [targets[item.get(R + "id")] for item in (slide_ids if slide_ids is not None else [])]
        for number, part in enumerate(slides, start=1):
            tree = ElementTree.fromstring(archive.read(part)).find(f"{P}cSld/{P}spTree")
            if tree is not None:
                _pptx_shapes(tree, number, reference)
            for target in _relationships(archive, part).values():
                if "notesSlide" in target and target in archive.namelist():
                    notes = ElementTree.fromstring(archive.read(target)).find(f"{P}cSld/{P}spTree")
                    for shape in notes.iter(P + "sp") if notes is not None else ():
                        placeholder = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                        body = shape.find(P + "txBody")
                        if placeholder is not None and placeholder.get("type") == "body" and body is not None:
                            reference.paragraphs.extend(_pptx_paragraphs(body))
    return reference


def office_reference(path: str | Path) -> Reference:
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        return docx_reference(path)
    if suffix == ".pptx":
        return pptx_reference(path)
    raise ValueError("XML references exist for .docx and .pptx only.")


# --- scores -----------------------------------------------------------------------

def character_coverage(reference: Iterable[str], extracted: Iterable[str]) -> float | None:
    """Share of reference letters/digits found in the extraction (word multiset, length-weighted)."""
    wanted = Counter(word for text in reference for word in _words(text))
    found = Counter(word for text in extracted for word in _words(text))
    total = sum(len(word) * count for word, count in wanted.items())
    if not total:
        return None
    return sum(len(word) * min(count, found[word]) for word, count in wanted.items()) / total


def reading_order(reference: Sequence[str], extracted: Sequence[str]) -> tuple[float | None, int]:
    """(share of consecutive located reference paragraphs in the same order, paragraphs located).

    Each paragraph is looked up in the normalised extracted stream from the
    previous paragraph's position on (repeated text such as headers is found
    where it is expected), falling back to its first occurrence.
    """
    stream = "".join(normalise(text) for text in extracted)
    positions: list[int] = []
    cursor = 0
    for text in reference:
        key = normalise(text)
        if len(key) < MIN_LOCATABLE:
            continue
        position = stream.find(key, cursor)
        if position < 0:
            position = stream.find(key)
        if position < 0:
            continue
        positions.append(position)
        cursor = position + len(key)
    pairs = list(zip(positions, positions[1:]))
    if not pairs:
        return None, len(positions)
    return sum(later > earlier for earlier, later in pairs) / len(pairs), len(positions)


def table_cell_preservation(reference: Reference, document: Document) -> tuple[float | None, int]:
    """(share of non-empty reference cells extracted with the same text at the same row/column, cells)."""
    # Several PPTX tables on one slide share the slide as container, so each position keeps a set.
    extracted: dict[tuple, set[str]] = {}
    for block in document.blocks:
        meta = block.metadata
        if meta.get("kind") != "table_cell" or "row_number" not in meta:
            continue
        if document.file_type == "docx":
            container = ("docx", meta.get("table_number"))
        else:
            container = ("pptx", block.slide_number)
        extracted.setdefault((container, meta["row_number"], meta["column_number"]), set()).add(normalise(block.text))
    cells = [(container, row, column, normalise(text)) for container, row, column, text in reference.cells]
    cells = [cell for cell in cells if cell[3]]
    if not cells:
        return None, 0
    kept = sum(text in extracted.get((container, row, column), ()) for container, row, column, text in cells)
    return kept / len(cells), len(cells)


@dataclass
class OfficeFidelity:
    character_coverage: float | None
    reading_order: float | None
    table_cells: float | None
    reference_paragraphs: int
    located_paragraphs: int
    reference_cells: int

    def to_dict(self) -> dict:
        def rounded(value):
            return None if value is None else round(value, 4)

        return {
            "kind": "xml_reference",
            "character_coverage": rounded(self.character_coverage),
            "reading_order": rounded(self.reading_order),
            "table_cells": rounded(self.table_cells),
            "reference_paragraphs": self.reference_paragraphs,
            "located_paragraphs": self.located_paragraphs,
            "reference_cells": self.reference_cells,
        }


def office_fidelity(path: str | Path, document: Document) -> OfficeFidelity:
    """Score the native blocks of an extracted DOCX/PPTX against its XML reference."""
    reference = office_reference(path)
    native = [block.text for block in document.blocks if block.extraction_method in NATIVE_METHODS]
    order, located = reading_order(reference.paragraphs, native)
    cells, cell_count = table_cell_preservation(reference, document)
    return OfficeFidelity(character_coverage(reference.paragraphs, native), order, cells,
                          len(reference.paragraphs), located, cell_count)


# --- scanned PDF against hand transcriptions --------------------------------------

def substring_distance(pattern: str, text: str) -> int:
    """Edit distance between pattern and the closest stretch of text (free start and end in text)."""
    if not pattern:
        return 0
    previous = [0] * (len(text) + 1)
    for i, character in enumerate(pattern, start=1):
        current = [i] + [0] * len(text)
        for j, other in enumerate(text, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (character != other))
        previous = current
    return min(previous)


def _collapse(text: str) -> str:
    return " ".join(text.split())


@dataclass
class PageFidelity:
    page: int
    reference_characters: int
    errors: int
    reference_lines: int
    found_lines: int
    ordered_pairs: int
    pairs: int

    @property
    def cer(self) -> float | None:
        return self.errors / self.reference_characters if self.reference_characters else None

    @property
    def line_order(self) -> float | None:
        return self.ordered_pairs / self.pairs if self.pairs else None


MIN_SEGMENT = 4  # shortest unmatched rest of a reference line that is matched again
MAX_SEGMENTS = 4


def _match_segments(line: str, candidates: Sequence[str], depth: int = 0) -> list[tuple[int, int, tuple[int, int] | None]]:
    """(reference start, errors, (OCR line, offset) or None) per segment of a reference line.

    The line is matched to its most similar OCR line; the part of the line that
    OCR line covers is scored by substring edit distance, and an uncovered
    prefix or suffix (OCR read a table row's cells as separate lines) is
    matched again on its own. A segment without a match of at least
    MIN_LINE_MATCH similarity counts every character as an error.
    """
    unmatched = [(0, sum(not character.isspace() for character in line), None)]
    best = None
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(line)
    for index, candidate in enumerate(candidates):
        matcher.set_seq1(candidate)
        blocks = [block for block in matcher.get_matching_blocks() if block.size >= 3]
        matched = sum(block.size for block in blocks)
        if blocks and (best is None or matched > best[0]):
            best = (matched, index, blocks)
    if best is None or best[0] < MIN_SEGMENT:
        return unmatched
    matched, index, blocks = best
    low, high = blocks[0].b, blocks[-1].b + blocks[-1].size
    # Widen to word boundaries so a misread first or last letter is an error, not a separate rest.
    while low > 0 and not line[low - 1].isspace():
        low -= 1
    while high < len(line) and not line[high].isspace():
        high += 1
    if matched < MIN_LINE_MATCH * (high - low):
        return unmatched  # scattered coincidental matches
    covered = line[low:high]
    segments = [(low, min(substring_distance(covered, candidates[index]), len(covered)), (index, blocks[0].a))]
    for start, rest in ((0, line[:low]), (high, line[high:])):
        if not rest.strip():
            continue
        if len(rest.strip()) >= MIN_SEGMENT and depth + 1 < MAX_SEGMENTS:
            segments += [(start + s, e, p) for s, e, p in _match_segments(rest.strip(), candidates, depth + 1)]
        else:
            segments.append((start, sum(not character.isspace() for character in rest), None))
    return sorted(segments, key=lambda segment: segment[0])


def page_fidelity(page: int, reference_lines: Sequence[str], ocr_lines: Sequence[str]) -> PageFidelity:
    """CER and line order of one page's OCR lines (in extraction order) against a transcription.

    CER: character errors of every reference line (see _match_segments) over
    all reference characters. Line order: over the matched segments in
    reference order, the share of consecutive pairs whose OCR positions also
    increase, so a table read column by column instead of row by row loses
    order, not characters.
    """
    candidates = [_collapse(line) for line in ocr_lines if line.strip()]
    errors = characters = found = 0
    positions: list[tuple[int, int]] = []
    lines = [line for line in (_collapse(line) for line in reference_lines) if line]
    for line in lines:
        characters += len(line)
        segments = _match_segments(line, candidates)
        errors += sum(segment_errors for _, segment_errors, _ in segments)
        located = [position for _, _, position in segments if position is not None]
        found += bool(located)
        for position in located:
            if not positions or positions[-1] != position:
                positions.append(position)
    pairs = list(zip(positions, positions[1:]))
    return PageFidelity(page, characters, errors, len(lines), found,
                        sum(later > earlier for earlier, later in pairs), len(pairs))


def load_transcriptions(folder: str | Path) -> dict[int, list[str]]:
    """page number -> reference lines, from page_NN.txt files (lines starting with "#" are comments)."""
    pages = {}
    for path in sorted(Path(folder).glob("page_*.txt")):
        number = int(re.search(r"\d+", path.stem).group())
        lines = path.read_text(encoding="utf-8").splitlines()
        pages[number] = [line for line in lines if line.strip() and not line.startswith("#")]
    return pages


def scanned_fidelity(document: Document, transcriptions: dict[int, list[str]]) -> dict:
    """Per-page and overall CER/line order of OCR'd pages against hand transcriptions."""
    results = []
    for page, lines in sorted(transcriptions.items()):
        ocr_lines = [block.text for block in document.blocks
                     if block.page_number == page and block.extraction_method in ("ocr", "figure_ocr")]
        results.append(page_fidelity(page, lines, ocr_lines))
    characters = sum(result.reference_characters for result in results)
    pairs = sum(result.pairs for result in results)

    def rounded(value):
        return None if value is None else round(value, 4)

    return {
        "kind": "transcription",
        "cer": rounded(sum(r.errors for r in results) / characters) if characters else None,
        "line_order": rounded(sum(r.ordered_pairs for r in results) / pairs) if pairs else None,
        "pages": [{"page": r.page, "cer": rounded(r.cer), "line_order": rounded(r.line_order),
                   "reference_lines": r.reference_lines, "found_lines": r.found_lines,
                   "reference_characters": r.reference_characters} for r in results],
    }
