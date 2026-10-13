# PrivacyGate benchmark — historical baseline (d85b251)

Generated 2026-10-07 with `scripts/evaluate.py` on Windows 10.0.26200, Python 3.11.9; commit `d85b2519cf5b35430deb17cb053792bfef6b9552`; spaCy model `en_core_web_sm`; OMP_THREAD_LIMIT=1.

Recall counts every occurrence of a ground truth value in the extracted text (a value that was never extracted counts as one missed occurrence). Residual = occurrences with any character left unredacted. Precision counts detections; detections that only overlap rows marked uncertain are excluded. See `eval/README.md`.

## Summary

| File | Recall | Precision | F1 | Residual PII rate | Structure retention | Gate (1 pass) | Gate (2 passes) | Runtime |
|---|---|---|---|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 100.0% (122/122) | 100.0% (122/122) | 100.0% | 0.0% (0) | 100.0% | APPROVED | APPROVED | 17.3 s |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | 92.4% (863/934) | 94.9% (873/920) | 93.6% | 8.6% (80) | 100.0% | BLOCKED | BLOCKED | 313.3 s |
| Cadence_TPRM_Training.docx | 59.2% (29/49) | 82.9% (29/35) | 69.0% | 40.8% (20) | 100.0% | APPROVED | APPROVED | 134.2 s |
| **All files** | **91.8%** | **95.1%** | **93.4%** | **9.0%** | | | | |

## Recall by source channel

native = digitally native text, ocr = scanned page text, image = values inside embedded images/figures (image-only).

| File | native | ocr | image | Not extracted at all |
|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 100.0% (122/122) | — | — | 0 |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | — | 98.9% (841/850) | 26.2% (22/84) | 68 |
| Cadence_TPRM_Training.docx | 92.9% (26/28) | — | 14.3% (3/21) | 0 |

## Cadence_Financial_Group_Organizational_Pack.pptx

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| EMAIL | 34 | 100.0% | 0 | 34 | 100.0% | 100.0% |
| LOCATION | 0 | n/a | 0 | 1 | 100.0% | n/a |
| PERSON | 54 | 100.0% | 0 | 53 | 100.0% | 100.0% |
| PHONE | 34 | 100.0% | 0 | 34 | 100.0% | 100.0% |

False positives by detected type: none. Ground truth rows: 122 (0 uncertain). Fuzzy (OCR-damaged) matches: 0. Blocks by extraction method: pptx_native 373.
Pipeline counts: detected count 122, redacted count 122, residual detection count 0, passes executed 1.
Extraction coverage: pages native 0, ocr 0, failed 0; embedded images attempted 0, succeeded 0, failed 0, skipped 1 (tiny 1, vector 0); warnings 1.

## Cadence_Group_Risk_Management_Policy__v6.0.pdf

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| ADDRESS | 3 | 100.0% | 0 | 4 | 100.0% | 100.0% |
| DATE_OF_BIRTH | 5 | 40.0% | 3 | 2 | 100.0% | 57.1% |
| EMAIL | 166 | 87.4% | 22 | 163 | 98.7% | 92.7% |
| EMPLOYEE_ID | 198 | 96.0% | 8 | 190 | 100.0% | 97.9% |
| FINANCIAL_ACCOUNT | 2 | 100.0% | 0 | 2 | 100.0% | 100.0% |
| GOVERNMENT_ID | 12 | 66.7% | 4 | 9 | 100.0% | 80.0% |
| IP_ADDRESS | 3 | 0.0% | 3 | 0 | n/a | n/a |
| LOCATION | 0 | n/a | 0 | 24 | 16.7% | n/a |
| PERSON | 419 | 93.1% | 34 | 392 | 99.2% | 96.1% |
| PHONE | 126 | 97.6% | 6 | 153 | 85.5% | 91.2% |

False positives by detected type: EMAIL 2, LOCATION 20, PERSON 3, PHONE 22. Ground truth rows: 870 (20 uncertain). Fuzzy (OCR-damaged) matches: 31. Blocks by extraction method: ocr 1999.
Pipeline counts: detected count 939, redacted count 949, residual detection count 0, passes executed 2.
Extraction coverage: pages native 0, ocr 35, failed 0; embedded images attempted 0, succeeded 0, failed 0, skipped 0 (tiny 0, vector 0); warnings 0.

## Cadence_TPRM_Training.docx

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| LOCATION | 0 | n/a | 0 | 2 | 0.0% | n/a |
| PERSON | 49 | 59.2% | 20 | 33 | 87.9% | 70.7% |

False positives by detected type: LOCATION 2, PERSON 4. Ground truth rows: 26 (0 uncertain). Fuzzy (OCR-damaged) matches: 1. Blocks by extraction method: docx_native 1285, embedded_image_ocr 751.
Pipeline counts: detected count 35, redacted count 35, residual detection count 0, passes executed 1.
Extraction coverage: pages native 0, ocr 0, failed 0; embedded images attempted 33, succeeded 33, failed 0, skipped 7 (tiny 2, vector 5); warnings 7.
