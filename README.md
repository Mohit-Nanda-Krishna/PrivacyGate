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

Development in progress.