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

`results_baseline_d85b251.json` and `.md` preserve the benchmark measured on commit
`d85b251`; they do not measure the current code. The dashboard reads
`results_current.json` when a fresh run creates it and otherwise shows that historical
baseline with its commit label. Generate fresh results with:

```
uv run python scripts/evaluate.py --out eval/results_current.md
```

The dashboard's residual detection count comes from the live validation scan. The
benchmark's residual occurrence rate is measured against labelled ground truth; neither
a zero scan count nor a zero measured rate proves that all PII has been removed.

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

### Review of PDF false positives (2026-10-13)

Every PDF detection that matched no labelled value was checked against the rendered pages.

- **Added** (note "added after review; …"): 18 phone numbers printed in table cells on pages
  3, 4, 6, 13, 25, 34 and 35 that wrap onto a second line and had never been labelled; the
  surname `Ashby` inside an HR extract file name on page 18; and `Miami` on page 23, labelled
  `LOCATION` because it is a customer's location tied to their card transactions (the only
  `LOCATION` row; office cities stay unlabelled).
- **Corrected** (note "corrected after review: value as printed includes country code"):
  phone rows on pages 3, 7 and 34 had been labelled without the `+1` that the page prints at the
  end of the line above (`+1` / `(212) 555-0147`); they now hold the full printed value. On page 6
  the two shorter duplicates of already-labelled `+1 (212) …` rows were removed, and the board
  chair's `+1 (212) 555-0100` on page 35 was added (as on page 32).
- **Left as false positives:** detections of values that *are* labelled, in a form the scorer
  cannot pair with the label: OCR-damaged spellings (`rbera@cadencefg.cor` for
  `r.achterberg@cadencefg.com`, `Osei-tuty`, `EMP-38056` for `EMP-38066`), truncated pieces
  (`P. Brig`), and damaged digits (`646-855-0188`, `90.42.7781`). They are real PII and are
  redacted, but the labels record the true value, digit-heavy values never match fuzzily
  (one wrong digit is a different number), and adding each OCR misreading as its own row
  would make the labels describe one OCR run instead of the document. So they lower
  precision; the matching occurrences are counted normally for recall and residual. Place
  names, register references, UI labels and OCR noise also stay false positives.

## Scoring rules

- **Occurrence matching** ignores case, spaces and punctuation and respects word boundaries.
  Letter-heavy values (names, e-mails) also match OCR-damaged text fuzzily (similarity ≥ 0.85,
  word-bounded) anywhere their exact form does not already match, so `Szewezyk` is found on a
  page that also prints `Szewczyk`. Digit-heavy values never match fuzzily.
- **Wrapped values:** OCR reads a table row across all its columns, so a value that wraps
  inside its cell comes out as two fragments with other cells' text in between
  (`…, +1 (212)` … `555-0136`). A value not found whole is also looked for as two fragments,
  split at a space or hyphen: the second fragment, then the nearest unclaimed first fragment
  at most 6 lines earlier on the same page. Fragments must match exactly with the same groups
  of letters and digits. A wrapped occurrence is **detected** only if every fragment is
  covered by a detection and **residual** if any fragment is left.
- **Not extracted:** a row whose value is not found on its page counts as one missed
  occurrence. This is how image-only content that the pipeline never extracts shows up.
- **Recall** = occurrences overlapped by any detection ÷ all occurrences.
- **Residual PII rate** = occurrences with any letter or digit left outside the redacted
  spans ÷ all occurrences. A partial redaction such as `TK[PHONE]` is detected but residual.
- **Precision** = detections overlapping a labelled occurrence ÷ all judged detections.
  Per-type precision uses the detector's type (`EMAIL_ADDRESS` → `EMAIL` etc.). `LOCATION`
  has one labelled row (a customer location); other place-name detections are false positives.
- **Channels:** `native` = digitally native text, `ocr` = scanned-page text, `image` = rows
  located in figures/screenshots (`location_type = image`) or text from embedded-image OCR.
- **Gate:** the single-pass and two-pass (app "Multi-Pass") privacy gate decisions are both
  reported; detection metrics use the first-pass detections.
- **Redaction structure preservation** (formerly "structure retention") uses
  `measure_redaction_structure_preservation`: the share of extracted blocks that sanitization
  kept in place (same id, page/slide/paragraph, non-empty text). Redaction never drops or moves
  blocks, so it is normally 100%; it says nothing about how well extraction captured the file.

## Extraction fidelity

How faithfully extraction captures the source file, scored against references built without
the extractors (`src/privacygate/structure.py`). `scripts/evaluate.py` reports it per file.

**DOCX and PPTX: XML reference.** The reference is read straight from the file's XML:
every paragraph of the body, tables (cells by row and grid column), text boxes (where they are
anchored), shapes and groups, header/footer parts and speaker notes, in document order.
Only native extracted blocks are compared; embedded-image OCR has no XML counterpart.

- **Character coverage** = letters and digits of the reference found in the extracted text
  (word multiset, each word weighted by its length) ÷ all reference letters and digits.
- **Reading order** = of consecutive reference paragraphs that are found in the extracted
  text (paragraphs of 8+ characters, looked up in order), the share found in the same order.
- **Table cells** = non-empty reference cells extracted with the same text at the same
  row and column ÷ all non-empty reference cells (body tables in DOCX, every table in PPTX).

**Scanned PDF: hand transcriptions.** `reference/<pdf stem>/page_NN.txt` are transcriptions
of three policy pages, typed from the rendered page images: page 3 (mostly prose), page 5 (a
full-page definitions table) and page 8 (the three-lines-model figure plus prose and a table).
One visual line per line, table rows read across the row, the figure read box by box; lines
starting with `#` are comments. They contain the same synthetic case-study data as the ground
truth CSVs.

- **OCR CER** = character errors ÷ reference characters. Each reference line is matched to the
  OCR line that covers most of it and scored by edit distance against the closest stretch of
  that line; an uncovered rest (OCR read a table row's cells as separate lines) is matched
  again on its own, and a line or rest with no match counts all its characters as errors.
- **Line order** = over the matched pieces in reference order, the share of consecutive pairs
  whose positions in the extracted text also increase. A table read column by column instead
  of row by row loses line order, not characters.

To add a page, transcribe it into a new `page_NN.txt`; it is picked up on the next run.

## Case study vs held-out

The case-study files were used while building and tuning the pipeline; the held-out files
(`holdout/`, generated by `scripts/make_holdout.py`) were not, and nothing is tuned on them.
Both measured with the same code (main 631078b, which this section merges into) on 2026-10-13:

| Set | Files | Recall | Precision | F1 | Residual PII rate |
|---|---|---|---|---|---|
| Case study | 3 (`ground_truth/`) | 97.4% | 92.9% | 95.1% | 3.3% |
| Held-out | 3 (`holdout/ground_truth/`) | 80.5% | 91.7% | 85.7% | 21.9% |

The gap is the expected cost of tuning on three files. Per-file results: `holdout/results.md`.

### Known gaps seen on the held-out set (not fixed, to keep it held out)

1. **Unseen staff-ID format.** `BWM-48213`-style identifiers are not detected in any of the
   three files (6 occurrences); the ID rules only know the case-study prefixes.
2. **Address wrapped over two lines** in the scanned PDF is not detected.
3. **OCR-damaged date of birth.** OCR read the year as `19711`; the DOB rule redacts
   `22 August 1971` but the labelled value is never located, so it counts as missed.
4. **Name only in speaker notes.** A full name that appears once, in PPTX notes, is not
   found by NER and has no other context.
5. **Table labels tagged as places.** "South" and "West" in a contact table and its notes
   are detected as LOCATION (false positives).
