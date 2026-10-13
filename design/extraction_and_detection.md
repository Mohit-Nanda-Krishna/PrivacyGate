# Extraction and detection logic

How each file format is read, how PII is found and classified, and how the result is
checked before anything reaches an AI model. See the diagrams in
[`architecture.md`](architecture.md) and measured results in
[`../eval/results_after.md`](../eval/results_after.md).

## 1. File structure analysis of the sample set

| File | Structure found | Extraction approach |
|---|---|---|
| Group Risk Management Policy (PDF, 35 pages) | Every page is a single scanned image: no text layer. Contains tables, narrative prose (sections 16.5 and 16.8), and figures with their own text (org chart, dashboard, scanned form, screenshots, audit log, ID badge). | Page-level OCR at 300 DPI with word boxes. Figures are OCR'd as part of their page. |
| Organizational Pack (PPTX, 9 slides) | Text shapes (org charts), grouped shapes, tables (RACI, directory), a repeated logo, speaker notes containing only slide numbers. | Shape tree including groups, table cells, speaker notes, picture OCR (the logo is skipped as tiny). |
| TPRM Training (DOCX) | Body paragraphs, 16 tables (user groups, version control), headers/footers, text boxes, 35 PNG images (33 screenshots of a TPRM tool with user names in tables, plus a logo and a button), 5 EMF vector images. | Body and tables in document order, header/footer parts, text boxes, OCR of each raster screenshot; EMF/WMF are reported as not inspected. |

## 2. Extraction per format

All extractors produce the same canonical model: a `Document` holding `ContentBlock`s in
reading order. Each block carries its text and its source location.

| Format | Library | Blocks | Location kept |
|---|---|---|---|
| PDF, page with ≥ 20 alphanumeric native characters | PyMuPDF `get_text("blocks")` | One block per text block, coordinate-sorted | page, block order, PDF bbox |
| PDF, page below that threshold (scanned) | PyMuPDF render at 300 DPI → Tesseract (`eng`, PSM 3) | One block per OCR line | page, Tesseract block/paragraph/line, pixel bbox, **word boxes** |
| DOCX | python-docx | Paragraphs, table cells (merged cells once), header/footer paragraphs, text boxes | paragraph number, table/row/column, part name, `kind` |
| PPTX | python-pptx | Shape text (incl. groups), table cells, speaker notes | slide, shape id/path, row/column, `kind` |
| Images in DOCX/PPTX | Pillow → Tesseract | One block per OCR line, `extraction_method = embedded_image_ocr` | image name, host slide/part, pixel and word boxes |

**OCR reliability.** Pages are OCR'd in parallel (up to 4) with Tesseract limited to one
thread each, so pages don't starve each other. A page that times out after 30 s is retried
once with 120 s. A page that still fails is marked `failed` in the per-page report; the
other pages are kept, and the gate blocks the document because that content was not
inspected.

**Redaction structure preservation.** Redaction replaces values inside blocks; it never
merges, drops or reorders blocks. Every block keeps its id, page/slide/paragraph and metadata,
so text before and after each value stays in place. `measure_redaction_structure_preservation`
checks block alignment, coordinates and non-empty continuity between the extracted and
sanitized documents.

**Extraction fidelity.** How much of the source structure extraction keeps is measured
separately (`privacygate.structure`, PRD target ≥ 80%): DOCX/PPTX against a reference read from
the file's XML (character coverage, reading order, table-cell preservation), and the scanned
PDF against hand transcriptions of three pages (OCR character error rate, line order). See
`eval/README.md`.

## 3. Detection logic

Detection runs per block and then across the whole document.

| Layer | What it finds | How |
|---|---|---|
| NER (Presidio + spaCy `en_core_web_sm`, offline) | People, locations | spaCy entities, then **cleaned**: split at line breaks, trimmed of non-name words, dropped if any token is on the configurable allowlist (Optiv, Cadence, Tier, Workflow, Trigger, ...) or contains digits. Single-word names survive only when the name registry confirms them. |
| Structured patterns | E-mail, phones (international, US, short `+1 (555) 0114`, labelled), SSN/ITIN, PAN, PESEL, TIN/EIN, passport, IBAN, payment cards, IP, DOB, card/account endings, SSN last four, US street addresses, OCR-damaged org e-mails | Regular expressions with labels, checksums or issuer checks (see [`false_positive_controls.md`](false_positive_controls.md)). |
| Enterprise identifiers | `EMP-38104`, `EMP100245`, `DIR-0042`, `MER-IN-4471`, labelled client/customer/portfolio/account IDs | Fixed formats, tolerant of OCR swaps (`D1R-`, `O`/`0`, `l`/`1`). |
| Context | Phones under a `Mobile`/`Phone` column header; names in cells under role headers (`Users`, `Owner`) or next to role labels (`Author(s)`, `Peer Reviewer`); a `+1` left at the end of an OCR line | Table structure and labels. |
| Name registry sweep | Every later mention of a person: `M. Achebe`, `M. T. Achebe`, `Rafael's`, first name + surname from `p.raghunathan@...` | People are registered only when corroborated (middle initial, matching e-mail, honorific, nearby identifier or role label), then all their variants are matched everywhere in the document. Short surnames that are English words are never matched alone. |
| Merger | One entity per overlapping region | The most specific type wins (enterprise IDs > addresses > identifiers > names/locations); the union of the spans is redacted so no tail is left behind. |

**Classification.** Every entity gets a type and a risk tier: **CRITICAL** (government IDs,
cards, accounts), **HIGH** (personnel/customer IDs, e-mail, phone, address, date of birth) or
**MEDIUM** (names, locations, IP addresses). The app shows each finding with its type, risk,
confidence, detectors and location (page/slide/table/image).

## 4. Redaction and the privacy gate

- **Tokens.** Each value is replaced by a typed token (`[PERSON_007]`, `[EMAIL_004]`). Name
  variants of one person share a token; in a batch the same person keeps one token across all
  files. The mapping exists only in memory.
- **Gate, layer 1:** the full detector runs again on the sanitized text; only tokens issued in
  this run are accepted as intentional.
- **Gate, layer 2 (independent of NER):** names from the original document's registry, 7+
  digit runs, e-mail shapes, personnel/PAN/SSN shapes and unissued token look-alikes. If this
  layer ever finds something, the document stays BLOCKED even after another sanitization pass.
- **Completeness:** any failed OCR page or embedded image blocks the document.
- **Errors:** any exception blocks, and the reason shows only the exception type.

## 5. What the AI model receives

The payload is the sanitized blocks in document order (`llm.py`), shown in the app's "What the
AI model sees" tab. The mock model call refuses unless the gate approved. The redacted PDF
masks exactly the spans replaced in the final sanitized text, with the same page count and
no document metadata.

## 6. Known limits (measured)

- Text inside PDF figures is read poorly by OCR: 25% recall on image-only values.
- A name that appears once, only in a screenshot, with no label or other mention, is not
  detected; such a document can be approved with that name left.
- NER LOCATION tags of countries and cities are the largest source of false positives.

Current numbers are in [`../eval/results_after.md`](../eval/results_after.md).
