# PrivacyGate Progress

## Phase 0 - Foundation (2026-10-07)

### Completed

- Restricted the project to Python 3.11.x with `.python-version` and
  `requires-python = ">=3.11,<3.12"`.
- Created the installable `src/privacygate` package using the uv build backend.
  Added all ten requested core dependencies with `uv add`, and pytest with
  `uv add --dev`. uv generated `uv.lock`; it was not edited manually.
- Added the PRD module directories and docstring-only placeholders for
  extraction, detection, redaction, validation, risk, and audit.
- Added typed dataclasses for Document, ContentBlock, PIIEntity,
  ValidationResult, and AuditReport. Unvalidated results default to BLOCKED;
  these are data containers, not implementations of privacy checks.
- Added a pipeline entry point that raises NotImplementedError without reading
  files or issuing approval, and a Streamlit foundation screen.
- Added pytest coverage for imports, model construction and independent mutable
  defaults, the disabled pipeline, app startup, and environment diagnostics.
- Added Windows PowerShell and Bash setup scripts, an environment diagnostic,
  Git ignore rules for secrets/environments, and LF checkout rules for shell scripts.
- Added GitHub Actions tests on Windows and Ubuntu with Python 3.11 and locked
  uv syncing. Added concise README setup instructions.
- Preserved existing AGENTS.md edits and left PRD.md unchanged. No Phase 1+
  processing, external LLM API integration, or system software installation was added.

### Verification

- Local platform: Windows, Python **3.11.9**, uv **0.11.19**.
- `uv run pytest`: **33 passed in 10.33s**, exit code 0; no failures or skips.
- `uv run python scripts/check_env.py`: exit code 0; all ten core packages
  imported successfully and the Phase 0 Python environment reported OK.
- Streamlit AppTest passed as part of the suite. A separate headless server
  returned **HTTP 200, health=ok** from `/_stcore/health` and was stopped afterward.
- `scripts/setup.ps1` and `bash scripts/setup.sh` (Git Bash on Windows): both
  completed successfully, including `uv sync --locked` and the diagnostic.
  Bash and PowerShell syntax checks passed.
- `.env` and `.venv` ignore rules were verified; `.env.example` remains trackable.
- Reviewed the Git diff and new source/configuration files; `git diff --check`
  passed without whitespace errors. The only pre-existing change is AGENTS.md.

### Environment diagnostics

| Python package | Verified version |
| --- | --- |
| streamlit | 1.65.0 |
| pymupdf | 1.28.2 |
| python-docx | 1.2.0 |
| python-pptx | 1.0.2 |
| presidio-analyzer | 2.2.364 |
| presidio-anonymizer | 2.2.364 |
| spacy | 3.8.16 |
| pandas | 3.0.6 |
| pytesseract | 0.3.13 |
| pillow | 12.3.0 |
| pytest (development) | 9.1.1 |

### Known issues and verification limits

- **Tesseract executable is not on PATH.** The diagnostic warns without crashing;
  pytesseract itself is installed. Install Tesseract separately before OCR work.
- No spaCy language model was installed or downloaded. Configure one during
  the detection phase; none is required for Phase 0.
- uv emitted upstream package metadata normalization warnings during initial
  dependency resolution; installation and subsequent locked syncing succeeded.
- Git reports normal LF-to-CRLF checkout notices for text files on this Windows
  environment. Shell scripts explicitly retain LF endings.
- GitHub Actions is configured but has not been run remotely. Linux/macOS
  execution has not been verified locally.

### Next task

**Phase 1 document extraction:** implement native PDF, DOCX, and PPTX extraction,
scanned PDF detection, and OCR using the canonical Document/ContentBlock models.
Keep detection and redaction work in their later phases.

## Phase 1A - Native document extraction (2026-10-07)

### Completed

- Native PDF extraction with PyMuPDF: page-ordered, coordinate-sorted text
  blocks with 1-based page/block locations, original library block numbers,
  and bounding boxes. Document metadata includes page count, native alphanumeric
  character count, and pages without native text.
- DOCX extraction with python-docx: body paragraphs and top-level table cells
  in document order. Source metadata records body position and table/row/column;
  empty paragraphs retain their ordinal and merged cells are emitted once.
- PPTX extraction with python-pptx: slide text boxes, grouped shapes, and table
  cells, preserving slide order, shape-tree order, shape IDs/paths, and cell
  coordinates. Merged cells are emitted once.
- Added `privacygate.extraction.extract_document(path: str | Path) -> Document`,
  with case-insensitive PDF/DOCX/PPTX dispatch and explicit unsupported-format
  rejection. Direct interfaces are `extract_pdf`, `extract_docx`, and `extract_pptx`.
- Added `ExtractionError` and its `OCRRequiredError` subclass. PDFs below
  20 alphanumeric native-text characters raise the latter with a clear message
  that OCR may be required but was not attempted. Corrupt/unreadable inputs and
  textless Office documents fail with project errors rather than empty results.
  Parser failures do not return partial documents or expose parser messages.
- Added three small synthetic fixture documents and their regeneration script,
  plus 38 extraction tests. Updated README status and extraction usage.
- Canonical models, dependencies/lockfile, Streamlit app, and pipeline scaffold
  are unchanged. No OCR, scanned-page classification, PII detection, redaction,
  privacy validation, or LLM integration was implemented.

### Verification

- `uv run --locked python tests/fixtures/generate_fixtures.py`: exit code 0;
  generated a two-page PDF, a DOCX with paragraphs/table, and a two-slide PPTX
  with text boxes/table, all containing synthetic labels only.
- First full test run: **70 passed, 1 failed in 15.18s**. The missing-PDF test
  exposed that PyMuPDF's FileNotFoundError inherits RuntimeError rather than
  Python's built-in FileNotFoundError. Added an explicit catch for that class.
- Final `uv run --locked pytest`: **71 passed in 6.24s**, exit code 0;
  all 33 existing Phase 0 tests and all 38 new extraction tests passed.
- `uv run --locked python scripts/check_env.py`: exit code 0 on Windows with
  Python 3.11.9. All ten core packages imported successfully at the versions
  recorded for Phase 0. Tesseract was not found on PATH; pytesseract is installed.
- Reviewed Git diff and new files; `git diff --check` passed. Verified no
  `.venv`, `__pycache__`, `.pytest_cache`, bytecode, or temporary files are tracked.
  No formatter or static-analysis command is configured in this repository.
- Git emitted normal LF-to-CRLF checkout notices. No unresolved test failures.
  Remote CI and Linux/macOS execution were not run during this phase.

### Known limitations

- The PDF 20-character check is an availability heuristic, not OCR/scanned-page
  detection or proof of complete extraction. It can reject legitimate short
  PDFs; mixed native/image content can still contain unextracted text. Textless
  pages are reported without inferring whether they are scanned or blank.
- PDF coordinate sorting does not reconstruct complex reading order, columns,
  or tables. PDF annotations/forms and all image text are outside this phase.
- DOCX headers/footers, nested tables, text boxes, tracked revisions, and advanced
  layout are not covered. DOCX merged-cell deduplication uses python-docx's
  underlying cell identity (`_tc`), covered by horizontal/vertical merge tests.
- PPTX shape-tree order is not necessarily visual reading order. Notes, masters,
  charts, SmartArt, and image content are not extracted.
- Password-protected PDFs are rejected. Extracted text remains unvalidated and
  must not be treated as approved for downstream AI processing.
- Tesseract and spaCy language models were not installed. Tesseract must be
  configured separately before OCR work; this does not block native extraction.

### Next task

**Phase 1B scanned-PDF detection and OCR.** Preserve these native extractors and
their canonical source locations while adding explicit OCR handling and tests.
