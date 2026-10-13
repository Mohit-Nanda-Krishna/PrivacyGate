# PrivacyGate — Pre-LLM Privacy Firewall for Business Documents

PrivacyGate is a document-aware, fail-closed privacy gateway positioned before enterprise AI systems. It inspects, classifies, and sanitizes sensitive Personally Identifiable Information (PII) embedded inside multi-format business documents (PDF, DOCX, PPTX, and scanned artifacts) before content is allowed to reach downstream Large Language Models (LLMs).

---

## Architecture & Processing Pipeline

```
Evidence Document (PDF / DOCX / PPTX)
  │
  ▼
[Stage 1: File Ingestion & Format Validation]
  │
  ▼
[Stage 2: Content Extraction & Structure Preservation]
  ├── PDF: PyMuPDF (native vector blocks & coordinates)
  ├── Scanned PDF: Local Tesseract OCR (300 DPI, English)
  ├── Word: python-docx (paragraphs, tables, ordinals)
  └── PowerPoint: python-pptx (slide shape trees, text boxes, tables)
  │
  ▼ Canonical Document Model (`Document` / `ContentBlock`)
  │
[Stage 3: Hybrid PII Detection Engine]
  ├── Layer 1: Structured Regex Detector (Email, Phone, SSN, IP, IBAN, Luhn-verified Credit Cards,
  │            PAN, passport, DOB, card/account endings, US street addresses)
  ├── Layer 2: Enterprise Custom Recognizers (Employee/Director/vendor IDs, Client IDs, Portfolio IDs, Customer Refs)
  ├── Layer 3: Microsoft Presidio & spaCy NLP (Names, Locations), filtered by a configurable allowlist
  └── Name registry sweep: every variant of a person named anywhere in the document
  │
  ▼ Deterministic Entity Merger & Conflict Resolution
  │
[Stage 4: Sensitivity Risk Classification]
  ├── CRITICAL: Government IDs, Bank Accounts, Payment Cards, Financial Data
  ├── HIGH: Employee/Client/Customer IDs, Email, Phone, Addresses
  └── MEDIUM: Personal Names, General Locations, IP addresses, Timestamps
  │
  ▼
[Stage 5: Context-Preserving Semantic Redaction]
  └── Replaces PII with stable typed tokens (`[PERSON_001]`, `[EMAIL_004]`, ...); the same person keeps
      one token across a document, or across all files of a batch. The mapping stays in memory only.
  │
  ▼ Sanitized Document
  │
[Stage 6: Fail-Closed Secondary Privacy Gate]
  ├── Rescans sanitized document with full hybrid detector
  ├── Independent checks that do not use the NER model (name registry, digit runs, e-mail/ID shapes)
  ├── Accepts only tokens issued in this run
  └── Fails closed on residual PII found by either layer, failed OCR pages/images, or system error:
        ├── APPROVED: no residual found -> sanitized text may go downstream
        └── BLOCKED: residual PII, incomplete extraction or error -> nothing is sent
  │
  ▼
[Stage 7: Audit Report & Streamlit Dashboard]
  └── Aggregate metrics, category/risk/location breakdowns and JSON audit export (counts, not raw values);
      "What the AI model sees" view, gated mock model call, redacted PDF download.
```

---

## Core Technologies

- **Language & Runtime**: Python 3.11.x (managed via `uv`)
- **Web UI & Dashboard**: Streamlit
- **PDF Extraction**: PyMuPDF (`fitz`)
- **Office Document Processing**: `python-docx`, `python-pptx`
- **OCR Engine**: Tesseract OCR via `pytesseract`
- **PII Detection**: Microsoft Presidio Analyzer, spaCy (`en_core_web_sm` 3.8.0, locked in `uv.lock`), Python regular expressions
- **Quality & Testing**: `pytest` unit/integration tests; benchmark against labelled ground truth (`eval/`)

---

## Quickstart & Installation

### 1. Requirements

Ensure Python 3.11 is installed, along with the fast package manager `uv`:

```bash
# Install uv if not already installed
pip install uv
```

### 2. Synchronize Dependencies

```bash
uv sync --locked
```

### 3. Verify Environment

```bash
uv run python scripts/check_env.py
```

### 4. Launch the Interactive Dashboard

```bash
uv run streamlit run app.py
```

The Streamlit dashboard will open in your browser at `http://localhost:8501`.

### 5. Run Test Suite

```bash
uv run pytest
```

### Troubleshooting

**Dependency installation fails**

- Verify that Python 3.11 is installed.
- Ensure that `uv` is installed and available in your terminal.
- Retry dependency synchronization with:

```bash
uv sync --locked
```

**Dashboard does not start**

- Verify that dependency installation completed successfully.
- Check the terminal output for the specific error.
- Start the dashboard using the command in the Quickstart section:

```bash
uv run streamlit run app.py
```

**Tests fail**

Run the test suite using `uv run pytest` and review the error output to identify the failing test.

---

## Project Documentation

- `PRD.md` — Product Requirements Document and specifications.
- `PROGRESS.md` — Detailed implementation progress, phase milestones, and verification logs.
- `CONTRIBUTIONS_HARSHIT.md` — Comprehensive commit-by-commit changelog of all work performed by Harshit.
- `AGENTS.md` — Architectural rules and security constraints.

---

## Python API Usage

```python
from privacygate.pipeline import run_pipeline, process_document

# 1. Full pipeline execution with all intermediate artifacts
result = run_pipeline("docs/Cadence_Group_Risk_Management_Policy__v6.0.pdf")

print("Document ID:", result.document.document_id)
print("Extracted Blocks:", len(result.document.blocks))
print("Detected Entities:", len(result.entities))
print("Privacy Gate Status:", result.validation.status)  # "APPROVED" or "BLOCKED"
print("Residual Entities:", len(result.validation.residual_entities))

# 2. Get sanitized text safe for LLMs
sanitized_text = "\n\n".join(b.text for b in result.sanitized_document.blocks)

# 3. Export audit report as JSON (aggregate counts and decisions, no raw values)
from privacygate.audit import audit_report_to_json
audit_json = audit_report_to_json(result.audit_report)
print(audit_json)
```

---

## Evaluation & Case Study Targets

Quality is measured, not asserted: `scripts/evaluate.py` runs the pipeline on the Cadence case-study
files and scores it against hand-labelled ground truth in `eval/ground_truth/`.

```bash
uv run python scripts/evaluate.py --out eval/results_current.md --label "current"
# copy eval/results_current.json to eval/results_after.json, then:
uv run python scripts/compare_results.py   # before/after tables + eval/results_chart.png
uv run python scripts/evaluate.py --ground-truth eval/holdout/ground_truth \
    --docs eval/holdout/docs --out eval/holdout/results.md --label "held-out"
```

- **Recall**: share of labelled PII occurrences that were detected
- **Precision**: share of detections that are labelled PII
- **F1 Score**: harmonic mean of precision and recall
- **Residual PII rate**: share of labelled occurrences with any character left unredacted
- **Extraction fidelity** (PRD structure target $\ge 80\%$): DOCX/PPTX character coverage,
  reading order and table-cell preservation against a reference read from the file's XML;
  scanned PDF OCR character error rate and line order against hand-transcribed pages
  (`eval/reference/`)
- **Redaction structure preservation**: share of extracted blocks that sanitization kept in
  place (id, location, non-empty text); it does not measure extraction

Current numbers are in `eval/results_current.md` (shown in the dashboard) and, with the
before/after comparison and chart, in `eval/results_after.md`; both come from the same run and
name the commit they measured. Results on held-out files the pipeline was not tuned on are in
`eval/holdout/results.md`. Scoring rules, the labelling method, the case-study vs held-out
comparison and the known limitations are in `eval/README.md`.
