"""Evaluation and benchmarking metrics for PII detection, redaction, and structure retention."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Sequence

from privacygate.models import ContentBlock, Document, PIIEntity


@dataclass
class GroundTruthItem:
    """A labelled ground truth PII entity for benchmark evaluation."""

    entity_type: str
    expected_text: str
    block_id: str | None = None


@dataclass
class BenchmarkResult:
    """Evaluation metrics according to PRD Sections 26 and 27."""

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    residual_rate: float
    structure_retention: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "residual_rate": round(self.residual_rate, 4),
            "structure_retention": round(self.structure_retention, 4),
        }


def calculate_metrics(
    tp: int,
    fp: int,
    fn: int,
    residual_count: int = 0,
    structure_retention: float = 1.0,
) -> BenchmarkResult:
    """Compute precision, recall, F1, and residual rates safely."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    total_truth = tp + fn
    residual_rate = residual_count / max(total_truth, 1) if total_truth > 0 else 0.0

    return BenchmarkResult(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1_score=f1,
        residual_rate=residual_rate,
        structure_retention=structure_retention,
    )


def evaluate_detection(
    detected: Sequence[PIIEntity],
    ground_truth: Sequence[GroundTruthItem],
    block_texts: dict[str, str],
) -> BenchmarkResult:
    """Match detected entities against labelled ground truth items.

    A detection is considered a True Positive if its extracted text matches
    the ground truth text and entity type (or compatible category).
    """
    matched_truth = set()
    matched_detected = set()

    # Extract detected text for each entity
    detected_spans: list[tuple[int, str, str]] = []
    for idx, e in enumerate(detected):
        text = block_texts.get(e.block_id, "")
        span_text = text[e.start:e.end].strip() if e.end <= len(text) else ""
        detected_spans.append((idx, e.entity_type.upper(), span_text.lower()))

    # Match ground truth
    for t_idx, item in enumerate(ground_truth):
        target_text = item.expected_text.strip().lower()
        target_type = item.entity_type.upper()

        for d_idx, d_type, d_text in detected_spans:
            if d_idx in matched_detected:
                continue

            # Match if expected text is contained or exact, and category matches
            if (target_text == d_text or target_text in d_text or d_text in target_text) and (
                target_type == d_type or target_type in ("PII", "ID", "IDENTIFIER")
            ):
                matched_truth.add(t_idx)
                matched_detected.add(d_idx)
                break

    tp = len(matched_truth)
    fn = len(ground_truth) - tp
    fp = len(detected) - len(matched_detected)

    return calculate_metrics(tp=tp, fp=fp, fn=fn)


def measure_structure_retention(
    original_blocks: Sequence[ContentBlock],
    sanitized_blocks: Sequence[ContentBlock],
) -> float:
    """Estimate structure retention between original and sanitized documents.

    Measures block alignment, coordinate preservation, and non-empty continuity.
    Target per PRD Section 26 is >= 80% (0.80).
    """
    if not original_blocks:
        return 1.0

    if len(original_blocks) != len(sanitized_blocks):
        return 0.5  # Heavy structural degradation if block count mismatches

    matches = 0
    for orig, sanit in zip(original_blocks, sanitized_blocks):
        # 1. Block ID match
        id_match = orig.block_id == sanit.block_id
        # 2. Coordinates match
        coords_match = (
            orig.page_number == sanit.page_number
            and orig.slide_number == sanit.slide_number
            and orig.paragraph_number == sanit.paragraph_number
        )
        # 3. Text present
        content_present = bool(sanit.text.strip()) if bool(orig.text.strip()) else True

        if id_match and coords_match and content_present:
            matches += 1

    return matches / len(original_blocks)


# ---------------------------------------------------------------------------
# Document-level ground truth benchmark (eval/ground_truth/*.csv)
#
# A ground truth row names one PII value on one page (PDF page, PPTX slide,
# embedded image name, or "" for a whole DOCX body). Every occurrence of that
# value in the extracted text of that page is one unit for recall. Matching is
# case-, space- and punctuation-insensitive so OCR spacing does not matter, and
# letter-heavy values fall back to fuzzy matching when OCR misspells them.
# Rows marked uncertain are excluded from recall, and detections that only
# overlap uncertain rows count as neither true nor false positives.
# ---------------------------------------------------------------------------

GROUND_TRUTH_FIELDS = ("file", "page", "location_type", "entity_type", "value", "uncertain", "note")
FUZZY_THRESHOLD = 0.85
NATIVE_METHODS = frozenset({"pdf_native", "docx_native", "pptx_native"})

# Detector labels mapped onto the ground truth vocabulary for per-type precision.
DETECTED_TYPE_MAP: dict[str, str] = {
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "US_SSN": "GOVERNMENT_ID",
    "IBAN_CODE": "FINANCIAL_ACCOUNT",
    "CREDIT_CARD": "FINANCIAL_ACCOUNT",
    "ACCOUNT_NUMBER": "FINANCIAL_ACCOUNT",
}


@dataclass(frozen=True)
class GroundTruthRow:
    """One labelled PII value on one page of one file."""

    file: str
    page: str
    location_type: str
    entity_type: str
    value: str
    uncertain: bool = False
    note: str = ""


@dataclass
class Occurrence:
    """One ground truth value occurrence, or a value that was never extracted."""

    row: GroundTruthRow
    page: str
    start: int = -1
    end: int = -1
    method: str = ""
    fuzzy: bool = False
    detected: bool = False
    fully_redacted: bool = False

    @property
    def extracted(self) -> bool:
        return self.start >= 0

    @property
    def channel(self) -> str:
        """native / ocr / image: where the value lives in the source file."""
        if self.row.location_type == "image" or self.method == "embedded_image_ocr":
            return "image"
        return "native" if self.method in NATIVE_METHODS else "ocr"


@dataclass
class PageText:
    text: str
    spans: list[tuple[int, ContentBlock]] = field(default_factory=list)

    def method_at(self, offset: int) -> str:
        method = ""
        for start, block in self.spans:
            if start > offset:
                break
            method = block.extraction_method or ""
        return method


def load_ground_truth(path: str | Path) -> list[GroundTruthRow]:
    """Read a ground truth CSV with the columns in GROUND_TRUTH_FIELDS."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set(GROUND_TRUTH_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Ground truth file is missing columns: {sorted(missing)}")
        return [
            GroundTruthRow(
                file=row["file"].strip(), page=row["page"].strip(),
                location_type=row["location_type"].strip(), entity_type=row["entity_type"].strip(),
                value=row["value"].strip(),
                uncertain=row["uncertain"].strip().lower() in ("yes", "true", "1"),
                note=row["note"].strip(),
            )
            for row in reader
            if row["value"].strip()
        ]


def page_key(block: ContentBlock) -> str:
    """Ground truth page key: embedded image name, PDF page, PPTX slide, else ""."""
    image = block.metadata.get("image_name")
    if image:
        return str(image)
    for number in (block.page_number, block.slide_number):
        if number is not None:
            return str(number)
    return ""


def build_page_texts(document: Document) -> dict[str, PageText]:
    """Concatenate block texts per page key, remembering each block's offset."""
    pages: dict[str, PageText] = {}
    for block in document.blocks:
        page = pages.setdefault(page_key(block), PageText(""))
        if page.text:
            page.text += "\n"
        page.spans.append((len(page.text), block))
        page.text += block.text
    return pages


def _normalize(text: str) -> tuple[str, list[int]]:
    chars, index = [], []
    for position, character in enumerate(text):
        if character.isalnum():
            chars.append(character.lower())
            index.append(position)
    return "".join(chars), index


def _bounded(text: str, start: int, end: int) -> bool:
    return (start == 0 or not text[start - 1].isalnum()) and (end == len(text) or not text[end].isalnum())


def find_value(text: str, value: str, fuzzy: bool = True) -> list[tuple[int, int, bool]]:
    """Return (start, end, is_fuzzy) spans of value in text.

    Exact matching ignores case, whitespace and punctuation and requires word
    boundaries. Only when there is no exact match, values that are mostly
    letters (names, e-mail addresses) may match OCR-damaged text fuzzily.
    Digit-heavy values never match fuzzily: 555-0147 must not match 555-0174.
    """
    norm_text, index = _normalize(text)
    norm_value, _ = _normalize(value)
    if not norm_value:
        return []
    hits: list[tuple[int, int, bool]] = []
    position = 0
    while (found := norm_text.find(norm_value, position)) >= 0:
        start, end = index[found], index[found + len(norm_value) - 1] + 1
        if _bounded(text, start, end):
            hits.append((start, end, False))
        position = found + 1
    letters = sum(character.isalpha() for character in norm_value)
    if hits or not fuzzy or len(norm_value) < 6 or letters < 0.6 * len(norm_value):
        return hits

    candidates: list[tuple[float, int, int]] = []
    for size in range(max(1, len(norm_value) - 2), len(norm_value) + 3):
        for offset in range(0, len(norm_text) - size + 1):
            matcher = SequenceMatcher(None, norm_value, norm_text[offset:offset + size], autojunk=False)
            if matcher.real_quick_ratio() < FUZZY_THRESHOLD or matcher.quick_ratio() < FUZZY_THRESHOLD:
                continue
            ratio = matcher.ratio()
            if ratio >= FUZZY_THRESHOLD:
                candidates.append((ratio, offset, offset + size))
    taken: list[tuple[int, int]] = []
    for _, low, high in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if any(low < other_high and high > other_low for other_low, other_high in taken):
            continue
        taken.append((low, high))
        hits.append((index[low], index[high - 1] + 1, True))
    return sorted(hits)


def locate_ground_truth(
    rows: Sequence[GroundTruthRow], pages: dict[str, PageText], fuzzy: bool = True,
) -> list[Occurrence]:
    """Assign every value occurrence on a page to at most one ground truth row.

    Longer values claim text first, so a surname row never re-counts the
    surname inside a full name that another row already covers. A row whose
    value is not found anywhere on its page yields one unextracted occurrence.
    """
    occurrences: list[Occurrence] = []
    claimed: dict[str, list[tuple[int, int]]] = {}
    for row in sorted(rows, key=lambda row: -len(_normalize(row.value)[0])):
        page = pages.get(row.page)
        found: list[Occurrence] = []
        if page is not None:
            taken = claimed.setdefault(row.page, [])
            for start, end, is_fuzzy in find_value(page.text, row.value, fuzzy=fuzzy):
                if any(start < high and end > low for low, high in taken):
                    continue
                taken.append((start, end))
                found.append(Occurrence(row, row.page, start, end, page.method_at(start), is_fuzzy))
        if not found:
            method = page.spans[0][1].extraction_method or "" if page is not None and page.spans else ""
            found = [Occurrence(row, row.page, method=method)]
        occurrences.extend(found)
    return occurrences


def entity_page_spans(
    entities: Sequence[PIIEntity], pages: dict[str, PageText],
) -> dict[str, list[tuple[int, int, PIIEntity]]]:
    """Translate block-relative entity offsets into page-text offsets."""
    offsets: dict[str, tuple[str, int]] = {}
    for key, page in pages.items():
        for start, block in page.spans:
            offsets[block.block_id] = (key, start)
    spans: dict[str, list[tuple[int, int, PIIEntity]]] = {}
    for entity in entities:
        if entity.block_id in offsets:
            key, base = offsets[entity.block_id]
            spans.setdefault(key, []).append((base + entity.start, base + entity.end, entity))
    return spans


def _covered(text: str, start: int, end: int, spans: Sequence[tuple[int, int, PIIEntity]]) -> bool:
    return all(
        not text[position].isalnum() or any(low <= position < high for low, high, _ in spans)
        for position in range(start, end)
    )


@dataclass
class Score:
    """Occurrence-level recall and detection-level precision for one slice."""

    occurrences: int = 0
    detected: int = 0
    residual: int = 0
    detections: int = 0
    true_positives: int = 0
    false_positives: int = 0

    @property
    def recall(self) -> float | None:
        return self.detected / self.occurrences if self.occurrences else None

    @property
    def precision(self) -> float | None:
        judged = self.true_positives + self.false_positives
        return self.true_positives / judged if judged else None

    @property
    def f1(self) -> float | None:
        if self.recall is None or self.precision is None or self.recall + self.precision == 0:
            return None
        return 2 * self.recall * self.precision / (self.recall + self.precision)

    @property
    def residual_rate(self) -> float | None:
        return self.residual / self.occurrences if self.occurrences else None

    def to_dict(self) -> dict[str, float | int | None]:
        def rounded(value: float | None) -> float | None:
            return None if value is None else round(value, 4)

        return {
            "occurrences": self.occurrences, "detected": self.detected, "residual": self.residual,
            "detections": self.detections, "true_positives": self.true_positives,
            "false_positives": self.false_positives, "recall": rounded(self.recall),
            "precision": rounded(self.precision), "f1": rounded(self.f1),
            "residual_rate": rounded(self.residual_rate),
        }


@dataclass
class DocumentEvaluation:
    """Benchmark result for one file; counts only, no document text or PII values."""

    overall: Score
    by_type: dict[str, Score]
    by_channel: dict[str, Score]
    not_extracted: int
    fuzzy_matches: int
    uncertain_rows: int
    false_positive_types: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "overall": self.overall.to_dict(),
            "by_type": {key: score.to_dict() for key, score in sorted(self.by_type.items())},
            "by_channel": {key: score.to_dict() for key, score in sorted(self.by_channel.items())},
            "not_extracted": self.not_extracted,
            "fuzzy_matches": self.fuzzy_matches,
            "uncertain_rows": self.uncertain_rows,
            "false_positive_types": dict(sorted(self.false_positive_types.items())),
        }


def evaluate_document(
    document: Document, entities: Sequence[PIIEntity], rows: Sequence[GroundTruthRow], fuzzy: bool = True,
) -> DocumentEvaluation:
    """Score detections against ground truth rows for one extracted document.

    Recall: share of ground truth occurrences overlapped by any detection.
    Residual: occurrences with any letter or digit left outside detected spans.
    Precision: detections overlapping a certain ground truth occurrence, over all
    detections except those overlapping only uncertain rows.
    """
    pages = build_page_texts(document)
    occurrences = locate_ground_truth(rows, pages, fuzzy=fuzzy)
    spans = entity_page_spans(entities, pages)

    overall, by_type, by_channel = Score(), {}, {}
    for occurrence in occurrences:
        page_spans = spans.get(occurrence.page, [])
        if occurrence.extracted:
            text = pages[occurrence.page].text
            occurrence.detected = any(s[0] < occurrence.end and s[1] > occurrence.start for s in page_spans)
            occurrence.fully_redacted = _covered(text, occurrence.start, occurrence.end, page_spans)
        if occurrence.row.uncertain:
            continue
        for score in (overall, by_type.setdefault(occurrence.row.entity_type, Score()),
                      by_channel.setdefault(occurrence.channel, Score())):
            score.occurrences += 1
            score.detected += occurrence.detected
            score.residual += not occurrence.fully_redacted

    false_positive_types: Counter[str] = Counter()
    for page, page_spans in spans.items():
        page_occurrences = [o for o in occurrences if o.page == page and o.extracted]
        for start, end, entity in page_spans:
            overlapping = [o for o in page_occurrences if o.start < end and o.end > start]
            detected_type = DETECTED_TYPE_MAP.get(entity.entity_type, entity.entity_type)
            type_score = by_type.setdefault(detected_type, Score())
            overall.detections += 1
            type_score.detections += 1
            if any(not o.row.uncertain for o in overlapping):
                overall.true_positives += 1
                type_score.true_positives += 1
            elif not overlapping:
                overall.false_positives += 1
                type_score.false_positives += 1
                false_positive_types[detected_type] += 1

    return DocumentEvaluation(
        overall=overall, by_type=by_type, by_channel=by_channel,
        not_extracted=sum(not o.extracted and not o.row.uncertain for o in occurrences),
        fuzzy_matches=sum(o.fuzzy for o in occurrences),
        uncertain_rows=sum(row.uncertain for row in rows),
        false_positive_types=dict(false_positive_types),
    )
