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
