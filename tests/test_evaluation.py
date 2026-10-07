"""Tests for evaluation metrics and ground truth benchmarks."""

import pytest
from privacygate.evaluation import (
    BenchmarkResult,
    GroundTruthItem,
    calculate_metrics,
    evaluate_detection,
    measure_structure_retention,
)
from privacygate.models import ContentBlock, PIIEntity


def test_calculate_metrics_perfect() -> None:
    res = calculate_metrics(tp=10, fp=0, fn=0, residual_count=0)
    assert res.precision == 1.0
    assert res.recall == 1.0
    assert res.f1_score == 1.0
    assert res.residual_rate == 0.0


def test_calculate_metrics_partial() -> None:
    # 8 TP, 2 FP, 2 FN
    res = calculate_metrics(tp=8, fp=2, fn=2, residual_count=1)
    assert res.precision == 8 / 10  # 0.80
    assert res.recall == 8 / 10     # 0.80
    assert res.f1_score == pytest.approx(0.80)
    assert res.residual_rate == pytest.approx(0.10)


def test_evaluate_detection_ground_truth() -> None:
    block_id = "block_eval_1"
    text = "Account Manager Alice Smith (EMP-9921) reached via alice@cadence.com."
    block_texts = {block_id: text}

    detected = [
        PIIEntity(entity_type="PERSON", start=16, end=27, confidence=0.9, detector="presidio", block_id=block_id),
        PIIEntity(entity_type="EMPLOYEE_ID", start=29, end=37, confidence=0.95, detector="custom_enterprise", block_id=block_id),
        PIIEntity(entity_type="EMAIL", start=51, end=68, confidence=1.0, detector="regex", block_id=block_id),
    ]

    truth = [
        GroundTruthItem(entity_type="PERSON", expected_text="Alice Smith"),
        GroundTruthItem(entity_type="EMPLOYEE_ID", expected_text="EMP-9921"),
        GroundTruthItem(entity_type="EMAIL", expected_text="alice@cadence.com"),
    ]

    benchmark = evaluate_detection(detected, truth, block_texts)
    assert benchmark.true_positives == 3
    assert benchmark.false_negatives == 0
    assert benchmark.false_positives == 0
    assert benchmark.recall == 1.0
    assert benchmark.precision == 1.0
    assert benchmark.f1_score == 1.0


def test_measure_structure_retention_high() -> None:
    orig = [
        ContentBlock(block_id="b1", text="Header", page_number=1),
        ContentBlock(block_id="b2", text="Body text", page_number=1, paragraph_number=2),
    ]
    sanitized = [
        ContentBlock(block_id="b1", text="Header", page_number=1),
        ContentBlock(block_id="b2", text="Body [REDACTED]", page_number=1, paragraph_number=2),
    ]

    retention = measure_structure_retention(orig, sanitized)
    assert retention == 1.0  # 100% structure retention
