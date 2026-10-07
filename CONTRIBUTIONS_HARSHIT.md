# Contributions & Work Log — Harshit (`harshit-git404`)

This document tracks all contributions, architectural enhancements, implementation milestones, and commits made by Harshit on the **PrivacyGate** pre-LLM privacy firewall project.

---

## Environment & Setup Milestone

- **Date**: 2026-10-07
- **Work Performed**:
  - Initialized and validated the development environment on Windows with Python 3.11.9.
  - Installed `uv` package manager (`uv 0.12.23`) into the Python 3.11 toolchain.
  - Synchronized locked project dependencies (`uv sync --locked`) installing all 90 core packages (including Presidio Analyzer, Presidio Anonymizer, spaCy, PyMuPDF, python-docx, python-pptx, Streamlit, Pandas, Pillow, pytesseract, pytest).
  - Configured spaCy English core pipeline (`en_core_web_lg` 3.8.0) for high-accuracy NLP entity recognition.
  - Executed baseline environment diagnostic (`check_env.py`) and verified existing 91 tests pass cleanly.

---

## Commit: Phase 2 — Hybrid PII Detection Engine

- **Author**: Harshit (`harshit-git404`)
- **Scope**: Hybrid PII Detection (Regex, Custom Enterprise, Presidio NLP, Entity Merger)
- **Files Added / Changed**:
  - `src/privacygate/detection/regex_detector.py`: Implemented structured pattern matching for Email, Phone numbers, valid IPv4, US SSN, IBAN, and Credit Cards with mathematical Luhn algorithm checksum verification.
  - `src/privacygate/detection/custom_recognizers.py`: Implemented enterprise-specific pattern recognition for Employee IDs (`EMP-XXXX`, `Employee ID:`), Client IDs (`C-XXXXX`), Portfolio IDs (`AX-XXXX`), Customer References (`CR-XXXX`), and Account Numbers (`ACC-XXXX`), with runtime extensibility.
  - `src/privacygate/detection/presidio_detector.py`: Implemented Microsoft Presidio NLP wrapper with lazy initialization, spaCy backend, canonical type mapping, and score thresholding.
  - `src/privacygate/detection/merger.py`: Implemented deterministic entity merger, overlap clustering, priority resolution (Enterprise > Regex > Presidio), tie-breaking, and detector provenance chaining.
  - `src/privacygate/detection/__init__.py`: Exposed high-level `detect_pii(document)` and `detect_pii_in_block(block)` with automatic source coordinate propagation (`page_number`, `slide_number`, `paragraph_number`).
  - `tests/test_detection.py`: Added 18 comprehensive tests verifying all detection mechanisms, Luhn algorithm, custom patterns, Presidio entities, and document-level integration.
  - `PROGRESS.md`: Documented Phase 2 deliverables, verification results, and next task.
- **Verification & Test Results**:
  - `uv run pytest`: 109 passed, 3 skipped, 0 failures.

