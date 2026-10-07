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
  ├── Layer 1: Structured Regex Detector (Email, Phone, SSN, IP, IBAN, Luhn-verified Credit Cards)
  ├── Layer 2: Enterprise Custom Recognizers (Employee IDs, Client IDs, Portfolio IDs, Customer Refs)
  └── Layer 3: Microsoft Presidio & spaCy NLP (Names, Locations, Dates, Organizations)
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
  └── Replaces PII with typed placeholders (`[PERSON]`, `[EMAIL]`, `[EMPLOYEE_ID]`, etc.)
  │
  ▼ Sanitized Document
  │
[Stage 6: Fail-Closed Secondary Privacy Gate]
  ├── Rescans sanitized document with full hybrid detector
  ├── Filters applied semantic placeholders
  └── Fails closed on any residual PII or system error:
        ├── APPROVED: 0 residual PII -> Forward to LLM
        └── BLOCKED: Residual PII or error -> Access Denied
  │
  ▼
[Stage 7: Zero-PII Audit Report & Streamlit Dashboard]
  └── Generates metrics, category/risk breakdowns, and JSON audit logs (never persists raw PII).
```

---

## Core Technologies

- **Language & Runtime**: Python 3.11.x (managed via `uv`)
- **Web UI & Dashboard**: Streamlit
- **PDF Extraction**: PyMuPDF (`fitz`)
- **Office Document Processing**: `python-docx`, `python-pptx`
- **OCR Engine**: Tesseract OCR via `pytesseract`
- **PII Detection**: Microsoft Presidio Analyzer, spaCy (`en_core_web_lg` 3.8.0), Python regular expressions
- **Quality & Testing**: `pytest` (125 automated unit/integration tests)

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

# 3. Export audit report as JSON (safe, zero raw PII persisted)
from privacygate.audit import audit_report_to_json
audit_json = audit_report_to_json(result.audit_report)
print(audit_json)
```

---

## Evaluation & Case Study Targets

PrivacyGate includes an automated evaluation benchmark (`src/privacygate/evaluation.py`):

- **Recall**: $TP / (TP + FN)$ (Security-critical; prioritizes zero missed PII)
- **Precision**: $TP / (TP + FP)$ (Reduces unnecessary redactions)
- **F1 Score**: Harmonic mean of Precision and Recall
- **Residual PII Rate**: Residual detections / Initial detections (Target: 0%)
- **Structure Retention**: Block, coordinate, and context continuity ($\ge 80\%$)
