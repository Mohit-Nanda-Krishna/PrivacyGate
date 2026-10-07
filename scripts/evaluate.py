"""Benchmark the pipeline against eval/ground_truth/*.csv and write a results report.

Usage:
    uv run python scripts/evaluate.py --out eval/results_before.md

Runs every ground truth file through the full pipeline (two passes, so both the
single-pass and multi-pass gate decisions are reported) and writes a Markdown
report plus a JSON file with the same numbers. Reports contain counts and
rates only, never document text or PII values. Tesseract runs single-threaded
(OMP_THREAD_LIMIT=1) unless the variable is already set.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from privacygate.detection import presidio_detector  # noqa: E402
from privacygate.evaluation import (  # noqa: E402
    Score,
    evaluate_document,
    load_ground_truth,
    measure_structure_retention,
)
from privacygate.pipeline import run_pipeline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHANNELS = ("native", "ocr", "image")


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def add_scores(target: Score, source: Score) -> None:
    for name in ("occurrences", "detected", "residual", "detections", "true_positives", "false_positives"):
        setattr(target, name, getattr(target, name) + getattr(source, name))


def score_from_dict(values: dict) -> Score:
    return Score(**{k: values[k] for k in (
        "occurrences", "detected", "residual", "detections", "true_positives", "false_positives")})


def evaluate_file(csv_path: Path, docs_dir: Path) -> dict:
    rows = load_ground_truth(csv_path)
    files = {row.file for row in rows}
    if len(files) != 1:
        raise ValueError(f"{csv_path.name}: expected rows for exactly one file, found {sorted(files)}")
    source = docs_dir / files.pop()
    started = time.perf_counter()
    result = run_pipeline(source, max_passes=2)
    seconds = time.perf_counter() - started
    single_pass = "APPROVED" if result.passes_executed == 1 and result.validation.status == "APPROVED" else "BLOCKED"
    evaluation = evaluate_document(result.document, result.entities, rows)
    methods: dict[str, int] = defaultdict(int)
    for block in result.document.blocks:
        methods[block.extraction_method or "unknown"] += 1
    return {
        "file": source.name,
        "ground_truth_rows": len(rows),
        "seconds": round(seconds, 1),
        "blocks_by_method": dict(sorted(methods.items())),
        "gate_single_pass": single_pass,
        "gate_multi_pass": result.validation.status,
        "structure_retention": round(
            measure_structure_retention(result.document.blocks, result.sanitized_document.blocks), 4),
        **evaluation.to_dict(),
    }


def render_markdown(report: dict) -> str:
    lines = [
        f"# PrivacyGate benchmark — {report['label']}",
        "",
        f"Generated {report['date']} with `scripts/evaluate.py` on {report['platform']}; "
        f"spaCy model `{report['spacy_model']}`; OMP_THREAD_LIMIT={report['omp_thread_limit']}.",
        "",
        "Recall counts every occurrence of a ground truth value in the extracted text "
        "(a value that was never extracted counts as one missed occurrence). Residual = "
        "occurrences with any character left unredacted. Precision counts detections; detections "
        "that only overlap rows marked uncertain are excluded. See `eval/README.md`.",
        "",
        "## Summary",
        "",
        "| File | Recall | Precision | F1 | Residual PII rate | Structure retention | "
        "Gate (1 pass) | Gate (2 passes) | Runtime |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in report["files"]:
        o = item["overall"]
        lines.append(
            f"| {item['file']} | {percent(o['recall'])} ({o['detected']}/{o['occurrences']}) | "
            f"{percent(o['precision'])} ({o['true_positives']}/{o['true_positives'] + o['false_positives']}) | "
            f"{percent(o['f1'])} | {percent(o['residual_rate'])} ({o['residual']}) | "
            f"{percent(item['structure_retention'])} | {item['gate_single_pass']} | {item['gate_multi_pass']} | "
            f"{item['seconds']} s |"
        )
    total = report["total"]
    lines.append(
        f"| **All files** | **{percent(total['recall'])}** | **{percent(total['precision'])}** | "
        f"**{percent(total['f1'])}** | **{percent(total['residual_rate'])}** | | | | |"
    )

    lines += ["", "## Recall by source channel", "",
              "native = digitally native text, ocr = scanned page text, image = values inside "
              "embedded images/figures (image-only).", "",
              "| File | " + " | ".join(CHANNELS) + " | Not extracted at all |",
              "|---|" + "---|" * (len(CHANNELS) + 1)]
    for item in report["files"]:
        cells = []
        for channel in CHANNELS:
            score = item["by_channel"].get(channel)
            cells.append("—" if not score else f"{percent(score['recall'])} ({score['detected']}/{score['occurrences']})")
        lines.append(f"| {item['file']} | " + " | ".join(cells) + f" | {item['not_extracted']} |")

    for item in report["files"]:
        lines += ["", f"## {item['file']}", "",
                  "| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |",
                  "|---|---|---|---|---|---|---|"]
        for entity_type, score in item["by_type"].items():
            lines.append(
                f"| {entity_type} | {score['occurrences']} | {percent(score['recall'])} | {score['residual']} | "
                f"{score['detections']} | {percent(score['precision'])} | {percent(score['f1'])} |"
            )
        fp = ", ".join(f"{k} {v}" for k, v in item["false_positive_types"].items()) or "none"
        lines += ["", f"False positives by detected type: {fp}. Ground truth rows: {item['ground_truth_rows']} "
                  f"({item['uncertain_rows']} uncertain). Fuzzy (OCR-damaged) matches: {item['fuzzy_matches']}. "
                  f"Blocks by extraction method: "
                  + ", ".join(f"{k} {v}" for k, v in item["blocks_by_method"].items()) + "."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ground-truth", type=Path, default=ROOT / "eval" / "ground_truth")
    parser.add_argument("--docs", type=Path, default=ROOT / "docs")
    parser.add_argument("--out", type=Path, required=True, help="Markdown report path; JSON is written next to it.")
    parser.add_argument("--label", default=None, help="Report title, defaults to the output file stem.")
    parser.add_argument("--only", nargs="*", default=None, help="Evaluate only ground truth files with these stems.")
    parser.add_argument("--spacy-model", default=None,
                        help="Override the spaCy model for this run only (must already be installed).")
    args = parser.parse_args()

    if args.spacy_model:
        presidio_detector.SPACY_MODEL = args.spacy_model
        presidio_detector.get_analyzer.cache_clear()

    csv_files = sorted(args.ground_truth.glob("*.csv"))
    if args.only:
        csv_files = [path for path in csv_files if path.stem in args.only]
    if not csv_files:
        print("No ground truth files found.", file=sys.stderr)
        return 1

    files = []
    for csv_path in csv_files:
        print(f"Evaluating {csv_path.stem} ...", flush=True)
        files.append(evaluate_file(csv_path, args.docs))
        o = files[-1]["overall"]
        print(f"  recall {percent(o['recall'])}, precision {percent(o['precision'])}, "
              f"residual {percent(o['residual_rate'])}, {files[-1]['seconds']} s", flush=True)

    total = Score()
    for item in files:
        add_scores(total, score_from_dict(item["overall"]))
    report = {
        "label": args.label or args.out.stem.replace("_", " "),
        "date": date.today().isoformat(),
        "platform": f"{platform.system()} {platform.version()}, Python {platform.python_version()}",
        "spacy_model": presidio_detector.SPACY_MODEL,
        "omp_thread_limit": os.environ.get("OMP_THREAD_LIMIT", ""),
        "files": files,
        "total": total.to_dict(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(report), encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} and {args.out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
