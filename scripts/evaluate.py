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
import subprocess
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
    measure_redaction_structure_preservation,
)
from privacygate.pipeline import run_pipeline  # noqa: E402
from privacygate.structure import load_transcriptions, office_fidelity, scanned_fidelity  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "eval" / "reference"
CHANNELS = ("native", "ocr", "image")
LOCATIONS = ("body", "table", "prose", "image")


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def add_scores(target: Score, source: Score) -> None:
    for name in ("occurrences", "detected", "residual", "detections", "true_positives", "false_positives"):
        setattr(target, name, getattr(target, name) + getattr(source, name))


def score_from_dict(values: dict) -> Score:
    return Score(**{k: values[k] for k in (
        "occurrences", "detected", "residual", "detections", "true_positives", "false_positives")})


def extraction_fidelity(source: Path, document) -> dict | None:
    """XML-reference scores for DOCX/PPTX; transcription scores for a PDF with eval/reference/<stem>/."""
    if source.suffix.lower() in (".docx", ".pptx"):
        return office_fidelity(source, document).to_dict()
    transcriptions = REFERENCE_DIR / source.stem
    if transcriptions.is_dir():
        return scanned_fidelity(document, load_transcriptions(transcriptions))
    return None


def redaction_preservation(item: dict) -> float | None:
    """Reports written before the rename call it "structure_retention"."""
    return item.get("redaction_structure_preservation", item.get("structure_retention"))

def status_counts(entries: object, statuses: tuple[str, ...]) -> dict[str, int]:
    """Count only fixed operational status values; never report source metadata."""
    counts = dict.fromkeys(statuses, 0)
    if type(entries) is list:
        for entry in entries:
            status = entry.get("status") if type(entry) is dict else None
            if status in counts:
                counts[status] += 1
    return counts


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
    evaluation = evaluate_document(result.document, result.entities, rows, sanitized_document=result.sanitized_document)
    methods: dict[str, int] = defaultdict(int)
    for block in result.document.blocks:
        methods[block.extraction_method or "unknown"] += 1
    metadata = result.document.metadata
    page_statuses = status_counts(metadata.get("page_report"), ("native", "ocr", "failed"))
    image_statuses = status_counts(metadata.get("embedded_images"), (
        "ocr", "failed", "skipped_tiny", "skipped_vector",
    ))
    return {
        "file": source.name,
        "ground_truth_rows": len(rows),
        "seconds": round(seconds, 1),
        "blocks_by_method": dict(sorted(methods.items())),
        "gate_single_pass": single_pass,
        "gate_multi_pass": result.validation.status,
        "redaction_structure_preservation": round(
            measure_redaction_structure_preservation(result.document.blocks, result.sanitized_document.blocks), 4),
        "extraction_fidelity": extraction_fidelity(source, result.document),
        "pipeline": {
            "detected_count": len(result.entities),
            "redacted_count": result.audit_report.redacted_count,
            "residual_detection_count": len(result.validation.residual_entities),
            "passes_executed": result.passes_executed,
        },
        "extraction_coverage": {
            "pages": page_statuses,
            "embedded_images": {
                "attempted": image_statuses["ocr"] + image_statuses["failed"],
                "succeeded": image_statuses["ocr"],
                "failed": image_statuses["failed"],
                "skipped": image_statuses["skipped_tiny"] + image_statuses["skipped_vector"],
                "skipped_tiny": image_statuses["skipped_tiny"],
                "skipped_vector": image_statuses["skipped_vector"],
            },
            "warning_count": len(metadata.get("extraction_warnings", [])),
        },
        **evaluation.to_dict(),
    }


FIDELITY_DEFINITIONS = [
    "- Character coverage: share of the reference's letters and digits found in the extracted text "
    "(DOCX/PPTX; reference read from the file's XML).",
    "- Reading order: of consecutive reference paragraphs (or transcribed lines) found in the extraction, "
    "the share found in the same order.",
    "- Table cells: share of non-empty reference table cells extracted with the same text at the same "
    "row and column.",
    "- OCR CER: character error rate of the OCR'd text against hand transcriptions of scanned pages "
    "(`eval/reference/`), lower is better.",
]


def extraction_fidelity_lines(files: list[dict]) -> list[str]:
    rows = [item for item in files if item.get("extraction_fidelity")]
    if not rows:
        return []
    lines = ["", "## Extraction fidelity", "",
             "How faithfully extraction captures the source file, against references built without the "
             "extractors (see `eval/README.md`).", "", *FIDELITY_DEFINITIONS, "",
             "| File | Reference | Character coverage | Reading order | Table cells | OCR CER |",
             "|---|---|---|---|---|---|"]
    for item in rows:
        fidelity = item["extraction_fidelity"]
        if fidelity["kind"] == "xml_reference":
            lines.append(
                f"| {item['file']} | XML: {fidelity['reference_paragraphs']} paragraphs, "
                f"{fidelity['reference_cells']} table cells | {percent(fidelity['character_coverage'])} | "
                f"{percent(fidelity['reading_order'])} | {percent(fidelity['table_cells'])} | — |"
            )
        else:
            pages = ", ".join(str(page["page"]) for page in fidelity["pages"])
            lines.append(
                f"| {item['file']} | hand transcription, pages {pages} | — | "
                f"{percent(fidelity['line_order'])} | — | {percent(fidelity['cer'])} |"
            )
    for item in rows:
        fidelity = item["extraction_fidelity"]
        if fidelity["kind"] == "transcription":
            lines += ["", f"Transcribed pages of {item['file']}: " + "; ".join(
                f"page {page['page']} CER {percent(page['cer'])}, line order {percent(page['line_order'])} "
                f"({page['found_lines']}/{page['reference_lines']} lines found)" for page in fidelity["pages"]) + "."]
    return lines


def render_markdown(report: dict) -> str:
    lines = [
        f"# PrivacyGate benchmark — {report['label']}",
        "",
        f"Generated {report['date']} with `scripts/evaluate.py` on {report['platform']}; "
        f"commit `{report['git_commit']}`; spaCy model `{report['spacy_model']}`; "
        f"OMP_THREAD_LIMIT={report['omp_thread_limit']}.",
        "",
        "Recall counts every occurrence of a ground truth value in the extracted text "
        "(a value that was never extracted counts as one missed occurrence). Residual = "
        "occurrences with any character left unredacted. Precision counts detections; detections "
        "that only overlap rows marked uncertain are excluded. See `eval/README.md`.",
        "",
        "## Summary",
        "",
        "| File | Recall | Precision | F1 | Residual PII rate | Redaction structure preservation | "
        "Gate (1 pass) | Gate (2 passes) | Runtime |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in report["files"]:
        o = item["overall"]
        lines.append(
            f"| {item['file']} | {percent(o['recall'])} ({o['detected']}/{o['occurrences']}) | "
            f"{percent(o['precision'])} ({o['true_positives']}/{o['true_positives'] + o['false_positives']}) | "
            f"{percent(o['f1'])} | {percent(o['residual_rate'])} ({o['residual']}) | "
            f"{percent(redaction_preservation(item))} | {item['gate_single_pass']} | {item['gate_multi_pass']} | "
            f"{item['seconds']} s |"
        )
    total = report["total"]
    lines.append(
        f"| **All files** | **{percent(total['recall'])}** | **{percent(total['precision'])}** | "
        f"**{percent(total['f1'])}** | **{percent(total['residual_rate'])}** | | | | |"
    )

    lines += ["", "Redaction structure preservation: share of extracted blocks that sanitization kept in place "
              "(same id, location, non-empty text); it does not measure extraction."]
    lines += extraction_fidelity_lines(report["files"])

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

    lines += ["", "## Recall by location type", "",
              "Where the value sits in the source (ground truth `location_type`): body text, tables, "
              "unlabelled narrative prose, or inside images/figures.", "",
              "| File | " + " | ".join(LOCATIONS) + " |", "|---|" + "---|" * len(LOCATIONS)]
    for item in report["files"]:
        cells = []
        for location in LOCATIONS:
            score = item.get("by_location", {}).get(location)
            cells.append("—" if not score else f"{percent(score['recall'])} ({score['detected']}/{score['occurrences']})")
        lines.append(f"| {item['file']} | " + " | ".join(cells) + " |")

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
        coverage = item["extraction_coverage"]
        images = coverage["embedded_images"]
        lines += ["", f"False positives by detected type: {fp}. Ground truth rows: {item['ground_truth_rows']} "
                  f"({item['uncertain_rows']} uncertain). Fuzzy (OCR-damaged) matches: {item['fuzzy_matches']}. "
                  f"Blocks by extraction method: "
                  + ", ".join(f"{k} {v}" for k, v in item["blocks_by_method"].items()) + ".",
                  "Pipeline counts: " + ", ".join(
                      f"{key.replace('_', ' ')} {value}" for key, value in item["pipeline"].items()
                  ) + ".",
                  "Extraction coverage: pages " + ", ".join(
                      f"{key} {value}" for key, value in coverage["pages"].items()
                  ) + "; embedded images attempted {attempted}, succeeded {succeeded}, failed {failed}, "
                  "skipped {skipped} (tiny {skipped_tiny}, vector {skipped_vector}); warnings {warnings}.".format(
                      **images, warnings=coverage["warning_count"],
                  )]
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
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False,
        ).stdout.strip() or "unavailable",
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
