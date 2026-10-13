"""The held-out benchmark stays held out: its values appear nowhere else in the repository."""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = ROOT / "eval" / "holdout"


def _holdout_rows():
    rows = []
    for path in sorted((HOLDOUT / "ground_truth").glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as handle:
            rows += list(csv.DictReader(handle))
    return rows


def test_holdout_ground_truth_points_at_existing_files():
    rows = _holdout_rows()
    assert len(rows) >= 30
    assert {row["file"] for row in rows} == {path.name for path in (HOLDOUT / "docs").iterdir()}


def test_holdout_values_are_not_used_in_code_tests_or_case_study_labels():
    values = {row["value"] for row in _holdout_rows()}
    sources = [path for folder in ("src", "tests", "eval/ground_truth") for path in (ROOT / folder).rglob("*")
               if path.is_file() and path.suffix in {".py", ".csv", ".md", ".txt"} and path.name != "test_holdout.py"]
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="ignore")
        leaked = sorted(value for value in values if value in text)
        assert not leaked, f"{path.relative_to(ROOT)} contains held-out values {leaked}"
