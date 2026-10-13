# PrivacyGate benchmark: before vs after

Before: baseline (before fixes) (2026-10-07). After: after fixes (main 80b5b46) (2026-10-13).
Both measured with `scripts/evaluate.py` against `eval/ground_truth/` (spaCy `en_core_web_sm`). After = main 80b5b46 (#19-#27 merged), measured in one run; eval/results_current.* is the same run.

| File | Recall | Precision | F1 | Residual PII rate | Gate 1 pass | Gate 2 passes |
|---|---|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 63.9% → **100.0%** (+36.1 pt) | 91.8% → **100.0%** (+8.2 pt) | 75.4% → **100.0%** | 36.1% → **0.0%** | APPROVED → APPROVED | APPROVED → APPROVED |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | 62.0% → **97.4%** (+35.4 pt) | 82.3% → **94.4%** (+12.0 pt) | 70.7% → **95.8%** | 41.5% → **2.5%** | BLOCKED → APPROVED | APPROVED → APPROVED |
| Cadence_TPRM_Training.docx | 75.0% → **100.0%** (+25.0 pt) | 8.0% → **82.8%** (+74.8 pt) | 14.4% → **90.6%** | 25.0% → **0.0%** | BLOCKED → BLOCKED | APPROVED → BLOCKED |
| **All files** | 62.6% → **97.7%** | 64.1% → **94.4%** | 63.4% → **96.0%** | 40.4% → **2.2%** | | |

## Recall by source channel

| File | Channel | Before | After |
|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | native | 63.9% (78/122) | 100.0% (122/122) |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | ocr | 66.2% (563/850) | 99.1% (907/915) |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | image | 19.1% (16/84) | 82.7% (91/110) |
| Cadence_TPRM_Training.docx | native | 96.4% (27/28) | 100.0% (28/28) |
| Cadence_TPRM_Training.docx | image | 0.0% (0/8) | 100.0% (21/21) |

Image-channel counts can differ between runs: a value that was never extracted counts as one missed occurrence, while extracted image text counts every occurrence.

## Recall by location type

Body text, tables, unlabelled narrative prose and image-only content (ground truth `location_type`). Reports made before this split existed show —.

| File | Location | Before | After |
|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | body | — | 100.0% (54/54) |
| Cadence_Financial_Group_Organizational_Pack.pptx | table | — | 100.0% (62/62) |
| Cadence_Financial_Group_Organizational_Pack.pptx | prose | — | 100.0% (6/6) |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | body | — | 100.0% (12/12) |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | table | — | 99.4% (827/832) |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | prose | — | 95.8% (68/71) |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | image | — | 82.7% (91/110) |
| Cadence_TPRM_Training.docx | table | — | 100.0% (28/28) |
| Cadence_TPRM_Training.docx | image | — | 100.0% (21/21) |

## Read with care

- **Cadence_Group_Risk_Management_Policy__v6.0.pdf** was APPROVED by the gate (APPROVED / APPROVED) while 26 ground-truth occurrence(s) remained unredacted.

## Runtime

| File | Before | After |
|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 4.8 s | 6.0 s |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | 148.1 s | 103.0 s |
| Cadence_TPRM_Training.docx | 32.7 s | 49.7 s |

![Before vs after: recall, precision and residual PII rate per file](results_chart.png)

---

# Full report (after)

Generated 2026-10-13 with `scripts/evaluate.py` on Windows 10.0.26300, Python 3.11.15; commit `80b5b46158615d1c82a58a5bc303ff3fd5fd214c`; spaCy model `en_core_web_sm`; OMP_THREAD_LIMIT=1.

Recall counts every occurrence of a ground truth value in the extracted text (a value that was never extracted counts as one missed occurrence). Residual = occurrences with any character left unredacted. Precision counts detections; detections that only overlap rows marked uncertain are excluded. See `eval/README.md`.

## Summary

| File | Recall | Precision | F1 | Residual PII rate | Redaction structure preservation | Gate (1 pass) | Gate (2 passes) | Runtime |
|---|---|---|---|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 100.0% (122/122) | 100.0% (122/122) | 100.0% | 0.0% (0) | 100.0% | APPROVED | APPROVED | 6.0 s |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | 97.4% (998/1025) | 94.4% (1038/1100) | 95.8% | 2.5% (26) | 100.0% | APPROVED | APPROVED | 103.0 s |
| Cadence_TPRM_Training.docx | 100.0% (49/49) | 82.8% (48/58) | 90.6% | 0.0% (0) | 100.0% | BLOCKED | BLOCKED | 49.7 s |
| **All files** | **97.7%** | **94.4%** | **96.0%** | **2.2%** | | | | |

Redaction structure preservation: share of extracted blocks that sanitization kept in place (same id, location, non-empty text); it does not measure extraction.

## Extraction fidelity

How faithfully extraction captures the source file, against references built without the extractors (see `eval/README.md`).

- Character coverage: share of the reference's letters and digits found in the extracted text (DOCX/PPTX; reference read from the file's XML).
- Reading order: of consecutive reference paragraphs (or transcribed lines) found in the extraction, the share found in the same order.
- Table cells: share of non-empty reference table cells extracted with the same text at the same row and column.
- OCR CER: character error rate of the OCR'd text against hand transcriptions of scanned pages (`eval/reference/`), lower is better.

| File | Reference | Character coverage | Reading order | Table cells | OCR CER |
|---|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | XML: 410 paragraphs, 224 table cells | 100.0% | 100.0% | 100.0% | — |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | hand transcription, pages 3, 5, 8 | — | 82.5% | — | 0.2% |
| Cadence_TPRM_Training.docx | XML: 2383 paragraphs, 983 table cells | 98.8% | 100.0% | 99.4% | — |

Transcribed pages of Cadence_Group_Risk_Management_Policy__v6.0.pdf: page 3 CER 0.3%, line order 100.0% (55/55 lines found); page 5 CER 0.2%, line order 61.8% (48/48 lines found); page 8 CER 0.1%, line order 91.4% (71/71 lines found).

## Recall by source channel

native = digitally native text, ocr = scanned page text, image = values inside embedded images/figures (image-only).

| File | native | ocr | image | Not extracted at all |
|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 100.0% (122/122) | — | — | 0 |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | — | 99.1% (907/915) | 82.7% (91/110) | 26 |
| Cadence_TPRM_Training.docx | 100.0% (28/28) | — | 100.0% (21/21) | 0 |

## Recall by location type

Where the value sits in the source (ground truth `location_type`): body text, tables, unlabelled narrative prose, or inside images/figures.

| File | body | table | prose | image |
|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 100.0% (54/54) | 100.0% (62/62) | 100.0% (6/6) | — |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | 100.0% (12/12) | 99.4% (827/832) | 95.8% (68/71) | 82.7% (91/110) |
| Cadence_TPRM_Training.docx | — | 100.0% (28/28) | — | 100.0% (21/21) |

## Cadence_Financial_Group_Organizational_Pack.pptx

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| EMAIL | 34 | 100.0% | 0 | 34 | 100.0% | 100.0% |
| PERSON | 54 | 100.0% | 0 | 54 | 100.0% | 100.0% |
| PHONE | 34 | 100.0% | 0 | 34 | 100.0% | 100.0% |

False positives by detected type: none. Ground truth rows: 122 (0 uncertain). Fuzzy (OCR-damaged) matches: 0. Blocks by extraction method: pptx_native 373.
Pipeline counts: detected count 122, redacted count 122, residual detection count 0, passes executed 1.
Extraction coverage: pages native 0, ocr 0, failed 0; embedded images attempted 0, succeeded 0, failed 0, skipped 1 (tiny 1, vector 0); warnings 1.

## Cadence_Group_Risk_Management_Policy__v6.0.pdf

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| ADDRESS | 3 | 100.0% | 0 | 4 | 100.0% | 100.0% |
| DATE_OF_BIRTH | 5 | 100.0% | 0 | 9 | 55.6% | 71.4% |
| EMAIL | 178 | 96.6% | 6 | 201 | 93.5% | 95.0% |
| EMPLOYEE_ID | 203 | 98.5% | 3 | 206 | 98.5% | 98.5% |
| FINANCIAL_ACCOUNT | 2 | 100.0% | 0 | 2 | 100.0% | 100.0% |
| GOVERNMENT_ID | 12 | 91.7% | 1 | 14 | 84.6% | 88.0% |
| IP_ADDRESS | 3 | 33.3% | 2 | 2 | 50.0% | 40.0% |
| LOCATION | 1 | 100.0% | 0 | 27 | 7.4% | 13.8% |
| PERSON | 457 | 97.8% | 9 | 455 | 98.7% | 98.2% |
| PHONE | 161 | 96.9% | 5 | 201 | 95.5% | 96.2% |

False positives by detected type: DATE_OF_BIRTH 4, EMAIL 12, EMPLOYEE_ID 3, GOVERNMENT_ID 2, IP_ADDRESS 1, LOCATION 25, PERSON 6, PHONE 9. Ground truth rows: 889 (20 uncertain). Fuzzy (OCR-damaged) matches: 72. Blocks by extraction method: figure_ocr 422, ocr 1880.
Pipeline counts: detected count 1121, redacted count 1121, residual detection count 0, passes executed 1.
Extraction coverage: pages native 0, ocr 35, failed 0; embedded images attempted 0, succeeded 0, failed 0, skipped 0 (tiny 0, vector 0); warnings 0.

## Cadence_TPRM_Training.docx

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| LOCATION | 0 | n/a | 0 | 3 | 0.0% | n/a |
| PERSON | 49 | 100.0% | 0 | 55 | 87.3% | 93.2% |

False positives by detected type: LOCATION 3, PERSON 7. Ground truth rows: 26 (0 uncertain). Fuzzy (OCR-damaged) matches: 1. Blocks by extraction method: docx_native 1285, embedded_image_ocr 742.
Pipeline counts: detected count 58, redacted count 58, residual detection count 0, passes executed 1.
Extraction coverage: pages native 0, ocr 0, failed 0; embedded images attempted 33, succeeded 33, failed 0, skipped 7 (tiny 2, vector 5); warnings 7.
