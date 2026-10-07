# PrivacyGate benchmark — baseline (before fixes)

Generated 2026-10-07 with `scripts/evaluate.py` on Windows 10.0.26300, Python 3.11.15; spaCy model `en_core_web_sm`; OMP_THREAD_LIMIT=1.

Recall counts every occurrence of a ground truth value in the extracted text (a value that was never extracted counts as one missed occurrence). Residual = occurrences with any character left unredacted. Precision counts detections; detections that only overlap rows marked uncertain are excluded. See `eval/README.md`.

## Summary

| File | Recall | Precision | F1 | Residual PII rate | Structure retention | Gate (1 pass) | Gate (2 passes) | Runtime |
|---|---|---|---|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 63.9% (78/122) | 91.8% (78/85) | 75.4% | 36.1% (44) | 100.0% | APPROVED | APPROVED | 4.8 s |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | 62.0% (579/934) | 82.3% (563/684) | 70.7% | 41.5% (388) | 100.0% | BLOCKED | APPROVED | 148.1 s |
| Cadence_TPRM_Training.docx | 75.0% (27/36) | 8.0% (21/263) | 14.4% | 25.0% (9) | 100.0% | BLOCKED | APPROVED | 32.7 s |
| **All files** | **62.6%** | **64.1%** | **63.4%** | **40.4%** | | | | |

## Recall by source channel

native = digitally native text, ocr = scanned page text, image = values inside embedded images/figures (image-only).

| File | native | ocr | image | Not extracted at all |
|---|---|---|---|---|
| Cadence_Financial_Group_Organizational_Pack.pptx | 63.9% (78/122) | — | — | 0 |
| Cadence_Group_Risk_Management_Policy__v6.0.pdf | — | 66.2% (563/850) | 19.1% (16/84) | 69 |
| Cadence_TPRM_Training.docx | 96.4% (27/28) | — | 0.0% (0/8) | 8 |

## Cadence_Financial_Group_Organizational_Pack.pptx

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| EMAIL | 34 | 100.0% | 0 | 34 | 100.0% | 100.0% |
| LOCATION | 0 | n/a | 0 | 4 | 25.0% | n/a |
| PERSON | 54 | 81.5% | 10 | 47 | 91.5% | 86.2% |
| PHONE | 34 | 0.0% | 34 | 0 | n/a | n/a |

False positives by detected type: LOCATION 3, PERSON 4. Ground truth rows: 122 (0 uncertain). Fuzzy (OCR-damaged) matches: 0. Blocks by extraction method: pptx_native 373.

## Cadence_Group_Risk_Management_Policy__v6.0.pdf

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| ADDRESS | 3 | 66.7% | 3 | 0 | n/a | n/a |
| DATE_OF_BIRTH | 5 | 0.0% | 5 | 0 | n/a | n/a |
| EMAIL | 166 | 86.8% | 25 | 160 | 99.3% | 92.6% |
| EMPLOYEE_ID | 198 | 4.0% | 191 | 0 | n/a | n/a |
| FINANCIAL_ACCOUNT | 2 | 0.0% | 2 | 0 | n/a | n/a |
| GOVERNMENT_ID | 12 | 25.0% | 10 | 2 | 100.0% | 40.0% |
| IP_ADDRESS | 3 | 0.0% | 3 | 0 | n/a | n/a |
| LOCATION | 0 | n/a | 0 | 48 | 23.4% | n/a |
| PERSON | 419 | 71.4% | 130 | 342 | 81.9% | 76.3% |
| PHONE | 126 | 97.6% | 19 | 148 | 85.0% | 90.9% |

False positives by detected type: EMAIL 1, LOCATION 36, PERSON 62, PHONE 22. Ground truth rows: 870 (20 uncertain). Fuzzy (OCR-damaged) matches: 30. Blocks by extraction method: ocr 1880.

## Cadence_TPRM_Training.docx

| Entity type | Occurrences | Recall | Residual | Detections | Precision | F1 |
|---|---|---|---|---|---|---|
| LOCATION | 0 | n/a | 0 | 29 | 0.0% | n/a |
| PERSON | 36 | 75.0% | 9 | 234 | 9.0% | 16.0% |

False positives by detected type: LOCATION 29, PERSON 213. Ground truth rows: 26 (0 uncertain). Fuzzy (OCR-damaged) matches: 0. Blocks by extraction method: docx_native 1277.
