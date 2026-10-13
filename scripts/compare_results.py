"""Before/after comparison of two scripts/evaluate.py JSON reports, as Markdown and a PNG chart.

Usage:
    uv run python scripts/compare_results.py \
        --before eval/results_before.json --after eval/results_after.json \
        --out eval/results_after.md --chart eval/results_chart.png --note "measured on ..."

The Markdown starts with the before/after tables and the chart, followed by
the full "after" report. Only counts and rates are written, never PII values.
The chart is drawn with Pillow (already a project dependency): three panels
(recall, precision, residual PII rate), before and after bars per file.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

# Categorical slots 1-2 of the reference palette, validated for CVD separation and
# contrast on the light surface (scripts/validate_palette.js, light mode: all checks pass).
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
BEFORE_COLOR = "#eb6834"
AFTER_COLOR = "#2a78d6"
PANELS = (("recall", "Recall (higher is better)"), ("precision", "Precision (higher is better)"),
          ("residual_rate", "Residual PII rate (lower is better)"))


def _load_render_markdown():
    spec = importlib.util.spec_from_file_location("evaluate_script", ROOT / "scripts" / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_markdown


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _delta(before: float | None, after: float | None) -> str:
    if before is None or after is None:
        return ""
    return f"{(after - before) * 100:+.1f} pt"


def _short(name: str) -> str:
    stem = Path(name).stem.replace("Cadence_", "").replace("_", " ")
    return f"{stem[:28]} ({Path(name).suffix[1:].upper()})"


def comparison_markdown(before: dict, after: dict, chart_name: str | None, note: str) -> str:
    files_before = {item["file"]: item for item in before["files"]}
    lines = [
        "# PrivacyGate benchmark: before vs after",
        "",
        f"Before: {before['label']} ({before['date']}). After: {after['label']} ({after['date']}).",
        f"Both measured with `scripts/evaluate.py` against `eval/ground_truth/` (spaCy `{after['spacy_model']}`)."
        + (f" {note}" if note else ""),
        "",
        "| File | Recall | Precision | F1 | Residual PII rate | Gate 1 pass | Gate 2 passes |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in after["files"]:
        old = files_before.get(item["file"])
        if old is None:
            continue
        o, n = old["overall"], item["overall"]
        lines.append(
            f"| {item['file']} | {_pct(o['recall'])} → **{_pct(n['recall'])}** ({_delta(o['recall'], n['recall'])}) "
            f"| {_pct(o['precision'])} → **{_pct(n['precision'])}** ({_delta(o['precision'], n['precision'])}) "
            f"| {_pct(o['f1'])} → **{_pct(n['f1'])}** "
            f"| {_pct(o['residual_rate'])} → **{_pct(n['residual_rate'])}** "
            f"| {old['gate_single_pass']} → {item['gate_single_pass']} "
            f"| {old['gate_multi_pass']} → {item['gate_multi_pass']} |"
        )
    tb, ta = before["total"], after["total"]
    lines.append(
        f"| **All files** | {_pct(tb['recall'])} → **{_pct(ta['recall'])}** | {_pct(tb['precision'])} → "
        f"**{_pct(ta['precision'])}** | {_pct(tb['f1'])} → **{_pct(ta['f1'])}** | {_pct(tb['residual_rate'])} → "
        f"**{_pct(ta['residual_rate'])}** | | |"
    )
    lines += ["", "## Recall by source channel", "", "| File | Channel | Before | After |", "|---|---|---|---|"]
    for item in after["files"]:
        old = files_before.get(item["file"], {"by_channel": {}})
        for channel in ("native", "ocr", "image"):
            o, n = old["by_channel"].get(channel), item["by_channel"].get(channel)
            if o or n:
                lines.append(
                    f"| {item['file']} | {channel} | {_pct(o['recall']) if o else '—'} "
                    f"({o['detected'] if o else 0}/{o['occurrences'] if o else 0}) | {_pct(n['recall']) if n else '—'} "
                    f"({n['detected'] if n else 0}/{n['occurrences'] if n else 0}) |"
                )
    lines += ["", "Image-channel counts can differ between runs: a value that was never extracted counts as one "
              "missed occurrence, while extracted image text counts every occurrence."]
    lines += ["", "## Recall by location type", "",
              "Body text, tables, unlabelled narrative prose and image-only content (ground truth "
              "`location_type`). Reports made before this split existed show —.", "",
              "| File | Location | Before | After |", "|---|---|---|---|"]
    for item in after["files"]:
        old = files_before.get(item["file"], {})
        for location in ("body", "table", "prose", "image"):
            o, n = old.get("by_location", {}).get(location), item.get("by_location", {}).get(location)
            if o or n:
                lines.append(
                    f"| {item['file']} | {location} | "
                    + (f"{_pct(o['recall'])} ({o['detected']}/{o['occurrences']})" if o else "—")
                    + " | " + (f"{_pct(n['recall'])} ({n['detected']}/{n['occurrences']})" if n else "—") + " |"
                )
    caveats = [
        f"- **{item['file']}** was APPROVED by the gate ({item['gate_single_pass']} / {item['gate_multi_pass']}) "
        f"while {item['overall']['residual']} ground-truth occurrence(s) remained unredacted."
        for item in after["files"]
        if "APPROVED" in (item["gate_single_pass"], item["gate_multi_pass"]) and item["overall"]["residual"]
    ]
    if caveats:
        lines += ["", "## Read with care", "", *caveats]
    lines += ["", "## Runtime", "", "| File | Before | After |", "|---|---|---|"]
    for item in after["files"]:
        old = files_before.get(item["file"])
        if old:
            lines.append(f"| {item['file']} | {old['seconds']} s | {item['seconds']} s |")
    if chart_name:
        lines += ["", f"![Before vs after: recall, precision and residual PII rate per file]({chart_name})"]
    return "\n".join(lines) + "\n"


def _font(size: int, bold: bool = False):
    for name in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_chart(before: dict, after: dict, path: Path) -> None:
    """Three small-multiple panels; one shared 0-100% axis per panel; before/after bars per file."""
    files_before = {item["file"]: item for item in before["files"]}
    files = [item for item in after["files"] if item["file"] in files_before]
    width, panel_height, margin = 1800, 300, 40
    header = 120
    height = header + len(PANELS) * (panel_height + 30) + 40
    image = Image.new("RGB", (width, height), SURFACE)
    draw = ImageDraw.Draw(image)
    title, small, tiny = _font(34, True), _font(22), _font(19)
    # Label column sized to the widest file label so text never runs into the bars.
    label_width = int(max(draw.textlength(_short(item["file"]), font=small) for item in files)) + 24
    draw.text((margin, 24), "PrivacyGate on the Cadence case-study files: before vs after", font=title,
              fill=TEXT_PRIMARY)
    # Legend (two series): swatch + label, text in text tokens.
    lx = margin
    for label, color in (("Before fixes", BEFORE_COLOR), ("After fixes", AFTER_COLOR)):
        draw.rounded_rectangle((lx, 78, lx + 22, 100), radius=4, fill=color)
        draw.text((lx + 32, 76), label, font=small, fill=TEXT_SECONDARY)
        lx += 230
    plot_x0, plot_x1 = margin + label_width, width - 140
    bar_h, gap, group_gap = 26, 2, 22

    for index, (key, label) in enumerate(PANELS):
        top = header + index * (panel_height + 30)
        draw.text((margin, top), label, font=_font(26, True), fill=TEXT_PRIMARY)
        y = top + 50
        axis_top, axis_bottom = y - 6, y + len(files) * (2 * bar_h + gap + group_gap)
        for tick in (0, 0.25, 0.5, 0.75, 1.0):
            x = plot_x0 + tick * (plot_x1 - plot_x0)
            draw.line((x, axis_top, x, axis_bottom), fill=GRID, width=1)
            draw.text((x - 18, axis_bottom + 4), f"{int(tick * 100)}%", font=tiny, fill=TEXT_SECONDARY)
        for item in files:
            old = files_before[item["file"]]["overall"].get(key)
            new = item["overall"].get(key)
            draw.text((margin, y + bar_h - 12), _short(item["file"]), font=small, fill=TEXT_PRIMARY)
            for value, color in ((old, BEFORE_COLOR), (new, AFTER_COLOR)):
                value = value or 0.0
                x1 = plot_x0 + max(value, 0.004) * (plot_x1 - plot_x0)
                # Thin bar, square at the baseline, 4px rounded data end.
                draw.rounded_rectangle((plot_x0, y, x1, y + bar_h), radius=4, fill=color)
                draw.rectangle((plot_x0, y, min(plot_x0 + 4, x1), y + bar_h), fill=color)
                draw.text((x1 + 8, y + 2), _pct(value), font=tiny, fill=TEXT_PRIMARY)
                y += bar_h + gap
            y += group_gap
    image.save(path, format="PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", type=Path, default=ROOT / "eval" / "results_before.json")
    parser.add_argument("--after", type=Path, default=ROOT / "eval" / "results_after.json")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results_after.md")
    parser.add_argument("--chart", type=Path, default=ROOT / "eval" / "results_chart.png")
    parser.add_argument("--note", default="", help="Extra provenance line, e.g. which commits were measured.")
    args = parser.parse_args()

    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    draw_chart(before, after, args.chart)
    comparison = comparison_markdown(before, after, args.chart.name, args.note)
    detail = _load_render_markdown()(after).split("\n", 1)[1]  # drop the report's own title line
    args.out.write_text(comparison + "\n---\n\n# Full report (after)\n" + detail, encoding="utf-8")
    print(f"Wrote {args.out} and {args.chart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
