"""Before/after reporting and the app's benchmark tab (synthetic report data only)."""

import importlib.util
import json
from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

from privacygate.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


def _compare_module():
    spec = importlib.util.spec_from_file_location("compare_results", ROOT / "scripts" / "compare_results.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _score(recall, precision, residual, occurrences=10):
    return {"occurrences": occurrences, "detected": round(recall * occurrences), "residual": residual,
            "detections": 10, "true_positives": 8, "false_positives": 2, "recall": recall,
            "precision": precision, "f1": 2 * recall * precision / (recall + precision),
            "residual_rate": residual / occurrences}


def _report(label, recall, precision, residual, gate):
    item = {"file": "sample.docx", "seconds": 1.0, "redaction_structure_preservation": 1.0, "gate_single_pass": gate,
            "gate_multi_pass": gate, "overall": _score(recall, precision, residual),
            "by_channel": {"native": _score(recall, precision, residual)}, "by_type": {},
            "not_extracted": 0, "fuzzy_matches": 0, "uncertain_rows": 0, "false_positive_types": {},
            "blocks_by_method": {"docx_native": 3}, "ground_truth_rows": 10,
            "extraction_fidelity": {"kind": "xml_reference", "character_coverage": 0.987, "reading_order": 0.95,
                                    "table_cells": 0.9, "reference_paragraphs": 40, "located_paragraphs": 38,
                                    "reference_cells": 10}}
    return {"label": label, "date": "2026-10-08", "platform": "test", "spacy_model": "en_core_web_sm",
            "omp_thread_limit": "1", "files": [item], "total": _score(recall, precision, residual)}


def test_comparison_markdown_and_chart(tmp_path):
    module = _compare_module()
    before = _report("before", 0.5, 0.4, 5, "BLOCKED")
    after = _report("after", 0.9, 0.8, 1, "APPROVED")
    text = module.comparison_markdown(before, after, "chart.png", "note")
    assert "50.0% → **90.0%** (+40.0 pt)" in text
    assert "BLOCKED → APPROVED" in text
    assert "was APPROVED by the gate" in text and "1 ground-truth occurrence(s)" in text
    chart = tmp_path / "chart.png"
    module.draw_chart(before, after, chart)
    with Image.open(chart) as image:
        assert image.width == 1800 and image.height > 600


def test_benchmark_tab_shows_measured_numbers_not_constants(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "results_after.json").write_text(
        json.dumps(_report("synthetic run", 0.875, 0.625, 2, "BLOCKED")), encoding="utf-8")
    result = run_pipeline(ROOT / "tests" / "fixtures" / "native.pdf")
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=60)
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Recall (all files)"] == "87.5%"
    assert metrics["Precision (all files)"] == "62.5%"
    assert metrics["Residual PII rate"] == "20.0%"
    # The per-document section computes its own values; the old constant cards are gone.
    assert "Residual PII Leakage" not in metrics and "Deterministic Overlap Rate" not in metrics
    assert "Redaction structure preservation" in metrics  # computed for the current document
    tables = [table.value for table in app.dataframe]
    fidelity = next(table for table in tables if "Character coverage" in table.columns)
    assert list(fidelity["Character coverage"]) == ["98.7%"] and list(fidelity["Table cells"]) == ["90.0%"]
    assert any("Character coverage" in str(block.value) and "OCR CER" in str(block.value) for block in app.markdown)


def test_benchmark_tab_without_results_shows_how_to_measure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_pipeline(ROOT / "tests" / "fixtures" / "native.pdf")
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["pipeline_result"] = result
    app.run(timeout=60)
    assert not app.exception
    assert any("No benchmark results found" in str(info.value) for info in app.info)


def test_no_hardcoded_quality_claims_in_app_or_readme():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for claim in ('"100%"', '"0.0%"', "Guarantee", "Zero Residual", "never sent downstream"):
        assert claim not in app_source
    for claim in ("Zero-PII", "zero raw PII", "125 automated", "en_core_web_lg"):
        assert claim not in readme
