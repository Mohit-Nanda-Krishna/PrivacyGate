# PrivacyGate — Product Requirements Document

## 1. Project Overview

### Product Name
PrivacyGate

### Product Type
Pre-LLM Privacy Firewall for Business Documents

### Project Context
This project is being developed for Optiv Consulting Case Study 2: Text Analysis and PII Detection.

Cadence is a global financial services firm whose employees use a document analysis agent to review and interpret business documents.

Company policy prevents Personally Identifiable Information (PII) from being processed by AI models.

Documents submitted to the system may include:
- scanned policy documents
- PowerPoint presentations
- process documents
- other business evidence artifacts

PrivacyGate must detect and remove PII before document content is allowed to reach an AI model.

---

# 2. Problem Statement

Sensitive personal information embedded inside business documents may accidentally be exposed to AI models during document analysis.

The system must therefore:

1. accept multiple business document formats,
2. extract their textual content,
3. identify and classify PII,
4. preserve enough document structure and context to make the extracted content useful,
5. redact detected PII,
6. verify the sanitized content again,
7. prevent unsafe content from being passed downstream.

The core security requirement is:

> Raw PII must not intentionally be sent to the downstream LLM.

---

# 3. Proposed Solution

PrivacyGate is a document-aware privacy gateway positioned before an enterprise AI system.

The system processes documents through the following pipeline:

Document
→ File Validation
→ Content Extraction
→ Structure Preservation
→ PII Detection
→ Entity Normalization
→ Risk Classification
→ Redaction
→ Secondary Privacy Scan
→ Allow / Block Decision
→ Sanitized Content

Only content that passes the final privacy validation stage may proceed to downstream AI processing.

The system follows a fail-closed approach:

> If PrivacyGate cannot determine that the sanitized content satisfies the configured privacy checks, the document is blocked instead of being forwarded.

---

# 4. Product Goals

PrivacyGate must:

- support the evidence artifact formats required by the case study,
- extract usable text from both digital and scanned documents,
- preserve source location and surrounding context,
- detect multiple categories of PII,
- combine deterministic and NLP-based PII detection,
- support custom enterprise-specific PII patterns,
- classify detected PII by type and risk,
- redact PII while preserving semantic meaning,
- perform a second PII scan after redaction,
- block documents that fail the final safety check,
- provide explainable and traceable results,
- generate a useful audit summary,
- provide a simple interface suitable for a live demonstration.

---

# 5. Non-Goals

The first version of PrivacyGate will NOT attempt to:

- train a custom machine-learning model,
- replace enterprise Data Loss Prevention platforms,
- guarantee mathematically perfect PII detection,
- permanently store sensitive documents,
- build a production-scale distributed architecture,
- implement enterprise authentication or authorization,
- support every document format,
- provide pixel-perfect reconstruction of the original document,
- build a complete commercial AI platform,
- rely on an external LLM to identify raw PII.

Advanced features may only be considered after the core pipeline is fully functional.

---

# 6. Supported File Types

Initial supported formats:

## PDF
Support:
- digitally generated PDFs
- scanned PDFs

Primary extraction:
- PyMuPDF

Fallback extraction:
- OCR

## DOCX
Extraction:
- python-docx

## PPTX
Extraction:
- python-pptx

## Scanned Content
OCR:
- Tesseract OCR

Support for additional formats may be added only after the required formats work reliably.

---

# 7. Locked Technology Stack

## Core Language
Python 3.11+

## User Interface
Streamlit

## PDF Processing
PyMuPDF

## DOCX Processing
python-docx

## PPTX Processing
python-pptx

## OCR
Tesseract OCR

## PII Detection
Microsoft Presidio

## NLP
spaCy

## Structured Pattern Detection
Python regular expressions

## Data Processing
Pandas where appropriate

## Data Models
Python dataclasses or Pydantic models

## Testing
pytest

## Local Persistence
JSON initially

SQLite may only be introduced if persistent structured storage becomes necessary.

## Version Control
Git + GitHub

---

# 8. Locked System Architecture

The architecture consists of the following stages:

## Stage 1 — File Ingestion

Responsibilities:

- receive uploaded file,
- validate file type,
- generate document identifier,
- reject unsupported files,
- pass valid files to the appropriate extractor.

Output:

Document metadata + file reference

---

## Stage 2 — Content Extraction

Each file type uses its own extractor.

PDF:
- PyMuPDF for native text
- OCR when required

DOCX:
- python-docx

PPTX:
- python-pptx

The extraction layer must NOT simply produce one large string.

It must preserve structural information wherever possible.

Example:

Page 4
Paragraph 8
Text: "Employee John Smith submitted..."

or:

Slide 6
Text Box 3
Text: "Account Manager: Rahul Sharma"

---

# 9. Canonical Internal Data Model

All extraction modules must return the same logical document structure.

Conceptual model:

Document
- document_id
- filename
- file_type
- metadata
- blocks[]

Each content block should contain fields such as:

ContentBlock
- block_id
- text
- page_number
- slide_number
- paragraph_number
- extraction_method
- optional structural metadata

Fields that do not apply to a particular file format may remain null.

This shared representation is a core architectural requirement.

Extraction modules must not expose incompatible output formats to downstream components.

---

# 10. PII Detection Architecture

PrivacyGate uses hybrid PII detection.

No single detector is trusted to identify every PII category.

The detection layer consists of:

1. Presidio / NLP detection
2. Regex-based detection
3. Custom enterprise recognizers
4. Entity merging and deduplication

Pipeline:

Extracted Content
→ Presidio
→ Regex Detectors
→ Custom Recognizers
→ Entity Merger
→ Normalized PII Entities

---

# 11. Detection Layer 1 — NLP / Presidio

Presidio and NLP-based recognizers may be used to identify contextual entities such as:

- person names
- locations
- dates
- addresses
- other supported natural-language entities

Exact supported categories will depend on configured recognizers.

---

# 12. Detection Layer 2 — Regex

Regex should be used where structured patterns provide strong evidence.

Examples include:

- email addresses
- phone numbers
- IP addresses
- payment card patterns
- government identifier patterns
- account identifiers
- other deterministic structured identifiers

Regex rules must include tests.

---

# 13. Detection Layer 3 — Custom Enterprise Recognizers

The system must support organization-specific identifiers.

Examples may include:

EMP-29381

Employee ID: 38291

Client ID: C-839201

Portfolio ID: AX-9832

Customer Reference: CR-19382

These patterns should be configurable rather than hard-coded throughout the application.

Custom recognizers will be refined after studying the sample documents supplied for the case study.

---

# 14. PII Entity Model

Detected entities should be normalized into a shared format.

Conceptual structure:

PIIEntity
- entity_type
- start
- end
- confidence
- detector
- block_id
- source_location
- risk_level

Example:

Entity Type: EMAIL
Block: page_4_paragraph_2
Detector: REGEX
Confidence: 1.00
Risk: HIGH

Raw PII values should not be stored unnecessarily in audit records.

---

# 15. Entity Merging

Multiple detectors may identify the same text.

The entity merger must:

- detect overlaps,
- remove duplicate detections,
- resolve conflicting entity classifications,
- retain detector information,
- select or derive a final confidence score,
- preserve source traceability.

Example:

Presidio:
PERSON
John Smith
0.91

Custom recognizer:
PERSON
John Smith
0.95

Final result:

PERSON
Confidence: 0.95
Detectors:
- Presidio
- Custom Recognizer

The exact conflict-resolution policy must be deterministic and documented.

---

# 16. Risk Classification

Detected PII should be assigned a configurable risk level.

Initial conceptual categories:

## CRITICAL
Examples:
- government identifiers
- bank account numbers
- payment card information
- highly sensitive financial identifiers

## HIGH
Examples:
- employee identifiers
- personal contact details
- addresses
- account identifiers

## MEDIUM
Examples:
- names
- general locations
- lower-risk contextual identifiers

These mappings are project-level risk classifications and may be adjusted after reviewing the provided sample artifacts.

---

# 17. Redaction

PrivacyGate should use semantic redaction.

Example:

Original:

John Smith submitted the request using john@company.com.

Sanitized:

[PERSON] submitted the request using [EMAIL].

This is preferred over:

******** submitted the request using ********.

The objective is to remove identifying information while retaining useful context for downstream processing.

---

# 18. Redaction Requirements

Redaction must:

- remove or replace detected PII,
- preserve surrounding non-sensitive text,
- preserve document structure as much as reasonably possible,
- use meaningful placeholders,
- maintain a mapping between redactions and source locations internally during processing,
- avoid exposing original PII inside audit logs.

Initial placeholders may include:

[PERSON]

[EMAIL]

[PHONE]

[ADDRESS]

[EMPLOYEE_ID]

[ACCOUNT_NUMBER]

[GOVERNMENT_ID]

[CARD_NUMBER]

[PII]

---

# 19. Secondary Privacy Validation

Redaction is NOT considered the final step.

After redaction, the sanitized content must pass through a second detection pass.

Pipeline:

Detected Document
→ Redaction
→ Sanitized Document
→ Secondary PII Scan
→ Decision

Possible outcomes:

## APPROVED

No PII exceeding configured safety thresholds is detected.

The document may proceed to downstream AI processing.

## BLOCKED

Residual PII is detected or validation cannot safely complete.

The document must NOT proceed downstream.

---

# 20. Fail-Closed Privacy Gate

PrivacyGate must fail closed.

Examples of conditions that should block downstream processing:

- residual PII detected,
- extraction failure,
- corrupted document,
- unsupported processing state,
- detector failure affecting safety,
- redaction failure,
- validation pipeline failure.

The user should receive a clear reason for the blocked status.

A technical error must never automatically result in:

"Safe for LLM"

---

# 21. Source Traceability

Every detected entity should be traceable to its location in the source artifact where practical.

Examples:

PDF:
- page number
- paragraph/block identifier

PPTX:
- slide number
- text block identifier

DOCX:
- paragraph or section identifier

OCR:
- page number
- OCR block identifier

Example UI result:

PII Type: EMAIL

Source:
Page 4

Detector:
Regex

Confidence:
100%

Risk:
High

Status:
Redacted

---

# 22. Audit Reporting

Each analysis should generate an audit summary.

Example:

Document:
Audit_Report.pdf

Pages:
12

Detected PII:
23

Categories:

PERSON: 8
EMAIL: 4
PHONE: 3
EMPLOYEE_ID: 6
ACCOUNT_NUMBER: 2

Risk:

Critical: 2
High: 13
Medium: 8

Redacted:
23

Residual detections:
0

Final Privacy Status:
APPROVED

The audit report should NOT unnecessarily store the actual detected PII values.

Prefer:

EMAIL
Page 4
Block 9
Redacted: Yes

instead of:

john.smith@example.com

---

# 23. User Interface

The initial interface will be implemented using Streamlit.

The primary workflow should remain simple.

## Screen / State 1 — Upload

Display:

PrivacyGate

Upload Evidence Artifact

Supported:
PDF
DOCX
PPTX

Action:

Analyze Document

---

## Screen / State 2 — Extraction Summary

Display:

- filename
- file type
- pages/slides if available
- extracted block count
- extraction method
- OCR status

---

## Screen / State 3 — PII Analysis

Display detected entities in a table.

Suggested fields:

- type
- source
- detector
- confidence
- risk
- status

Also display counts by PII category.

---

## Screen / State 4 — Redaction

Allow the document to be sanitized.

Display:

- original context
- sanitized context
- redaction category

Full raw documents do not have to be shown if doing so creates unnecessary PII exposure.

---

## Screen / State 5 — Privacy Validation

Display:

Initial PII detected

PII redacted

Residual detections

Final decision

Example:

Initial PII: 23

Redacted: 23

Residual: 0

PRIVACY GATE PASSED

Approved for downstream AI processing

or:

PRIVACY GATE FAILED

Residual PII detected

Document blocked

---

# 24. Functional Requirements

## FR-01 File Upload
The system must allow supported evidence artifacts to be uploaded.

## FR-02 File Validation
The system must identify and validate supported file types.

## FR-03 PDF Extraction
The system must extract text from digital PDFs.

## FR-04 OCR
The system must support text extraction from scanned documents.

## FR-05 DOCX Extraction
The system must extract relevant content from DOCX files.

## FR-06 PPTX Extraction
The system must extract relevant textual content from PowerPoint files.

## FR-07 Structure Preservation
The system must preserve source location and surrounding context where technically possible.

## FR-08 PII Detection
The system must detect and classify supported PII types.

## FR-09 Multi-Detector Pipeline
The system must combine more than one detection technique.

## FR-10 Custom Recognizers
The system must support enterprise-specific PII patterns.

## FR-11 Confidence
Detected entities should include detection confidence where supported.

## FR-12 Risk Classification
Detected entities must be mapped to a risk category.

## FR-13 Redaction
The system must sanitize detected PII.

## FR-14 Semantic Placeholders
Redaction should preserve useful semantic context using typed placeholders.

## FR-15 Secondary Scan
Sanitized content must be scanned again.

## FR-16 Privacy Gate
The system must output an APPROVED or BLOCKED status.

## FR-17 Fail Closed
Validation failures must not result in approval.

## FR-18 Traceability
Detected entities must preserve source location information where available.

## FR-19 Audit Summary
The system must generate an analysis summary.

## FR-20 Demo Interface
The entire main pipeline must be usable from a simple graphical interface.

---

# 25. Non-Functional Requirements

## Security
Raw PII must not intentionally be sent to external LLM services.

## Privacy
Raw PII values should not be unnecessarily persisted.

## Explainability
The system should explain:
- what was detected,
- how it was detected,
- where it was found,
- its classification,
- its risk,
- whether it was redacted.

## Repeatability
Running the same deterministic configuration against the same input should produce consistent results wherever possible.

## Modularity
Each major pipeline stage must be independently testable.

## Maintainability
Modules should communicate through documented interfaces.

## Performance
The prototype should process normal case-study documents in a reasonable time suitable for a live demonstration.

## Reliability
A failure in a security-critical component must not result in approval.

---

# 26. Case Study Success Targets

The case study expects extracted content to retain at least approximately 80% of the original document structure/context.

PII detection should approach complete coverage, because unidentified PII should not be passed downstream to AI processing.

These are evaluation targets rather than guarantees.

The project must therefore prioritize PII recall while also measuring false positives.

---

# 27. Evaluation Metrics

The test dataset should contain known labelled PII entities.

Important metrics:

## Recall

Recall = TP / (TP + FN)

This is the most security-sensitive metric because false negatives represent missed PII.

## Precision

Precision = TP / (TP + FP)

This measures how many detections are actually valid.

## F1 Score

F1 = 2 × Precision × Recall / (Precision + Recall)

## Residual PII

After redaction:

Residual Rate =
Remaining PII / Original PII

Target:
as close to zero as practical.

## Structure Retention

The team should develop a reproducible method for estimating whether useful structure and surrounding context have been preserved.

The case-study target is at least approximately 80%.

---

# 28. Testing Strategy

Testing will be required at multiple levels.

## Unit Tests

Examples:

- PDF extraction
- DOCX extraction
- PPTX extraction
- regex recognizers
- custom recognizers
- entity merging
- risk classification
- redaction
- privacy validation

## Integration Tests

Example:

sample.pdf
→ extraction
→ detection
→ redaction
→ secondary scan
→ final decision

## Ground Truth Tests

Create controlled documents containing known PII.

Example:

Ground truth entities:
100

Correct detections:
97

False negatives:
3

False positives:
4

Calculate:

- recall
- precision
- F1

Testing should include both straightforward and difficult cases.

---

# 29. Project Module Interfaces

Core modules should expose predictable interfaces.

Conceptually:

extract(file)
→ Document

detect(document)
→ list[PIIEntity]

merge(entities)
→ list[PIIEntity]

classify(entities)
→ list[PIIEntity]

redact(document, entities)
→ SanitizedDocument

validate(sanitized_document)
→ ValidationResult

generate_audit(...)
→ AuditReport

Exact function names may evolve, but module boundaries should remain stable.

---

# 30. Repository Structure

privacygate/
│
├── README.md
├── PRD.md
├── PROGRESS.md
├── AGENTS.md
│
├── app.py
│
├── src/
│   └── privacygate/
│       │
│       ├── models.py
│       ├── pipeline.py
│       │
│       ├── extraction/
│       │   ├── pdf.py
│       │   ├── docx.py
│       │   ├── pptx.py
│       │   └── ocr.py
│       │
│       ├── detection/
│       │   ├── presidio_detector.py
│       │   ├── regex_detector.py
│       │   ├── custom_recognizers.py
│       │   └── merger.py
│       │
│       ├── redaction/
│       │   └── redactor.py
│       │
│       ├── validation/
│       │   └── privacy_gate.py
│       │
│       ├── risk/
│       │   └── classifier.py
│       │
│       └── audit/
│           └── report.py
│
├── tests/
│   ├── fixtures/
│   ├── test_extraction.py
│   ├── test_detection.py
│   ├── test_redaction.py
│   └── test_pipeline.py
│
├── requirements.txt
├── .gitignore
└── .env.example

---

# 31. Development Phases

## Phase 0 — Foundation

Deliverables:

- repository structure
- Python environment
- dependencies
- canonical data models
- Streamlit skeleton
- pytest setup
- AGENTS.md
- PROGRESS.md

Success condition:

The application starts successfully and tests can run.

---

## Phase 1 — Document Extraction

Implement:

- PDF native extraction
- scanned PDF detection
- OCR
- DOCX extraction
- PPTX extraction
- canonical ContentBlock output

Success condition:

Supported documents produce structured extracted content.

---

## Phase 2 — PII Detection

Implement:

- Presidio
- spaCy configuration
- regex recognizers
- custom recognizers
- entity merger
- source mapping
- confidence handling

Success condition:

Extracted documents produce normalized PIIEntity objects.

---

## Phase 3 — Redaction and Privacy Gate

Implement:

- semantic redaction
- risk classification
- second PII scan
- fail-closed validation
- APPROVED / BLOCKED result

Success condition:

The backend pipeline works end-to-end.

---

## Phase 4 — User Interface

Implement:

- upload
- extraction summary
- PII findings
- risk summary
- redaction preview
- final privacy decision
- audit summary

Success condition:

A user can complete the entire workflow without using the command line.

---

## Phase 5 — Evaluation

Build labelled test documents.

Measure:

- recall
- precision
- F1
- residual PII
- structure retention

Analyze failures.

Tune:

- thresholds
- regex rules
- custom recognizers

Success condition:

Evaluation results can be shown during the presentation.

---

## Phase 6 — Final Polish

Work only after the core system is stable.

Tasks:

- UI improvements
- architecture diagram
- functional diagram
- presentation
- demo script
- final test suite
- documentation
- screenshots

---

# 32. MVP Definition

The Minimum Viable Product is complete when:

1. A PDF, DOCX or PPTX can be uploaded.
2. Text can be extracted.
3. Scanned PDFs can be processed through OCR.
4. Extracted text maintains source metadata.
5. Multiple categories of PII can be detected.
6. Regex and NLP-based detection are both functional.
7. Enterprise custom recognizers are supported.
8. Detected entities are normalized and deduplicated.
9. PII is redacted using semantic placeholders.
10. Sanitized content is rescanned.
11. Unsafe documents are blocked.
12. Safe documents receive APPROVED status.
13. Findings are visible through Streamlit.
14. An audit summary is available.
15. Automated tests verify the core pipeline.

---

# 33. Optional / Stretch Features

Do NOT implement these until the MVP is stable.

Possible stretch features:

- configurable detection thresholds
- custom recognizer configuration UI
- downloadable sanitized files
- downloadable audit reports
- visual PII highlighting
- richer analytics
- advanced OCR
- table extraction
- image-region redaction
- actual downstream LLM integration
- authentication
- database persistence
- cloud deployment

These are secondary to the core case-study requirements.

---

# 34. Security Principles

The following principles are mandatory:

1. Privacy processing occurs before downstream AI processing.
2. Raw PII should not be sent to an external LLM.
3. Raw PII should not be logged unnecessarily.
4. Processing failures must fail closed.
5. Audit logs should contain metadata rather than unnecessary PII values.
6. Every approval decision must be explainable.
7. Redaction must be followed by verification.
8. Security-critical tests must not be silently bypassed.
9. External dependencies must not quietly transmit document content.
10. No claim of perfect PII detection should be made without evidence.

---

# 35. Demo Scenario

The final demonstration should follow one simple story.

## Step 1

Upload a business document containing multiple forms of PII.

## Step 2

PrivacyGate extracts its contents.

Show:

- document type
- pages/slides
- extraction method
- number of blocks

## Step 3

PrivacyGate analyzes the document.

Show:

- detected PII categories
- count
- confidence
- source location
- risk

## Step 4

Redact the document.

Show original and sanitized examples.

Example:

John Smith
→ [PERSON]

john@example.com
→ [EMAIL]

EMP-29382
→ [EMPLOYEE_ID]

## Step 5

Run the secondary privacy scan.

Display:

Initial PII: 18
Redacted: 18
Residual: 0

## Step 6

Display:

PRIVACY GATE PASSED

Content approved for downstream AI processing.

Also demonstrate at least one failure case in which residual PII causes:

PRIVACY GATE FAILED

Document blocked from downstream AI processing.

---

# 36. Final Product Positioning

PrivacyGate should NOT be presented merely as:

"an application that detects PII."

It should be presented as:

> A document-aware, fail-closed privacy gateway that protects enterprise AI pipelines by detecting, classifying and sanitizing sensitive information before it reaches an AI model.

The main differentiators of the prototype are:

- hybrid PII detection,
- document-aware source traceability,
- enterprise-specific recognizers,
- context-preserving semantic redaction,
- secondary residual-PII validation,
- fail-closed downstream access control,
- explainable audit reporting.

The novelty claim should be conservative.

PII detection and redaction already exist as established technologies.

The value of PrivacyGate lies in integrating these capabilities into an explainable, document-aware pre-LLM security control aligned with the given business problem.

---

# 37. Case Study Alignment

The solution must remain aligned with the supplied Optiv case-study brief.

The brief requires the team to:

- analyze the structure of supplied sample documents,
- determine appropriate extraction methods for each file type,
- extract text,
- detect and classify PII,
- apply transparent tags,
- preserve source traceability,
- surface PII exposure,
- prevent PII from reaching AI processing.

The expected solution also includes:

- a functional solution blueprint,
- system architecture,
- extraction and detection logic,
- reliable outcomes,
- and a live working demonstration.

No architectural change should weaken these requirements.

---

# 38. Source of Truth

This PRD defines the intended PrivacyGate product architecture and scope.

All coding agents and contributors should read:

1. PRD.md
2. AGENTS.md
3. PROGRESS.md

before making significant changes.

Architecture or technology-stack changes must not be introduced without explicit team approval.

PROGRESS.md should contain the current implementation status and should be updated as development progresses.