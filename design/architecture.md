# PrivacyGate: solution blueprint and system architecture

PrivacyGate sits between business documents and an AI model. It extracts text from PDF
(native and scanned), DOCX and PPTX files, detects and classifies PII, replaces it with
stable tokens, and only lets sanitized text through when an independent privacy gate
approves it. Everything runs locally: no network calls and no API keys.

This describes `main` together with the open pull requests for the redacted PDF / AI model
view (#13) and the identifier controls (TIN, unlabelled PESEL, card issuer checks).

Detailed extraction and detection logic: [`extraction_and_detection.md`](extraction_and_detection.md).
Identifier false-positive controls: [`false_positive_controls.md`](false_positive_controls.md).
Measured results: [`../eval/results_after.md`](../eval/results_after.md).

## 1. Functional design (file ingestion → PII detection output)

```mermaid
flowchart LR
    U[User uploads one or more<br/>PDF / DOCX / PPTX files] --> V[File validation<br/>type and parser checks]
    V --> X{Extraction<br/>per format}
    X -->|PDF page with text| PN[Native text blocks<br/>+ coordinates]
    X -->|PDF page without text| PO[Page OCR<br/>line + word boxes]
    X -->|DOCX| DX[Paragraphs, tables,<br/>headers/footers, text boxes]
    X -->|PPTX| PX[Shapes, tables,<br/>speaker notes]
    X -->|Embedded images| IO[Screenshot OCR]
    PN & PO & DX & PX & IO --> C[Canonical Document<br/>ContentBlocks with source location]
    C --> D[Hybrid PII detection<br/>NER + patterns + enterprise IDs<br/>+ name registry sweep]
    D --> R[Risk classification<br/>CRITICAL / HIGH / MEDIUM]
    R --> S[Redaction with stable tokens<br/>PERSON_001, EMAIL_004 ...]
    S --> G{Privacy gate<br/>re-scan + independent checks<br/>+ extraction completeness}
    G -->|APPROVED| OUT[Sanitized text for the AI model]
    G -->|BLOCKED| BLK[Nothing is sent<br/>reason + residual diagnostics]
    S --> A[Audit report<br/>counts only, no raw values]
    S --> M[Redacted PDF<br/>same page count]
    S --> XF[Cross-file identity view<br/>batch only, in memory]
```

**What each function guarantees**

| Function | Output | Guarantee |
|---|---|---|
| Extraction | `Document` of `ContentBlock`s | Every block keeps its source location: page/slide, paragraph, table row/column, shape path, image name, pixel or PDF boxes. A page or image whose OCR fails is recorded, never silently dropped. |
| Detection | `PIIEntity` spans (type, offsets, confidence, detectors) | Offsets point into the original block text, and detections from several detectors are merged deterministically. |
| Redaction | Sanitized `Document` + `RedactionRecord`s | The same person gets the same token across a document, or across a batch. The token mapping is never exported. |
| Privacy gate | `APPROVED` / `BLOCKED` + reason | Fails closed on residual PII, failed OCR or any error. A second pass cannot approve PII that only the independent checks caught. |
| Audit | JSON with counts by type, risk and location | No source text or values. |

## 2. System architecture (components and interactions)

```mermaid
flowchart TB
    subgraph UI["Streamlit app (app.py)"]
        UP[Upload / batch selection] --> RUN[run_pipeline / run_batch]
        TABS[Tabs: extraction, findings, redaction preview,<br/>audit export, benchmark, AI model view,<br/>cross-file identities]
    end

    subgraph EXT["privacygate.extraction"]
        PDF["pdf.py<br/>PyMuPDF native blocks<br/>parallel page OCR"]
        OCR["ocr.py<br/>Tesseract via pytesseract<br/>OMP_THREAD_LIMIT=1, retry on timeout"]
        DOCX["docx.py<br/>python-docx: body, tables,<br/>headers/footers, text boxes"]
        PPTX["pptx.py<br/>python-pptx: shapes, groups,<br/>tables, notes, pictures"]
        EMB["embedded.py<br/>image OCR, skip tiny / vector"]
        PDF --> OCR
        DOCX --> EMB
        PPTX --> EMB
        EMB --> OCR
    end

    subgraph DET["privacygate.detection"]
        PRES["presidio_detector.py<br/>Presidio + spaCy en_core_web_sm<br/>offline, PERSON / LOCATION"]
        REG["regex_detector.py<br/>emails, phones, SSN, PAN, PESEL, TIN,<br/>cards, DOB, addresses, endings"]
        CUS["custom_recognizers.py<br/>EMP / DIR / MER IDs, labelled IDs"]
        NAM["names.py<br/>allowlist, NER clean-up,<br/>name registry + sweep, role context"]
        MER["merger.py<br/>overlap resolution by specificity"]
        PRES --> NAM
        REG & CUS & NAM --> MER
    end

    subgraph RED["privacygate.redaction"]
        PS["PseudonymSession<br/>stable tokens per run / batch"]
        RD["redactor.py<br/>splices tokens, RedactionRecords"]
    end

    subgraph VAL["privacygate.validation"]
        GATE["privacy_gate.py<br/>re-scan + completeness checks"]
        IND["residual_checks.py<br/>registry names, digit runs,<br/>e-mail / ID shapes, unissued tokens"]
        GATE --> IND
    end

    subgraph OUT["Outputs"]
        AUD["audit/report.py<br/>allowlisted counts"]
        DIAG["audit/residual_diagnostics.py"]
        DERIV["derivatives.py<br/>redacted PDF"]
        LLM["llm.py<br/>payload + gated mock call"]
        XF["crossfile.py<br/>token to locations index"]
    end

    RUN --> EXT --> DET --> RISK["risk/classifier.py"] --> RED --> VAL
    VAL --> AUD & DIAG & LLM
    RED --> DERIV & XF
    OUT --> TABS
    EVAL["scripts/evaluate.py + eval/ground_truth<br/>benchmark against labelled data"] -.measures.-> RUN
```

**Interactions and data handling**

- One pipeline run works on in-memory objects. Uploaded files exist on disk only while
  processing and are deleted afterwards; OCR temp files are cleaned by pytesseract.
- The name registry built during detection is passed to the gate, so the gate can find
  leftover names without trusting the same NER model again.
- In a batch, `run_batch` merges the per-file registries and shares one `PseudonymSession`,
  so tokens line up across files. Names from other files are swept only as full names or
  dotted-initial forms.
- External dependencies are all local: PyMuPDF, python-docx, python-pptx, Pillow, Tesseract
  5.x, Presidio, spaCy `en_core_web_sm` (pinned in `uv.lock`), and Streamlit.
