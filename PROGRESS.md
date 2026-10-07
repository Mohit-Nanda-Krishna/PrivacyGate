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

## Phase 1B - Scanned-PDF detection and OCR fallback (2026-10-07)

### Completed

- Preserved `extract_document(path) -> Document`, canonical models, and the
  existing native PDF block extraction. Native DOCX/PPTX code is unchanged.
- Applied the native-text heuristic per page: at least 20 alphanumeric native
  characters retains native blocks; fewer characters requires whole-page OCR.
  This is deterministic OCR-needed detection, not perfect scan classification.
- Implemented local OCR in `extraction/ocr.py`: PyMuPDF renders RGB at 300 DPI,
  Pillow passes the image to pytesseract, and Tesseract runs with English (`eng`),
  automatic page segmentation (`--psm 3`), and a 30-second engine timeout.
- OCR words are grouped into canonical line ContentBlocks, preserving page,
  block order, Tesseract block/paragraph/line IDs, and rendered pixel bounding
  boxes. `extraction_method` is `ocr`; native blocks remain `pdf_native`.
- Mixed PDFs preserve page order. OCR replaces sparse native output for its
  page, avoiding duplicate text. Document metadata adds `ocr_pages`; existing
  native character counts and textless-page metadata keep their native meaning.
- PATH-based executable discovery raises a clear OCRRequiredError when
  Tesseract is unavailable. Rendering, engine, malformed-output, or unusable-text
  failures raise ExtractionError and reject the entire document, with no partial
  success. OCR output below 20 alphanumeric characters is considered unusable.
- Explicitly close rendered Pillow images on success/failure. pytesseract's
  local temporary files are cleaned by its wrapper; no document images/text
  are sent to external services or intentionally persisted by PrivacyGate.
- Extended the fixture generator with deterministic image-only scanned and
  native/scanned/native PDFs. Tests generate them in temporary directories,
  with synthetic labels and no hidden native text layer in scanned pages.
- Added 23 OCR tests and updated the earlier sparse/blank-page expectations for
  required OCR. In particular, a textless page can no longer silently pass as
  partially extracted. Existing native ordering, models, and Office regressions
  remain covered. README now documents OCR setup, defaults, and limitations.
- No dependency, model, app, pipeline, CI, or environment-diagnostic changes
  were needed. No system software was installed and no Phase 2 work was added.

### Verification

- First full test run: **91 passed, 3 failed in 8.60s**. Failure tests showed
  Pillow's Image context manager did not release in-memory pixel data. Verified
  this in the installed library and fixed cleanup using `image.close()` in a
  `finally` block; the assertions were retained.
- Final `uv run --locked pytest`: **94 passed in 7.32s**, exit code 0, no skips.
  All Phase 0/1A regression cases (with the intentional OCR expectations above)
  and 23 new OCR cases passed, including three real-engine integration cases.
- Real Tesseract recognized both expected synthetic lines from scanned and
  mixed PDFs. A blank page failed closed. Temporary-file cleanup passed for
  successful OCR, blank-output failure, and an injected engine failure.
- Generated scanned/mixed PDF bytes matched across two independent generations.
- `uv run --locked python scripts/check_env.py`: exit code 0. Python **3.11.9**,
  all ten core Python packages available, and local Tesseract
  **v5.5.3.20260724** found on PATH. `tesseract --list-langs` confirmed `eng` and
  `osd`. Python package versions remain those recorded in Phase 0.
- Reviewed the Git diff and new test file; `git diff --check` passed. Verified
  no environments, caches, bytecode, temporary OCR images, or generated junk
  are tracked. No formatter/static-analysis tool is configured. Git emitted
  normal Windows LF-to-CRLF checkout notices; no unresolved test failures.
- Remote CI and Linux/macOS execution were not run. On machines without
  Tesseract, three real-engine tests explicitly skip; mocked OCR/error tests
  still run. A present but broken engine or missing English data fails tests.

### Known limitations

- The page-level character threshold may OCR legitimate short native pages and
  miss image text on pages with substantial native text. It is not a guarantee
  of complete extraction. Even truly blank pages fail if OCR yields too little
  text; blank-page exceptions have not been introduced.
- OCR is English-only and depends on scan quality and Tesseract segmentation.
  There is no deskewing, rotation correction, advanced preprocessing, or layout
  reconstruction. Sufficient character count does not prove semantic accuracy;
  recognition mistakes and omissions remain possible.
- OCR bounding boxes use rendered-image pixels (including page rotation), while
  native PDF bounding boxes use PDF coordinates. They must not be interchanged.
- pytesseract uses transient local files; normal success/error cleanup is
  tested, but abrupt process/OS termination can leave system temporary files.
- Extraction does not assess PII or grant privacy approval. Earlier native
  Office/PDF limitations remain applicable outside the new OCR fallback.

### Next task

**Phase 2 hybrid PII detection.** Add Presidio/spaCy, deterministic recognizers,
and entity merging/source mapping against the existing canonical blocks.

## Phase 2 - Hybrid PII detection (2026-10-07)

### Completed

- Added `privacygate.detection.detect_pii(document) -> list[PIIEntity]`.
  Detection runs independently on each canonical ContentBlock, using Presidio,
  spaCy-backed NER within Presidio, project regex, and enterprise recognizers.
  It is independent of file format and leaves all extraction/OCR code intact.
- Explicit Presidio baseline: **PERSON, LOCATION, EMAIL_ADDRESS, PHONE_NUMBER,
  IP_ADDRESS, CREDIT_CARD, US_SSN, IBAN_CODE**. spaCy maps PERSON to PERSON and
  GPE/LOC to LOCATION; all other NLP labels are ignored. ORGANIZATION and generic
  dates are not enabled. US_SSN uses formatted hyphenated spans only, avoiding
  arbitrary nine-digit counts. Phone validation uses US/GB/IN regional defaults.
- Project regex adds conventional/internal-domain email matching (score 0.95)
  and explicitly labelled structured/E.164 phone numbers (score 0.85).
  Presidio's minimum score is 0.4; its recognizers retain their validation/context
  scoring. spaCy's default NER confidence is a fixed 0.85, not a calibrated probability.
- Central enterprise rules add **EMPLOYEE_ID, CLIENT_ID, CUSTOMER_ID,
  PORTFOLIO_ID** (score 0.95). Employee ID/No/Number, Client ID, Customer ID, and
  Portfolio ID labels require a colon, equals sign, or hash before the value.
  Supported prefixes are EMP, CLI/C, CUST, and PF/AX respectively, with 4-10
  digits; labelled numeric-only values require 5-10 digits. Unlabelled tokens
  are not matched by these custom rules. Spans select only the identifier.
- Reused PIIEntity unchanged: offsets are `[start, end)` Python character
  indices into the original block text. Results retain block IDs and whitelisted
  page/slide/paragraph/table/shape/OCR structural positions. Bounding boxes remain
  accessible from the original ContentBlock. No raw values are stored; risk is None.
- Missing NLP, malformed detections, duplicate block IDs, conflicting source
  locations, and detector failures raise DetectionError. No detector silently
  drops out and no partial result is returned. Even empty documents require a
  successfully initialized NLP engine; an empty result grants no privacy approval.
- Explicitly preload the local spaCy model into Presidio, bypassing its runtime
  downloader. Email validation uses tldextract's bundled public-suffix snapshot
  with downloads and disk caching disabled. Presidio decision tracing is off;
  its logger is restricted to WARNING to avoid debug context text in logs.
  Only the NLP engine is cached, not document text or results.

### Dependency and setup changes

- Added **en_core_web_sm 3.8.0** (about 12 MB) using `uv add` with the official
  versioned spaCy wheel URL. uv generated its SHA-256 lock entry; uv.lock was
  not edited manually. Constrained spaCy via uv to `>=3.8.16,<3.9`, matching the
  model's 3.8-series compatibility. Installed spaCy remains **3.8.16**.
- No other package versions changed. Existing `uv sync --locked` setup and CI
  install the model automatically; no manual model-download command or API key
  is needed. Updated setup messages and README to reflect this.
- The environment diagnostic now loads the installed model and checks NER;
  model failure produces a nonzero exit. It still reports the pytesseract Python
  package and external Tesseract executable separately.

### Merge policy

- Within each block, exact duplicates collapse with maximum confidence and a
  sorted unique `|`-separated detector list. Inputs are not mutated.
- Overlapping intervals form connected components. Each component uses the
  union of its spans so overlapping tails are not discarded. The winning type
  is selected by specificity: labelled enterprise IDs, then structured PII,
  then PERSON/LOCATION. Ties use descending confidence, descending original
  span length, earliest start, then lexical entity type and detector name.
- The winner's confidence is retained; combined detector provenance means each
  source contributed a finding, not that all agreed on the winning type.
  Adjacent spans and different blocks never merge. Public output follows
  document block order and increasing offsets within each block.

### Verification

- `uv run --locked pytest`: **171 passed in 37.55s**, exit code 0, no failures
  or skips. This includes all 94 earlier tests plus 60 detection tests,
  16 merger tests, and one new model-diagnostic failure test.
- Positive cases cover all 12 supported types. Negative cases cover ordinary
  numbers, years, version strings, organization names, unlabelled codes, malformed
  regex values, and invalid enterprise contexts. Unicode offsets and page/slide/
  paragraph/OCR source associations passed; native PDF/DOCX/PPTX extraction-to-
  detection integration passed. Existing real-Tesseract tests also passed.
- Duplicate email/phone provenance, conflicting/partial/transitive overlaps,
  custom-ID precedence, input permutations, and malformed entities passed.
  Network/download prohibition and raw-PII logging checks passed. Missing NLP
  and failure of each detection source raised explicit errors as expected.
- `uv run --locked python scripts/check_env.py`: exit code 0; Python **3.11.9**,
  all ten existing core packages importable, **en_core_web_sm 3.8.0** loaded with
  NER, and Tesseract **v5.5.3.20260724** available on PATH.
- After tightening the compatible spaCy range (without changing installed
  versions), `scripts/setup.ps1` completed locked sync and diagnostics successfully.
  Bash setup syntax check passed; Bash setup was not rerun end-to-end this phase.
- Inspected the diff and new files; `git diff --check` passed. Verified no
  environments, caches, model caches, temporary documents/images, or sensitive
  artifacts are tracked. No formatter/static checker is configured.
- Only normal Windows LF-to-CRLF Git notices occurred. No unresolved failures.
  GitHub Actions and Linux/macOS execution were not run remotely/locally.

### Known limitations

- The lightweight English NER model can miss names/locations or misclassify
  business terms. Detection confidence is heuristic, not a safety guarantee.
- Per-block processing cannot recognize values or labels split across blocks;
  OCR mistakes, obfuscation, unusual international formats, and unconfigured
  enterprise identifiers can produce false negatives. Custom labels do not
  cross line breaks. The phone fallback relies on formatting and labels rather
  than assignment verification and can produce false positives.
- Conservative overlap unions may absorb harmless text or combine nearby
  findings linked by a broad NLP span. The selected type can obscure a losing
  classification; provenance retains sources, not every candidate type/score.
- spaCy/Presidio integration uses the loaded engine's `nlp` mapping; dependency
  upgrades must retain the offline and initialization tests. The offline suffix
  snapshot can age; project email regex provides additional coverage.
- Extraction and detection are not redaction or residual-PII validation.
  No risk classification, APPROVED/BLOCKED decision, database, external API,
  LLM, or Streamlit analysis workflow was added.

### Next task

**Phase 3 risk classification, semantic redaction, and secondary privacy
validation.** Preserve block-relative offsets and source associations when
consuming these normalized entities.
