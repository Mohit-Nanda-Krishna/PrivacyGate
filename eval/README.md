# Ground truth and benchmark

`ground_truth/` holds hand-labelled PII for the three Cadence case-study files in `docs/`.
`scripts/evaluate.py` runs the pipeline on each file and scores it against these labels.

```
uv run python scripts/evaluate.py --out eval/results_before.md --label "baseline (before fixes)"
```

The report is written as Markdown plus a JSON file with the same numbers. Reports contain
counts and rates only, never document text or PII values. The PDF is fully scanned (35 OCR
pages, about 2 minutes); the script sets `OMP_THREAD_LIMIT=1` for Tesseract unless it is
already set. `--only <csv stem>` limits the run to some files and `--spacy-model` swaps the
NLP model for one run (the model must already be installed; the locked model is unchanged).

## Ground truth files

One CSV per source file, columns:

| Column | Meaning |
|---|---|
| `file` | Source file name in `docs/` |
| `page` | PDF page or PPTX slide number. Blank for DOCX body text. For DOCX screenshots, the embedded image name (`image12.png`). |
| `location_type` | `body`, `table`, `prose` (unlabelled narrative), or `image` (inside a figure, screenshot or scanned form) |
| `entity_type` | `PERSON`, `EMAIL`, `PHONE`, `EMPLOYEE_ID` (EMP-, DIR- and vendor IDs), `GOVERNMENT_ID` (SSN, PAN, passport, PESEL, SSN last four), `FINANCIAL_ACCOUNT` (card/account endings), `ADDRESS`, `DATE_OF_BIRTH`, `IP_ADDRESS` |
| `value` | The value as printed in the source (true spelling, not the OCR reading) |
| `uncertain` | `yes` = needs human review; excluded from scoring (see below) |
| `note` | Why a row is uncertain, or which figure it comes from |

A row is one value on one page. Every occurrence of that value on that page counts. Name
variants are separate rows (`Miriam T. Achebe`, `M. T. Achebe`, `M. Achebe`, `Achebe`), and
longer values claim text first, so a surname inside a full name is counted once.

### How the labels were built

1. Candidate rows came from the step-0 extracted text: a per-document registry of every
   person (with initial and surname variants), plus pattern sweeps for e-mails, phones,
   EMP-/DIR-/MER- identifiers, PANs and SSNs.
2. A manual pass covered the content those sweeps cannot see. That means the narrative prose
   in sections 16.5 and 16.8 (DOB, passport, PAN, home addresses, card/account endings, SSN
   last four) and the out-of-hours escalation in 5.2. It also covers values that only exist
   inside figures, read from rendered page images: Figures 1, 3, 4, 8, 9, 11 and 13 in the
   PDF, and screenshots `image10.png`, `image12.png`, `image35.png` and `image38.png` in the
   DOCX. Sections 7, 16.5, 16.8 and Appendix E were checked against the rendered pages.
3. A coverage check listed every name-like or ID-like string in the extracted text that no
   row covered. The only leftovers are OCR fragments of people already labelled.

### Not labelled as PII

Company names, job titles, office cities and floors ("New York 24F"), document and register
references (GRP-POL-, RSK-, ISS-, INC- …), and business dates. Detections of these count as
false positives.

### Rows to review (`uncertain = yes`)

These rows are excluded from recall, and detections that overlap only them count as neither
true nor false positives:

- Functional mailboxes `brc@`, `board@`, `gerc@`, `orc@`, `remco@` and the role mailbox
  `board.chair@`, the Speak Up hotline, and the corporate office address on page 1.
- Low-resolution values in the Figure 3 identity screenshot (employee ID, phone, manager name
  and e-mail), the masked PESEL `890412xxxxx`, the masked card `4111-XXXX-XXXX-1111`, and
  `vendor.ops@` in Figure 11.
- First-name-only OCR fragments from Figure 1.

To include a row, change `uncertain` to blank. To drop one, delete the row.

## Scoring rules

- **Occurrence matching** ignores case, spaces and punctuation and respects word boundaries.
  When a letter-heavy value (a name or e-mail) has no exact match on its page, it can match
  OCR-damaged text fuzzily (similarity ≥ 0.85). Digit-heavy values never match fuzzily.
- **Not extracted:** a row whose value is not found on its page counts as one missed
  occurrence. This is how image-only content that the pipeline never extracts shows up.
- **Recall** = occurrences overlapped by any detection ÷ all occurrences.
- **Residual PII rate** = occurrences with any letter or digit left outside the redacted
  spans ÷ all occurrences. A partial redaction such as `TK[PHONE]` is detected but residual.
- **Precision** = detections overlapping a labelled occurrence ÷ all judged detections.
  Per-type precision uses the detector's type (`EMAIL_ADDRESS` → `EMAIL` etc.); `LOCATION`
  has no ground truth type and is reported on its own row.
- **Channels:** `native` = digitally native text, `ocr` = scanned-page text, `image` = rows
  located in figures/screenshots (`location_type = image`) or text from embedded-image OCR.
- **Gate:** the single-pass and two-pass (app "Multi-Pass") privacy gate decisions are both
  reported; detection metrics use the first-pass detections.
- **Structure retention** uses `measure_structure_retention` (block-level alignment between
  the original and sanitized documents).
