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

Phase 2 adds local hybrid PII detection to native/OCR PDF and native DOCX/PPTX
extraction. The Streamlit app remains a foundation screen. Risk classification,
redaction, and privacy validation are not implemented yet.

Extraction returns the shared `Document` / `ContentBlock` models:

```python
from privacygate.extraction import extract_document

document = extract_document("sample.pdf")  # Also accepts DOCX/PPTX paths.
```

Extracted text is unvalidated and may contain PII. Extraction is not approval
for downstream AI use. Each PDF page with fewer than 20 alphanumeric native-text
characters uses OCR; other pages retain native extraction. This deterministic
heuristic can misclassify short pages or miss image text on native-rich pages.
OCR failure or fewer than 20 alphanumeric OCR characters rejects the entire
document, including effectively blank pages. Missing Tesseract raises
`OCRRequiredError`, a subclass of `ExtractionError`.

OCR runs locally with English language data, automatic page segmentation, and
a 30-second engine timeout per page. Pages render at
[300 DPI](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).
OCR blocks use `extraction_method="ocr"` with page/order identifiers and pixel
bounding boxes in the rendered page. Images are held in memory by PrivacyGate;
pytesseract uses local temporary files and cleans them up after each call.

## Local PII detection

```python
from privacygate.detection import detect_pii

entities = detect_pii(document)
```

Presidio uses spaCy for PERSON/LOCATION and explicit recognizers for
EMAIL_ADDRESS, PHONE_NUMBER, IP_ADDRESS, CREDIT_CARD, US_SSN, and IBAN_CODE.
Project regex covers conventional/internal-domain email addresses and labelled
phone numbers. Enterprise rules support labelled EMPLOYEE_ID, CLIENT_ID,
CUSTOMER_ID, and PORTFOLIO_ID values. ORGANIZATION and generic dates are excluded.

Each result identifies its block and uses `[start, end)` Python character offsets
into that block's text, with structural source locations and detector provenance.
Results follow document block order. Overlapping spans are conservatively united;
type selection prefers labelled enterprise IDs, then structured identifiers,
then PERSON/LOCATION, with confidence and deterministic tie breakers. This can
over-expand a finding. Exact duplicates retain maximum confidence. Detectors are
joined with `|`; raw matched text is not stored in entities. Risk remains unassigned.

Missing NLP or any detector failure raises `DetectionError` rather than returning
a partial pass. Detection makes no network calls and grants no privacy approval;
an empty finding list does not prove the document is safe. Small-model NER, OCR
errors, and matches split across blocks can cause false positives or negatives.

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

`uv sync` installs the pinned [English spaCy model](https://spacy.io/models/en/),
`en_core_web_sm` **3.8.0** (about 12 MB), from its official versioned wheel.
spaCy is constrained to the compatible 3.8 series. The existing CI locked sync
installs the same model; no separate download command is required. The diagnostic
loads the model and checks its NER component. Detection never downloads models
at runtime, and Presidio email validation uses a bundled offline suffix list.

Tesseract is a separate system executable: installing `pytesseract` does not
install it. Install Tesseract separately with English (`eng`) language data,
add its executable directory to `PATH`, then open a fresh terminal and run
`tesseract --version` and `uv run python scripts/check_env.py`.
Missing Tesseract warns in diagnostics and prevents required OCR, while native
extraction and the app still work. Setup does not install system Tesseract.

The test suite always runs mocked OCR routing/failure tests. Three real-engine
integration tests run when Tesseract is on `PATH`; otherwise pytest explicitly
reports them as skipped. Synthetic scanned/mixed fixtures are generated in
pytest temporary directories from `tests/fixtures/generate_fixtures.py`.

No API keys or `.env` file are required. `.env.example` documents the current
configuration; `.env` and `.venv` are ignored by Git.
