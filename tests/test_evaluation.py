"""Tests for evaluation metrics and ground truth benchmarks."""

import json
from pathlib import Path

import pytest
from privacygate.evaluation import (
    BenchmarkResult,
    GroundTruthItem,
    calculate_metrics,
    evaluate_detection,
    measure_redaction_structure_preservation,
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


def test_redaction_structure_preservation_high() -> None:
    orig = [
        ContentBlock(block_id="b1", text="Header", page_number=1),
        ContentBlock(block_id="b2", text="Body text", page_number=1, paragraph_number=2),
    ]
    sanitized = [
        ContentBlock(block_id="b1", text="Header", page_number=1),
        ContentBlock(block_id="b2", text="Body [REDACTED]", page_number=1, paragraph_number=2),
    ]

    retention = measure_redaction_structure_preservation(orig, sanitized)
    assert retention == 1.0  # every block kept in place


def test_historical_results_are_safe_aggregate_evaluation_evidence() -> None:
    report_path = Path(__file__).parents[1] / "eval" / "results_baseline_d85b251.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["git_commit"] == "d85b2519cf5b35430deb17cb053792bfef6b9552"
    assert len(report["files"]) == 3
    assert {item["file"] for item in report["files"]} == {
        "Cadence_Financial_Group_Organizational_Pack.pptx",
        "Cadence_Group_Risk_Management_Policy__v6.0.pdf",
        "Cadence_TPRM_Training.docx",
    }
    assert {"recall", "precision", "f1", "residual_rate"} <= report["total"].keys()
    for item in report["files"]:
        assert {"detected_count", "redacted_count", "residual_detection_count", "passes_executed"} <= item["pipeline"].keys()
        assert {"pages", "embedded_images", "warning_count"} <= item["extraction_coverage"].keys()
        assert "value" not in item
