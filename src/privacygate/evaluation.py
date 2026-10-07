"""Evaluation and benchmarking metrics for PII detection, redaction, and structure retention."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from privacygate.models import ContentBlock, PIIEntity


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
