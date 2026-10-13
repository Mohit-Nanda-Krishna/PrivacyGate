# False-positive controls for structured identifiers

Structured identifiers are short strings of letters and digits. Without controls, the same
shapes match reference numbers, dates, order IDs and phone numbers, and every false match
costs precision (a redacted reference number makes the sanitized text less useful to the
model). Each rule below therefore needs one of three kinds of evidence: a **label**, a
**checksum**, or a **format that is rare in ordinary text**.

Rules live in `src/privacygate/detection/regex_detector.py` and `custom_recognizers.py`.
Tests: `tests/test_id_controls.py` and `tests/test_recall_pack.py`. All test values are
synthetic.

| Identifier | Rule | Control | Why this control |
|---|---|---|---|
| **Indian PAN** | `AAAPA9999A` without a label | 4th letter must be a holder-type code (`P`, `C`, `H`, `F`, `A`, `T`, `B`, `L`, `J`, `G`) | PAN has no public check digit, but its 4th letter encodes the holder type. That cuts random 5-letter/4-digit/1-letter strings by more than half. Mixed letter-digit-letter is rare in prose. |
| **PESEL** (Poland) | With a label: `PESEL 890412xxxxx`, partly masked values accepted | The label | A labelled value is PII even when partly masked, because the visible birth-date digits still identify the person. |
| | Without a label: 11 digits | PESEL check digit (weights 1-3-7-9) **and** a valid birth date (month 01-12 plus century offset 20/40/60/80, day 1-31) | Bare 11-digit runs are common (phone numbers, account numbers, tracking numbers). The checksum accepts 1 in 10 random runs, and the date check removes most of those. |
| **US TIN / EIN** | `12-3456789` or `123456789` | Only after `TIN`, `EIN`, `FEIN`, `Tax ID` or `Taxpayer Identification Number` | The EIN format matches reference and batch numbers, and there's no public checksum, so a label is the only reliable evidence. ITINs (`9xx-xx-xxxx`) are covered by the SSN rule. |
| **US SSN / ITIN** | `ddd-dd-dddd` | Invalid area numbers `000` and `666` and group `00` / serial `0000` are rejected; `9xx` is kept (ITINs and test SSNs are still personal identifiers) | Hyphenated 3-2-4 is rare outside SSNs. |
| **Payment card** | 13-19 digits (grouped or not) | **Luhn** check **and** a real issuer prefix with a valid length (Visa, Mastercard incl. 2-series, Amex, Discover, JCB, Diners, UnionPay) | Luhn alone accepts about 1 in 10 random digit strings. The issuer and length check removes long references and account numbers that happen to pass Luhn. |
| **Card / account endings** | `card ending 2218`, `account ending in 7741` | Only after `card` / `account` and `ending`; **only the 4 digits** are redacted | Four digits alone are meaningless and everywhere (years, amounts). The phrase makes them identifying. |
| **SSN last four** | `last four digits ... (8827)`, `social security number (8827)` | Only next to those phrases | Same reasoning as card endings. |
| **Passport** | `TK4820913` | Only after `passport` (optionally `no.` / `number`) | Letter(s) followed by 7-8 digits matches many product and document codes. |
| **Phones** | International and US formats | Bare short numbers (`555 0114`) need a label (`M`, `Mobile`, `Phone`, `Tel`) or a `Mobile` / `Phone` table column header; `+CC (NNN) NNNN` is accepted without one | Seven-digit runs without context are too common. |

## Detections that look the same

When a confirmed rule (labelled TIN, checksum-valid PESEL, labelled passport) matches the
same digits as a generic phone pattern, both are kept. The merger then picks the more
specific, higher-confidence identifier type, so a labelled TIN is never reported as a
phone number.

## What these controls cost

- An unlabelled TIN/EIN or passport number is **not** detected. The independent gate checks
  (7+ digit runs, ID shapes) still block a document that contains one, so it fails closed
  rather than leaking silently.
- PAN has no checksum. A random string that happens to have a valid holder letter is still
  redacted, which costs precision, not privacy.
- OCR damage (`AQUPRI74IL` for `AQBPR7741L`) defeats format and checksum rules. Those
  occurrences show up as residual PII in the benchmark (`eval/results_after.md`).
