# PrivacyGate

PrivacyGate is a pre-LLM privacy firewall that detects, classifies and redacts Personally Identifiable Information from business documents before the content reaches an AI model.

## Pipeline

Document
→ Extract
→ Detect PII
→ Classify
→ Redact
→ Verify
→ Allow / Block

## Supported Formats

- PDF
- Scanned PDF
- DOCX
- PPTX

## Stack

Python · Streamlit · PyMuPDF · Tesseract · Microsoft Presidio · spaCy · pytest

## Documentation

- `PRD.md` — complete product requirements and architecture
- `AGENTS.md` — development instructions for coding agents
- `PROGRESS.md` — current implementation status

## Status

Phase 1A native PDF, DOCX, and PPTX text extraction is available in the backend.
The Streamlit app remains a foundation screen. OCR, PII detection, redaction,
and privacy validation are not implemented yet.

Native extraction returns the shared `Document` / `ContentBlock` models:

```python
from privacygate.extraction import extract_document

document = extract_document("sample.pdf")  # Also accepts DOCX/PPTX paths.
```

Extracted text is unvalidated and may contain PII. Extraction is not approval
for downstream AI use. PDFs with fewer than 20 alphanumeric native-text
characters raise `OCRRequiredError`; this is a text-availability heuristic,
not scanned-page detection. OCR is never attempted in Phase 1A.

## Development setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
these commands from the repository root:

```sh
uv sync
uv run python scripts/check_env.py
uv run streamlit run app.py
uv run pytest
```

Stop Streamlit with Ctrl+C before running tests, or use a second terminal.
Python is restricted to 3.11.x. uv creates `.venv` and can download Python 3.11
if needed. `pyproject.toml` and the uv-generated `uv.lock` are the dependency
source of truth; use `uv sync --locked` to require the existing lockfile.

Alternatively, run `./scripts/setup.ps1` in PowerShell or
`bash scripts/setup.sh` on macOS/Linux or Git Bash. Both sync the locked
environment and run the diagnostic.

Tesseract is a separate system executable: installing `pytesseract` does not
install it. Missing Tesseract produces a warning and does not prevent Phase 0
tests or the app from running. Before OCR work, install Tesseract separately
and put it on `PATH`. Setup does not install Tesseract or spaCy language models;
language-model configuration belongs to the detection phase.

No API keys or `.env` file are required. `.env.example` documents the current
configuration; `.env` and `.venv` are ignored by Git.
