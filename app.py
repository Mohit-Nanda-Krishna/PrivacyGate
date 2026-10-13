"""PrivacyGate — Pre-LLM Privacy Firewall for Business Documents.

Streamlit interactive interface for multi-format document ingestion,
hybrid PII detection, semantic redaction, and fail-closed privacy gating.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
import re
import tempfile
from typing import Any
import pandas as pd
import streamlit as st

from privacygate.audit import audit_report_to_json
from privacygate.detection import DetectionError
from privacygate.extraction import ExtractionError
from privacygate.evaluation import measure_redaction_structure_preservation
from privacygate.models import PIIEntity
from privacygate.derivatives import REVIEW_WATERMARK, redact_pdf
from privacygate.llm import GateRefusedError, build_llm_payload, mock_llm_call
from privacygate.pipeline import run_batch, run_pipeline
from privacygate.risk.classifier import RISK_MAPPING

EVALUATION_RESULTS_PATH = Path(__file__).with_name("eval") / "results_current.json"
BASELINE_RESULTS_PATH = Path(__file__).with_name("eval") / "results_baseline_d85b251.json"

st.set_page_config(
    page_title="PrivacyGate — AI Privacy Firewall",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom header & component styling
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 800;
        color: #1E3A8A;
        margin-bottom: 0.1rem;
        letter-spacing: -0.5px;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
        font-weight: 400;
    }
    .status-badge-approved {
        background-color: #ECFDF5;
        color: #065F46;
        padding: 1rem 1.4rem;
        border-radius: 10px;
        font-weight: 700;
        font-size: 1.25rem;
        text-align: center;
        border: 2px solid #10B981;
        box-shadow: 0 4px 6px -1px rgba(16, 185, 129, 0.1);
    }
    .status-badge-blocked {
        background-color: #FEF2F2;
        color: #991B1B;
        padding: 1rem 1.4rem;
        border-radius: 10px;
        font-weight: 700;
        font-size: 1.25rem;
        text-align: center;
        border: 2px solid #EF4444;
        box-shadow: 0 4px 6px -1px rgba(239, 68, 68, 0.1);
    }
    .preview-card {
        background-color: #FAFAFA;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 1.2rem;
        max-height: 480px;
        overflow-y: auto;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
    }
    .block-tag {
        display: inline-block;
        background-color: #E2E8F0;
        color: #334155;
        font-size: 0.75rem;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        margin-bottom: 6px;
        font-family: monospace;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="main-header">🛡️ PrivacyGate</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Pre-LLM Privacy Firewall for Business Documents — '
    'Detecting, Classifying, and Sanitizing PII before AI processing.</div>',
    unsafe_allow_html=True,
)

# Helper highlighting functions
UI_PLACEHOLDER_PATTERN = re.compile(
    r"(?<!\[)\[(?:" + "|".join(re.escape(name) for name in sorted(set(RISK_MAPPING) | {"PII"}))
    + r")(?:_(?P<number>[0-9]{3,}))?\](?!\])"
)


def load_evaluation_results(path: Path = EVALUATION_RESULTS_PATH) -> dict[str, Any] | None:
    """Load an aggregate benchmark report if it has the expected shape."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return report if type(report) is dict and type(report.get("files")) is list and type(report.get("total")) is dict else None


def percent(value: object) -> str:
    """Format a measured rate without inventing a value for unavailable fields."""
    return f"{value * 100:.1f}%" if type(value) in (int, float) else "Not available"


def highlight_original_block(text: str, block_entities: list[PIIEntity]) -> str:
    """Highlight detected PII in block text with color-coded risk pills."""
    if not block_entities:
        return f"<div style='margin-bottom: 12px;'>{html.escape(text)}</div>"

    sorted_ents = sorted(block_entities, key=lambda e: (e.start, -e.end))
    last_idx = 0
    parts = []
    for e in sorted_ents:
        if e.start < last_idx or e.start >= len(text):
            continue
        parts.append(html.escape(text[last_idx:e.start]))
        entity_val = html.escape(text[e.start:min(e.end, len(text))])

        if e.risk_level == "CRITICAL":
            bg, fg, border = "#FEE2E2", "#991B1B", "#FCA5A5"
        elif e.risk_level == "HIGH":
            bg, fg, border = "#FFEDD5", "#9A3412", "#FDBA74"
        else:
            bg, fg, border = "#FEF9C3", "#854D0E", "#FDE047"

        tooltip = f"{e.entity_type} ({e.risk_level} Risk) | Detector: {e.detector}"
        parts.append(
            f'<mark style="background-color: {bg}; color: {fg}; border: 1px solid {border}; '
            f'padding: 1px 5px; border-radius: 4px; font-weight: 600; font-family: monospace;" '
            f'title="{html.escape(tooltip)}">{entity_val}</mark>'
        )
        last_idx = min(e.end, len(text))

    parts.append(html.escape(text[last_idx:]))
    rendered = "".join(parts).replace("\n", "<br>")
    return f"<div style='margin-bottom: 12px;'>{rendered}</div>"


def highlight_sanitized_block(text: str) -> str:
    """Highlight known generic and numbered placeholders with emerald security badges."""
    escaped = html.escape(text)

    def _replace_placeholder(match: re.Match) -> str:
        token = match.group(0)
        return (
            f'<span style="background-color: #ECFDF5; color: #065F46; border: 1px solid #10B981; '
            f'padding: 1px 5px; border-radius: 4px; font-weight: 700; font-family: monospace;">'
            f'{token}</span>'
        )

    highlighted = UI_PLACEHOLDER_PATTERN.sub(_replace_placeholder, escaped)
    rendered = highlighted.replace("\n", "<br>")
    return f"<div style='margin-bottom: 12px;'>{rendered}</div>"


# Sidebar: System configuration and sample files
with st.sidebar:
    st.header("⚙️ Configuration")
    st.info("Environment: Python 3.11 (Locked uv)\nHybrid Engine: Regex + Presidio + Custom Rules")

    docs_dir = Path("docs")
    sample_options = ["None (Upload Custom File)"]
    sample_files: dict[str, Path] = {}
    if docs_dir.exists():
        for f in sorted(docs_dir.glob("*.*")):
            if f.suffix.lower() in (".pdf", ".docx", ".pptx"):
                sample_options.append(f.name)
                sample_files[f.name] = f

    selected_sample = st.selectbox(
        "Load Pre-Packaged Evidence Artifact:",
        options=sample_options,
        index=0,
    )
    extra_samples = st.multiselect(
        "Add more artifacts to the batch (shared pseudonym tokens):",
        options=[name for name in sample_files if name != selected_sample],
        help="Files processed together share one token session: the same person gets the same "
             "[PERSON_n] token in every file. The token mapping stays in memory only.",
    )

    st.markdown("---")
    st.markdown("**Sanitization Mode:**")
    sanitization_mode = st.radio(
        "Firewall Policy:",
        options=["Strict Fail-Closed (1 Pass)", "Iterative Auto-Clean (Multi-Pass)"],
        index=0,
        help="Strict Fail-Closed performs 1 redaction pass and immediately blocks if residual PII is caught. Iterative Auto-Clean attempts a second cleaning pass on residual entities.",
    )
    max_passes = 2 if "Multi-Pass" in sanitization_mode else 1

    st.markdown("---")
    st.markdown("**Core Security Policy:**")
    st.caption("• Only gate-approved, sanitized text may go downstream\n• Fail-closed on extraction or "
               "validation errors\n• Traceable source coordinates\n• Audit export holds counts, not raw values")

# File selection logic
uploaded_files = st.file_uploader(
    "Upload Business Evidence Document(s)",
    type=["pdf", "docx", "pptx"],
    accept_multiple_files=True,
    help="Supported formats: Digital/Scanned PDF, Microsoft Word DOCX, Microsoft PowerPoint PPTX. "
         "Several files are processed as one batch with shared pseudonym tokens.",
)

# (display name, uploaded file or sample path) in processing order
selected: list[tuple[str, object]] = [(upload.name, upload) for upload in uploaded_files or []]
if not selected and selected_sample != "None (Upload Custom File)":
    selected = [(selected_sample, sample_files[selected_sample])]
selected += [(name, sample_files[name]) for name in extra_samples if name not in dict(selected)]

# Results (and the batch token session behind them) belong to one file set. When the
# selection changes, drop them so tokens from a previous batch are never shown or reused.
selection_signature = tuple(
    (name, getattr(source, "size", None) if not isinstance(source, Path) else str(source))
    for name, source in selected
)
previous_signature = st.session_state.get("results_signature")
if previous_signature is not None and previous_signature != selection_signature:
    for key in ("pipeline_result", "batch_result", "results_signature", "redacted_pdfs", "mock_llm_reply"):
        st.session_state.pop(key, None)

if selected:
    names = ", ".join(f"`{name}`" for name, _ in selected)
    st.write(f"**Selected Document{'s' if len(selected) > 1 else ''}:** {names}")
    process_btn = st.button("🚀 Analyze & Firewall Document" + ("s" if len(selected) > 1 else ""), type="primary")

    if process_btn:
        with st.spinner(f"Processing through PrivacyGate firewall (max passes: {max_passes})..."):
            temp_paths: list[Path] = []
            try:
                paths: list[Path] = []
                for name, source in selected:
                    if isinstance(source, Path):
                        paths.append(source)
                        continue
                    # Uploaded bytes exist on disk only while the pipeline runs.
                    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix) as handle:
                        handle.write(source.getvalue())
                    temp_paths.append(Path(handle.name))
                    paths.append(temp_paths[-1])
                if len(paths) == 1:
                    batch = None
                    results = [run_pipeline(paths[0], max_passes=max_passes)]
                else:
                    batch = run_batch(paths, max_passes=max_passes)
                    results = batch.results
                for (name, _), item in zip(selected, results):
                    item.document.filename = item.sanitized_document.filename = name
                if batch is not None:
                    # Locations were recorded with the on-disk names; show the display names.
                    renames = {path.name: name for path, (name, _) in zip(paths, selected)}
                    for summary in batch.cross_file.values():
                        summary.occurrences = [(renames.get(file, file), where) for file, where in summary.occurrences]
                # Masked PDFs are built now because uploaded bytes are deleted right after processing.
                redacted_pdfs = {}
                for path, (name, _), item in zip(paths, selected, results):
                    if Path(name).suffix.lower() == ".pdf":
                        approved_file = item.validation.status == "APPROVED"
                        redacted_pdfs[name] = redact_pdf(
                            path, item.document, item.sanitized_document,
                            watermark=None if approved_file else REVIEW_WATERMARK,
                        )
                st.session_state["redacted_pdfs"] = redacted_pdfs
                st.session_state.pop("mock_llm_reply", None)
                st.session_state["batch_result"] = batch
                st.session_state["pipeline_result"] = results[0]
                st.session_state["results_signature"] = selection_signature
            except Exception as exc:
                # Project errors carry vetted messages; anything else may quote document text.
                detail = f": {exc}" if isinstance(exc, (ExtractionError, DetectionError)) else ""
                st.error(f"Processing failed closed: {type(exc).__name__}{detail}")
                st.session_state["pipeline_result"] = None
                st.session_state["batch_result"] = None
                st.session_state.pop("results_signature", None)
                st.session_state.pop("redacted_pdfs", None)
            finally:
                for temp_path in temp_paths:
                    temp_path.unlink(missing_ok=True)

batch_result = st.session_state.get("batch_result")
if batch_result is not None and st.session_state.get("pipeline_result") is not None:
    st.markdown("---")
    st.markdown("#### Batch Overview (shared pseudonym tokens)")
    st.dataframe(
        pd.DataFrame([{
            "File": item.document.filename,
            "Gate": item.validation.status,
            "Detected PII": len(item.entities),
            "Redactions": len(item.redactions),
        } for item in batch_result.results]),
        use_container_width=True, hide_index=True,
    )
    shown = st.radio(
        "Show detailed results for:",
        options=list(range(len(batch_result.results))),
        format_func=lambda index: batch_result.results[index].document.filename,
        horizontal=True,
    )
    st.session_state["pipeline_result"] = batch_result.results[shown]

# Render results if available
if "pipeline_result" in st.session_state and st.session_state["pipeline_result"] is not None:
    result = st.session_state["pipeline_result"]
    doc = result.document
    entities = result.entities
    sanitized = result.sanitized_document
    validation = result.validation
    audit = result.audit_report
    passes_executed = getattr(result, "passes_executed", 1)

    st.markdown("---")

    # Final Decision Banner
    if validation.status == "APPROVED":
        st.markdown(
            '<div class="status-badge-approved">✅ APPROVED BY CONFIGURED RESIDUAL VALIDATION CHECKS<br>'
            f'<span style="font-size:0.95rem; font-weight:400;">{html.escape(validation.reason)}</span><br>'
            f'<span style="font-size:0.85rem; font-weight:600; opacity:0.85;">Sanitization passes: {passes_executed} | '
            f'Residual detections: {len(validation.residual_entities)}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="status-badge-blocked">🚫 BLOCKED — NOT APPROVED FOR DOWNSTREAM AI PROCESSING<br>'
            f'<span style="font-size:0.95rem; font-weight:400;">{html.escape(validation.reason)}</span><br>'
            f'<span style="font-size:0.85rem; font-weight:600; opacity:0.85;">Sanitization passes: {passes_executed} | '
            f'Residual detections: {len(validation.residual_entities)}</span></div>',
            unsafe_allow_html=True,
        )

    page_report = doc.metadata.get("page_report") or []
    image_report = doc.metadata.get("embedded_images") or []
    failed_pages = sum(entry.get("status") == "failed" for entry in page_report if type(entry) is dict)
    failed_images = sum(entry.get("status") == "failed" for entry in image_report if type(entry) is dict)
    extraction_status = (
        f"Incomplete — {failed_pages} page(s) and {failed_images} image(s) were not inspected"
        if failed_pages or failed_images else "Complete"
    )
    st.markdown("#### Pipeline status")
    st.dataframe(pd.DataFrame([
        {"Stage": "Extraction", "Status": extraction_status},
        {"Stage": "PII detection", "Status": f"Complete — {len(entities)} detections"},
        {"Stage": "Risk classification", "Status": "Complete"},
        {"Stage": "Redaction", "Status": f"Complete — {audit.redacted_count} transformations"},
        {"Stage": "Residual scan", "Status": f"Complete — {len(validation.residual_entities)} current residual detections"},
        {"Stage": "Privacy gate", "Status": validation.status},
    ]), use_container_width=True, hide_index=True)

    tab_labels = [
        "📋 1. Extraction Summary",
        "🔍 2. PII Findings & Analytics",
        "✂️ 3. Semantic Redaction Preview",
        "📊 4. Audit Report & Export",
        "📈 5. Quality Benchmark",
        "🤖 6. What the AI Model Sees",
    ]
    if batch_result is not None:
        tab_labels.append("🔗 7. Cross-File Identities")
    tabs = st.tabs(tab_labels)
    tab_summary, tab_findings, tab_redaction, tab_audit, tab_benchmarks, tab_ai = tabs[:6]

    if batch_result is not None:
        with tabs[6]:
            st.subheader("Cross-File Identities")
            st.caption(
                "One token session covers the whole batch, so the same person carries the same token in "
                "every file. E-mail addresses keep their own token and are linked to their person. "
                "This view is built in memory from tokens and locations only; it is not exported."
            )
            summaries = sorted(batch_result.cross_file.values(),
                               key=lambda s: (-len(s.files), s.entity_type, s.token))
            only_shared = st.checkbox("Only tokens that appear in more than one file", value=False)
            type_options = sorted({s.entity_type for s in summaries})
            chosen_types = st.multiselect("Entity types", options=type_options,
                                          default=[t for t in ("PERSON", "EMAIL") if t in type_options])
            rows = [{
                "Token": s.token,
                "Type": s.entity_type,
                "Files": len(s.files),
                "Where": s.locations_text(),
                "Linked": s.linked_person or ", ".join(s.linked_emails),
            } for s in summaries
                if s.entity_type in chosen_types and (len(s.files) > 1 or not only_shared)]
            c1, c2, c3 = st.columns(3)
            c1.metric("Tokens in batch", len(summaries))
            c2.metric("Tokens in 2+ files", sum(len(s.files) > 1 for s in summaries))
            c3.metric("E-mails linked to a person", sum(s.linked_person is not None for s in summaries))
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No tokens match the current filters.")

    with tab_ai:
        st.subheader("What the AI Model Sees")
        payload = build_llm_payload(sanitized)
        approved = validation.status == "APPROVED"
        a1, a2, a3 = st.columns(3)
        a1.metric("Characters", f"{len(payload):,}")
        a2.metric("Pseudonym tokens", len(re.findall(r"\[[A-Z][A-Z_]*(?:_\d+)?\]", payload)))
        a3.metric("Gate", validation.status)
        st.caption(
            "This is the exact sanitized text a downstream model would receive. "
            + ("The gate approved it." if approved else
               "The gate BLOCKED this document, so it would not be sent; shown here for review only.")
        )
        st.text_area("Sanitized payload", payload, height=300, disabled=True)

        st.markdown("#### Mock model call")
        st.caption("Local mock only: no network access and no API keys. It refuses unless the gate approved.")
        instruction = st.text_input("Instruction for the model", value="Summarise the key risks in this document.")
        if st.button("Send to mock LLM", disabled=False):
            try:
                st.session_state["mock_llm_reply"] = mock_llm_call(sanitized, validation, instruction).text
            except GateRefusedError as refusal:
                st.session_state["mock_llm_reply"] = None
                st.error(str(refusal))
        if st.session_state.get("mock_llm_reply"):
            st.success(st.session_state["mock_llm_reply"])

        masked = (st.session_state.get("redacted_pdfs") or {}).get(doc.filename)
        if masked is not None and doc.file_type == "pdf":
            st.markdown("#### Redacted PDF")
            st.caption(
                f"{masked.page_count} pages (same as the source), {masked.boxes} masked areas, "
                f"document metadata removed. Masks follow the final sanitized text; scanned pages "
                f"have the image pixels under each mask destroyed."
                + (f" {masked.unlocated} replaced spans could not be placed on the page." if masked.unlocated else "")
                + (f" {masked.unreadable_figures} figure regions masked as unreadable."
                   if masked.unreadable_figures else "")
                + (f" {masked.photos} photo or barcode regions masked." if masked.photos else "")
                + (f" Figure scan failed on {masked.figure_scan_failures} pages: figures there may be unmasked."
                   if masked.figure_scan_failures else "")
            )
            pdf_name = f"{Path(doc.filename).stem}_redacted.pdf"
            if approved:
                st.download_button("⬇️ Download redacted PDF", masked.data, file_name=pdf_name,
                                   mime="application/pdf")
            else:
                st.warning("The gate blocked this document: the masked copy may still contain personal data.")
                if st.checkbox("I understand: download a watermarked review copy for internal review only"):
                    st.download_button("⬇️ Download review copy (not approved)", masked.data,
                                       file_name=f"{Path(doc.filename).stem}_review_copy.pdf",
                                       mime="application/pdf")

    with tab_summary:
        st.subheader("Document Extraction Summary")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("File Name", doc.filename)
        col2.metric("Format", doc.file_type.upper())
        col3.metric("Extracted Blocks", len(doc.blocks))
        pages_slides = doc.metadata.get("page_count") or doc.metadata.get("slide_count") or "N/A"
        col4.metric("Pages / Slides", str(pages_slides))

        page_report = doc.metadata.get("page_report") or []
        if page_report:
            st.markdown("#### Per-Page Extraction Report")
            statuses = [entry["status"] for entry in page_report]
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Native Pages", statuses.count("native"))
            p2.metric("OCR'd Pages", statuses.count("ocr"))
            p3.metric("Failed Pages", statuses.count("failed"))
            p4.metric("OCR Time (sum)", f"{sum(entry.get('seconds', 0) for entry in page_report):.1f} s")
            if "failed" in statuses:
                st.error(
                    "OCR failed on page(s) "
                    + ", ".join(str(entry["page"]) for entry in page_report if entry["status"] == "failed")
                    + ". Text on those pages was not inspected, so the document cannot be approved."
                )
            st.dataframe(
                pd.DataFrame([{
                    "Page": entry["page"],
                    "Status": entry["status"],
                    "Attempts": entry.get("attempts", 0),
                    "Seconds": entry.get("seconds", 0.0),
                    "Note": entry.get("reason", ""),
                } for entry in page_report]),
                use_container_width=True,
                hide_index=True,
            )

        image_report = doc.metadata.get("embedded_images") or []
        if image_report:
            st.markdown("#### Embedded Images")
            image_statuses = [entry["status"] for entry in image_report]
            i1, i2, i3 = st.columns(3)
            i1.metric("Images OCR'd", image_statuses.count("ocr"))
            i2.metric("Images Skipped", sum(s.startswith("skipped") for s in image_statuses))
            i3.metric("Images Failed", image_statuses.count("failed"))
            if "failed" in image_statuses:
                st.error("OCR failed for some embedded images. Their content was not inspected, "
                         "so the document cannot be approved.")
            with st.expander("Embedded image details and warnings", expanded=False):
                st.dataframe(
                    pd.DataFrame([{
                        "Image": entry["image"], "Status": entry["status"],
                        "Text Lines": entry.get("lines"), "Note": entry.get("reason", ""),
                    } for entry in image_report]),
                    use_container_width=True, hide_index=True,
                )
                for warning in doc.metadata.get("extraction_warnings") or []:
                    st.caption(f"⚠️ {warning['image']}: {warning['reason']}")

        st.markdown("#### Document Structure Blocks")
        block_records = []
        for b in doc.blocks[:50]:  # Limit display to first 50 blocks
            block_records.append({
                "Block ID": b.block_id,
                # None (not "-") keeps the columns numeric for Arrow serialization.
                "Page": b.page_number,
                "Slide": b.slide_number,
                "Paragraph": b.paragraph_number,
                "Extraction Method": b.extraction_method or "native",
                "Text Preview": (b.text[:80] + "...") if len(b.text) > 80 else b.text,
            })
        if block_records:
            st.dataframe(pd.DataFrame(block_records), use_container_width=True)

        if len(doc.blocks) > 0:
            with st.expander("🔬 Deep Block Inspector", expanded=False):
                inspector_block_idx = st.slider(
                    "Select Block Index:",
                    min_value=0,
                    max_value=len(doc.blocks) - 1,
                    value=0,
                ) if len(doc.blocks) > 1 else 0
                selected_block = doc.blocks[inspector_block_idx]
                st.write(f"**Block ID:** `{selected_block.block_id}` | **Length:** {len(selected_block.text)} chars")
                st.json({
                    "page_number": selected_block.page_number,
                    "slide_number": selected_block.slide_number,
                    "paragraph_number": selected_block.paragraph_number,
                    "table_number": selected_block.metadata.get("table_number"),
                    "row_number": selected_block.metadata.get("row_number"),
                    "column_number": selected_block.metadata.get("column_number"),
                    "extraction_method": selected_block.extraction_method,
                    "metadata": selected_block.metadata,
                })
                st.text_area("Full Block Text", selected_block.text, height=120, disabled=True)

    with tab_findings:
        st.subheader("PII Detection & Sensitivity Classification")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total PII Entities", len(entities))
        m2.metric("Critical Risk", audit.counts_by_risk.get("CRITICAL", 0))
        m3.metric("High Risk", audit.counts_by_risk.get("HIGH", 0))
        m4.metric("Medium Risk", audit.counts_by_risk.get("MEDIUM", 0))
        avg_conf = (sum(e.confidence for e in entities) / len(entities)) if entities else 0.0
        m5.metric("Avg Confidence", f"{avg_conf:.0%}")
        if audit.unreadable_figures:
            st.info(f"{audit.unreadable_figures} figure(s) could not be read reliably: their text is withheld "
                    "from the sanitized output as [FIGURE_UNREADABLE_n] and the figures are masked in the "
                    "redacted PDF.")

        if audit.counts_by_location:
            st.markdown("#### PII by Location")
            st.dataframe(
                pd.DataFrame(
                    [{"Location": where, "Entities": count}
                     for where, count in sorted(audit.counts_by_location.items(), key=lambda item: -item[1])]
                ),
                use_container_width=True, hide_index=True,
            )

        if entities:
            st.markdown("#### Interactive Analytics")
            chart_col1, chart_col2 = st.columns(2)

            with chart_col1:
                st.markdown("**Entities by Category**")
                cat_df = pd.DataFrame(
                    list(audit.counts_by_category.items()),
                    columns=["Category", "Count"],
                ).sort_values(by="Count", ascending=False).set_index("Category")
                st.bar_chart(cat_df)

            with chart_col2:
                st.markdown("**Risk Severity Distribution**")
                risk_df = pd.DataFrame(
                    list(audit.counts_by_risk.items()),
                    columns=["Risk Level", "Count"],
                ).set_index("Risk Level")
                st.bar_chart(risk_df)

            st.markdown("#### Detected Entities Breakdown")
            findings_data = []
            for e in entities:
                findings_data.append({
                    "Entity Type": e.entity_type,
                    "Risk Level": e.risk_level,
                    "Confidence": f"{e.confidence:.0%}",
                    "Detector": e.detector,
                    "Block ID": e.block_id,
                    "Source Location": json.dumps(e.source_location),
                })
            df_findings = pd.DataFrame(findings_data)
            st.dataframe(df_findings, use_container_width=True)
        else:
            st.success("No Personally Identifiable Information detected in this document.")

    with tab_redaction:
        st.subheader("Semantic Context Redaction Preview")
        st.markdown("**Identity removed. Relationships preserved.**")
        st.caption("Stable pseudonyms remove identity while preserving relationships for downstream AI.")
        st.caption("Repeated references to the same detected identity reuse the same token, e.g. [PERSON_001].")

        sanitized_full_text = "\n\n".join(b.text for b in sanitized.blocks)
        pseudonym_tokens = [
            match.group(0) for match in UI_PLACEHOLDER_PATTERN.finditer(sanitized_full_text)
            if match.group("number") is not None
        ]
        unique_metric, occurrences_metric = st.columns(2)
        unique_metric.metric("Unique pseudonyms", len(set(pseudonym_tokens)))
        occurrences_metric.metric("Pseudonym occurrences", len(pseudonym_tokens))
        if pseudonym_tokens:
            st.caption("Stable tokens observed in this document: " + ", ".join(sorted(set(pseudonym_tokens))[:5]))
        else:
            st.caption("This document uses generic semantic placeholders where stable pseudonyms were not issued.")

        preview_mode = st.radio(
            "Preview Mode:",
            options=["🎨 Visual Badge Highlighting", "📄 Plain Text Diff"],
            horizontal=True,
        )

        # Pagination / Block range selector
        max_blocks = len(doc.blocks)
        range_size = 10
        total_pages = max(1, (max_blocks + range_size - 1) // range_size)
        # st.slider rejects min_value == max_value, so small documents get no slider.
        page_idx = (
            st.slider("Select Display Window (10 blocks per page):", min_value=1, max_value=total_pages, value=1)
            if total_pages > 1 else 1
        )
        start_block_idx = (page_idx - 1) * range_size
        end_block_idx = min(start_block_idx + range_size, max_blocks)

        st.caption(f"Showing Blocks {start_block_idx + 1} to {end_block_idx} of {max_blocks}")

        # Group entities by block_id for fast lookup
        entities_by_block: dict[str, list[PIIEntity]] = {}
        for ent in entities:
            entities_by_block.setdefault(ent.block_id, []).append(ent)

        col_orig, col_san = st.columns(2)

        if preview_mode == "🎨 Visual Badge Highlighting":
            with col_orig:
                st.markdown("**Original Text (Sensitive Entities Highlighted):**")
                orig_html_blocks = []
                for b in doc.blocks[start_block_idx:end_block_idx]:
                    b_ents = entities_by_block.get(b.block_id, [])
                    tag = f"<span class='block-tag'>Block {b.block_id}</span>"
                    rendered = highlight_original_block(b.text, b_ents)
                    orig_html_blocks.append(f"{tag}{rendered}")
                st.markdown(f"<div class='preview-card'>{''.join(orig_html_blocks)}</div>", unsafe_allow_html=True)

            with col_san:
                st.markdown("**Sanitized Text (Protected Semantic Placeholders):**")
                san_html_blocks = []
                for b in sanitized.blocks[start_block_idx:end_block_idx]:
                    tag = f"<span class='block-tag'>Block {b.block_id}</span>"
                    rendered = highlight_sanitized_block(b.text)
                    san_html_blocks.append(f"{tag}{rendered}")
                st.markdown(f"<div class='preview-card'>{''.join(san_html_blocks)}</div>", unsafe_allow_html=True)
        else:
            with col_orig:
                st.markdown("**Original Extracted Text:**")
                orig_text = "\n\n".join(b.text for b in doc.blocks[start_block_idx:end_block_idx])
                st.text_area("Original Snippet", orig_text, height=450, disabled=True)
            with col_san:
                st.markdown("**Sanitized Text:**")
                san_text = "\n\n".join(b.text for b in sanitized.blocks[start_block_idx:end_block_idx])
                st.text_area("Sanitized Snippet", san_text, height=450, disabled=True)

        st.download_button(
            label="💾 Download Sanitized Document Text",
            data=sanitized_full_text,
            file_name=f"{Path(doc.filename).stem}_sanitized.txt",
            mime="text/plain",
        )

    with tab_audit:
        st.subheader("Security & Privacy Audit Summary")
        audit_json = audit_report_to_json(audit)
        st.json(audit_json)

        st.download_button(
            label="📥 Export Audit Report (JSON)",
            data=audit_json,
            file_name=f"audit_report_{audit.document_id}.json",
            mime="application/json",
        )

    with tab_benchmarks:
        st.subheader("Current-document validation")
        st.caption(
            "These results are from the selected document's live processing. Redaction structure preservation "
            "compares extracted and sanitized blocks. Residual detections come from the configured "
            "validation scan; zero detections do not prove that no PII remains."
        )

        redaction_preservation = measure_redaction_structure_preservation(
            doc.blocks,
            sanitized.blocks,
        )
        residual_count = len(validation.residual_entities)

        b1, b2, b3 = st.columns(3)

        b1.metric(
            "Redaction structure preservation",
            f"{redaction_preservation:.1%}",
            help="Share of extracted blocks that sanitization kept in place (same id, location, non-empty text). "
                 "It does not measure how well extraction captured the file.",
        )

        b2.metric("Residual Detections", residual_count)

        b3.metric(
            "Validation Status",
            validation.status,
        )

        if residual_count > 0:
            st.error(
                f"Validation detected {residual_count} residual PII entities. "
                "The document must remain blocked from downstream AI processing."
            )
        elif validation.status == "APPROVED":
            st.success(
                "The configured validation scan reported no residual detections, "
                "and the privacy gate approved the document."
            )
        else:
            st.warning(
                "The configured validation scan reported no residual detections, but the privacy gate has not "
                "approved the document. Review the validation reason above."
            )

        st.subheader("Measured evaluation evidence")
        st.caption("Ground-truth benchmark results are separate from this document's live validation.")
        evaluation = load_evaluation_results()
        if evaluation is None:
            st.info("No saved local evaluation results are available. After validation, run "
                    "`uv run python scripts/evaluate.py --out eval/results_current.md` to generate them.")
            evaluation = load_evaluation_results(BASELINE_RESULTS_PATH)
            if evaluation is not None:
                st.markdown("#### Historical baseline — d85b251")
        else:
            st.markdown("#### Saved local benchmark")
        if evaluation is not None:
            total = evaluation["total"]
            st.caption(
                "Measured on supplied Cadence evaluation artifacts; these figures are not live results "
                "for the selected document. "
                f"Benchmark commit: {evaluation.get('git_commit', 'unavailable')}. "
                "The saved run may predate the current working tree. "
                "A zero residual occurrence rate applies only to the labelled occurrences in this benchmark."
            )
            evidence = st.columns(4)
            evidence[0].metric("Measured recall", percent(total.get("recall")))
            evidence[1].metric("Measured precision", percent(total.get("precision")))
            evidence[2].metric("Measured F1", percent(total.get("f1")))
            evidence[3].metric("Measured residual occurrence rate", percent(total.get("residual_rate")))
            rows = []
            coverage_rows = []
            for item in evaluation["files"]:
                overall = item.get("overall") or {}
                rows.append({
                    "Artifact": item.get("file", "Not available"),
                    "Recall": percent(overall.get("recall")),
                    "Precision": percent(overall.get("precision")),
                    "F1": percent(overall.get("f1")),
                    "Residual occurrence rate": percent(overall.get("residual_rate")),
                    "Gate (2 passes)": item.get("gate_multi_pass", "Not available"),
                    "Not extracted": item.get("not_extracted", "Not available"),
                    "Runtime": f"{item['seconds']} s" if type(item.get("seconds")) in (int, float) else "Not available",
                })
                coverage = item.get("extraction_coverage")
                if type(coverage) is dict:
                    pages = coverage.get("pages", {})
                    images = coverage.get("embedded_images", {})
                    coverage_rows.append({
                        "Artifact": item.get("file", "Not available"),
                        "Native pages": pages.get("native", "Not available"),
                        "OCR pages": pages.get("ocr", "Not available"),
                        "Failed pages": pages.get("failed", "Not available"),
                        "Images attempted": images.get("attempted", "Not available"),
                        "Images succeeded": images.get("succeeded", "Not available"),
                        "Images failed": images.get("failed", "Not available"),
                        "Images skipped": images.get("skipped", "Not available"),
                        "Extraction warnings": coverage.get("warning_count", "Not available"),
                    })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if coverage_rows:
                st.markdown("#### OCR and embedded-image coverage")
                st.dataframe(pd.DataFrame(coverage_rows), use_container_width=True, hide_index=True)

        st.markdown("#### Checked-in case-study benchmark")
        benchmark_path = next(
            (path for path in (Path("eval/results_after.json"), Path("eval/results_before.json")) if path.exists()),
            None,
        )
        benchmark = load_evaluation_results(benchmark_path) if benchmark_path else None
        if benchmark is None:
            st.info("No benchmark results found. Run `uv run python scripts/evaluate.py --out eval/results_after.md`.")
        else:
            st.caption(
                f"Measured {benchmark.get('date', 'unknown')} ({benchmark.get('label', 'unlabelled')}) "
                "against the labelled case-study files. These are saved measurements, not live results. "
                "See `eval/README.md` for definitions."
            )
            total = benchmark["total"]
            metrics = st.columns(4)
            metrics[0].metric("Recall (all files)", percent(total.get("recall")))
            metrics[1].metric("Precision (all files)", percent(total.get("precision")))
            metrics[2].metric("F1 (all files)", percent(total.get("f1")))
            metrics[3].metric("Residual PII rate", percent(total.get("residual_rate")))
            st.dataframe(pd.DataFrame([{
                "File": item["file"],
                "Recall": percent(item["overall"].get("recall")),
                "Precision": percent(item["overall"].get("precision")),
                "Residual PII": percent(item["overall"].get("residual_rate")),
                "Redaction structure preservation": percent(item.get(
                    "redaction_structure_preservation", item.get("structure_retention"))),
                "Gate (1 pass)": item.get("gate_single_pass", "Not available"),
                "Gate (2 passes)": item.get("gate_multi_pass", "Not available"),
            } for item in benchmark["files"]]), use_container_width=True, hide_index=True)
            st.caption("Redaction structure preservation measures whether sanitization kept the extracted blocks in place.")
            fidelity_rows = [item for item in benchmark["files"] if item.get("extraction_fidelity")]
            if fidelity_rows:
                st.markdown("##### Extraction fidelity")
                st.dataframe(pd.DataFrame([{
                    "File": item["file"],
                    "Reference": "XML of the file" if item["extraction_fidelity"]["kind"] == "xml_reference"
                    else "hand transcription, pages " + ", ".join(
                        str(page["page"]) for page in item["extraction_fidelity"]["pages"]),
                    "Character coverage": percent(item["extraction_fidelity"].get("character_coverage")),
                    "Reading order": percent(item["extraction_fidelity"].get(
                        "reading_order", item["extraction_fidelity"].get("line_order"))),
                    "Table cells": percent(item["extraction_fidelity"].get("table_cells")),
                    "OCR CER": percent(item["extraction_fidelity"].get("cer")),
                } for item in fidelity_rows]), use_container_width=True, hide_index=True)
                st.markdown(
                    "- **Character coverage**: share of reference letters and digits found in extracted text.\n"
                    "- **Reading order**: share of reference paragraphs or lines kept in order.\n"
                    "- **Table cells**: share of reference cells extracted at the same row and column.\n"
                    "- **OCR CER**: character error rate against hand transcription (lower is better)."
                )
            chart = Path("eval/results_chart.png")
            if chart.exists() and benchmark_path.name == "results_after.json":
                st.image(str(chart), caption="Before vs after (eval/results_after.md)")
