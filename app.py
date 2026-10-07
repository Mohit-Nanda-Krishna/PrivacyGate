"""PrivacyGate — Pre-LLM Privacy Firewall for Business Documents.

Streamlit interactive interface for multi-format document ingestion,
hybrid PII detection, semantic redaction, and fail-closed privacy gating.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import streamlit as st
import pandas as pd

from privacygate.audit import audit_report_to_json
from privacygate.pipeline import run_pipeline

st.set_page_config(
    page_title="PrivacyGate — AI Privacy Firewall",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom header styling
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .status-badge-approved {
        background-color: #D1FAE5;
        color: #065F46;
        padding: 0.8rem 1.2rem;
        border-radius: 8px;
        font-weight: 700;
        font-size: 1.25rem;
        text-align: center;
        border: 2px solid #10B981;
    }
    .status-badge-blocked {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 0.8rem 1.2rem;
        border-radius: 8px;
        font-weight: 700;
        font-size: 1.25rem;
        text-align: center;
        border: 2px solid #EF4444;
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

# Sidebar: System configuration and sample files
with st.sidebar:
    st.header("⚙️ Configuration")
    st.info("Environment: Python 3.11 (Locked uv toolchain)\nHybrid Engine: Regex + Presidio + Custom Rules")

    docs_dir = Path("docs")
    sample_options = ["None (Upload Custom File)"]
    sample_files: dict[str, Path] = {}
    if docs_dir.exists():
        for f in docs_dir.glob("*.*"):
            if f.suffix.lower() in (".pdf", ".docx", ".pptx"):
                sample_options.append(f.name)
                sample_files[f.name] = f

    selected_sample = st.selectbox(
        "Load Pre-Packaged Evidence Artifact:",
        options=sample_options,
        index=0,
    )

    st.markdown("---")
    st.markdown("**Core Security Policy:**")
    st.caption("• Raw PII never sent downstream\n• Fail-closed enforcement\n• Traceable source coordinates\n• Zero-PII audit logging")

# File selection logic
uploaded_file = st.file_uploader(
    "Upload Business Evidence Document",
    type=["pdf", "docx", "pptx"],
    help="Supported formats: Digital/Scanned PDF, Microsoft Word DOCX, Microsoft PowerPoint PPTX",
)

file_to_process: Path | None = None
temp_file_ref = None

if uploaded_file is not None:
    suffix = Path(uploaded_file.name).suffix
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.write(uploaded_file.getvalue())
    temp_file.flush()
    temp_file.close()
    file_to_process = Path(temp_file.name)
    temp_file_ref = file_to_process
elif selected_sample != "None (Upload Custom File)":
    file_to_process = sample_files[selected_sample]

if file_to_process is not None:
    st.write(f"**Selected Document:** `{file_to_process.name}`")
    process_btn = st.button("🚀 Analyze & Firewall Document", type="primary")

    if process_btn:
        with st.spinner("Processing document through PrivacyGate firewall stages..."):
            try:
                result = run_pipeline(file_to_process)
                st.session_state["pipeline_result"] = result
            except Exception as exc:
                st.error(f"Processing failed closed: {type(exc).__name__}: {exc}")
                st.session_state["pipeline_result"] = None

# Render results if available
if "pipeline_result" in st.session_state and st.session_state["pipeline_result"] is not None:
    result = st.session_state["pipeline_result"]
    doc = result.document
    entities = result.entities
    sanitized = result.sanitized_document
    validation = result.validation
    audit = result.audit_report

    st.markdown("---")

    # Final Decision Banner
    if validation.status == "APPROVED":
        st.markdown(
            f'<div class="status-badge-approved">✅ PRIVACY GATE PASSED — APPROVED FOR DOWNSTREAM AI PROCESSING<br>'
            f'<span style="font-size:0.95rem; font-weight:400;">{validation.reason}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="status-badge-blocked">🚫 PRIVACY GATE FAILED — DOCUMENT BLOCKED FROM DOWNSTREAM AI PROCESSING<br>'
            f'<span style="font-size:0.95rem; font-weight:400;">{validation.reason}</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    tab_summary, tab_findings, tab_redaction, tab_audit = st.tabs([
        "📋 1. Extraction Summary",
        "🔍 2. PII Findings & Risks",
        "✂️ 3. Semantic Redaction Preview",
        "📊 4. Audit Report & Export",
    ])

    with tab_summary:
        st.subheader("Document Extraction Summary")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("File Name", doc.filename)
        col1_type = doc.file_type.upper()
        col2.metric("Format", col1_type)
        col3.metric("Extracted Blocks", len(doc.blocks))
        pages_slides = doc.metadata.get("page_count") or doc.metadata.get("slide_count") or "N/A"
        col4.metric("Pages / Slides", pages_slides)

        st.markdown("#### Document Structure Blocks")
        block_records = []
        for b in doc.blocks[:50]:  # Limit display to first 50 blocks
            block_records.append({
                "Block ID": b.block_id,
                "Page": b.page_number if b.page_number is not None else "-",
                "Slide": b.slide_number if b.slide_number is not None else "-",
                "Paragraph": b.paragraph_number if b.paragraph_number is not None else "-",
                "Extraction Method": b.extraction_method or "native",
                "Text Preview": (b.text[:80] + "...") if len(b.text) > 80 else b.text,
            })
        if block_records:
            st.dataframe(pd.DataFrame(block_records), use_container_width=True)

    with tab_findings:
        st.subheader("PII Detection & Sensitivity Classification")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total PII Entities", len(entities))
        m2.metric("Critical Risk", audit.counts_by_risk.get("CRITICAL", 0))
        m3.metric("High Risk", audit.counts_by_risk.get("HIGH", 0))
        m4.metric("Medium Risk", audit.counts_by_risk.get("MEDIUM", 0))

        if entities:
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
        st.caption("PII is replaced with standardized semantic placeholders ([PERSON], [EMAIL], [EMPLOYEE_ID], etc.) preserving surrounding context.")

        sanitized_full_text = "\n\n".join(b.text for b in sanitized.blocks)

        col_orig, col_san = st.columns(2)
        with col_orig:
            st.markdown("**Original Extracted Text (Redaction Target):**")
            orig_text = "\n\n".join(b.text for b in doc.blocks[:10])
            st.text_area("Original Snippet (First 10 blocks)", orig_text, height=350, disabled=True)
        with col_san:
            st.markdown("**Sanitized Text (Safe for LLM):**")
            san_text = "\n\n".join(b.text for b in sanitized.blocks[:10])
            st.text_area("Sanitized Snippet (First 10 blocks)", san_text, height=350, disabled=True)

        st.download_button(
            label="💾 Download Sanitized Document Text",
            data=sanitized_full_text,
            file_name=f"{Path(doc.filename).stem}_sanitized.txt",
            mime="text/plain",
        )

    with tab_audit:
        st.subheader("Security & Privacy Audit Summary")
        audit_json = audit_report_to_json(audit, indent=2)
        st.json(audit_json)

        st.download_button(
            label="📥 Export Audit Report (JSON)",
            data=audit_json,
            file_name=f"audit_report_{doc.document_id}.json",
            mime="application/json",
        )
