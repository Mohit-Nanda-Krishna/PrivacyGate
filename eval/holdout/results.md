# PrivacyGate benchmark — held-out (main 7ba5ca4 + #20, #21, #22)

Generated 2026-10-13 with `scripts/evaluate.py` on Windows 10.0.26300, Python 3.11.15; spaCy model `en_core_web_sm`; OMP_THREAD_LIMIT=1.

Recall counts every occurrence of a ground truth value in the extracted text (a value that was never extracted counts as one missed occurrence). Residual = occurrences with any character left unredacted. Precision counts detections; detections that only overlap rows marked uncertain are excluded. See `eval/README.md`.

## Summary

| File | Recall | Precision | F1 | Residual PII rate | Redaction structure preservation | Gate (1 pass) | Gate (2 passes) | Runtime |
|---|---|---|---|---|---|---|---|---|
| holdout_deck.pptx | 90.0% (9/10) | 81.8% (9/11) | 85.7% | 10.0% (1) | 100.0% | APPROVED | APPROVED | 0.6 s |
| holdout_memo.docx | 78.6% (11/14) | 100.0% (11/11) | 88.0% | 21.4% (3) | 100.0% | APPROVED | APPROVED | 0.6 s |
| holdout_scan.pdf | 76.5% (13/17) | 92.9% (13/14) | 83.9% | 29.4% (5) | 100.0% | APPROVED | APPROVED | 8.7 s |
| **All files** | **80.5%** | **91.7%** | **85.7%** | **21.9%** | | | | |

Redaction structure preservation: share of extracted blocks that sanitization kept in place (same id, location, non-empty text); it does not measure extraction.

## Extraction fidelity

How faithfully extraction captures the source file, against references built without the extractors (see `eval/README.md`).

- Character coverage: share of the reference's letters and digits found in the extracted text (DOCX/PPTX; reference read from the file's XML).
- Reading order: of consecutive reference paragraphs (or transcribed lines) found in the extraction, the share found in the same order.
- Table cells: share of non-empty reference table cells extracted with the same text at the same row and column.
- OCR CER: character error rate of the OCR'd text against hand transcriptions of scanned pages (`eval/reference/`), lower is better.

| File | Reference | Character coverage | Reading order | Table cells | OCR CER |
|---|---|---|---|---|---|
| holdout_deck.pptx | XML: 17 paragraphs, 12 table cells | 100.0% | 100.0% | 100.0% | — |
| holdout_memo.docx | XML: 18 paragraphs, 12 table cells | 100.0% | 100.0% | 100.0% | — |

## Recall by source channel

native = digitally native text, ocr = scanned page text, image = values inside embedded images/figures (image-only).

| File | native | ocr | image | Not extracted at all |
|---|---|---|---|---|
| holdout_deck.pptx | 90.0% (9/10) | — | — | 0 |
| holdout_memo.docx | 72.7% (8/11) | — | 100.0% (3/3) | 0 |
| holdout_scan.pdf | — | 81.8% (9/11) | 66.7% (4/6) | 1 |

## Recall by location type

Where the value sits in the source (ground truth `location_type`): body text, tables, unlabelled narrative prose, or inside images/figures.

| File | body | table | prose | image |
|---|---|---|---|---|
| holdout_deck.pptx | 100.0% (3/3) | 100.0% (6/6) | 0.0% (0/1) | — |
| holdout_memo.docx | 100.0% (2/2) | 25.0% (1/4) | 100.0% (5/5) | 100.0% (3/3) |
| holdout_scan.pdf | — | 100.0% (2/2) | 77.8% (7/9) | 66.7% (4/6) |

## holdout_deck.pptx

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| EMAIL | 1 | 100.0% | 0 | 1 | 100.0% | 100.0% |
| LOCATION | 0 | n/a | 0 | 2 | 0.0% | n/a |
| PERSON | 6 | 83.3% | 1 | 5 | 100.0% | 90.9% |
| PHONE | 3 | 100.0% | 0 | 3 | 100.0% | 100.0% |

False positives by detected type: LOCATION 2. Ground truth rows: 10 (0 uncertain). Fuzzy (OCR-damaged) matches: 0. Blocks by extraction method: pptx_native 17.

## holdout_memo.docx

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| EMAIL | 1 | 100.0% | 0 | 1 | 100.0% | 100.0% |
| EMPLOYEE_ID | 3 | 0.0% | 3 | 0 | n/a | n/a |
| PERSON | 9 | 100.0% | 0 | 9 | 100.0% | 100.0% |
| PHONE | 1 | 100.0% | 0 | 1 | 100.0% | 100.0% |

False positives by detected type: none. Ground truth rows: 12 (0 uncertain). Fuzzy (OCR-damaged) matches: 0. Blocks by extraction method: docx_native 18, embedded_image_ocr 5.

## holdout_scan.pdf

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| ADDRESS | 1 | 100.0% | 1 | 0 | n/a | n/a |
| DATE_OF_BIRTH | 1 | 0.0% | 1 | 1 | 0.0% | n/a |
| EMAIL | 2 | 100.0% | 0 | 2 | 100.0% | 100.0% |
| EMPLOYEE_ID | 3 | 0.0% | 3 | 0 | n/a | n/a |
| GOVERNMENT_ID | 1 | 100.0% | 0 | 1 | 100.0% | 100.0% |
| IP_ADDRESS | 2 | 100.0% | 0 | 2 | 100.0% | 100.0% |
| LOCATION | 0 | n/a | 0 | 1 | 100.0% | n/a |
| PERSON | 4 | 100.0% | 0 | 4 | 100.0% | 100.0% |
| PHONE | 3 | 100.0% | 0 | 3 | 100.0% | 100.0% |

False positives by detected type: DATE_OF_BIRTH 1. Ground truth rows: 12 (0 uncertain). Fuzzy (OCR-damaged) matches: 0. Blocks by extraction method: figure_ocr 4, ocr 15.
