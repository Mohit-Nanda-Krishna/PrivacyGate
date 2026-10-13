# Held-out benchmark

Three small synthetic files that the pipeline was **not** developed or tuned on, with their
ground truth. They exist to check whether the case-study numbers generalise.

| File | Layout |
|---|---|
| `docs/holdout_memo.docx` | memo: header, prose, approvals table with staff IDs, an embedded "ticket queue" screenshot with an Assignee column |
| `docs/holdout_deck.pptx` | title slide with presenter, contact table, text box, speaker notes |
| `docs/holdout_scan.pdf` | one scanned page (image only): incident report prose with DOB, address and SSN, an action table, a dark-background log figure |

All names, identifiers (`BWM-` staff IDs, phones, SSN, address, IP) and the organisation are
new: none appear in the case-study files, `src/`, `tests/` or `eval/ground_truth/`
(`tests/test_holdout.py` checks this). Values are fictitious; domains use `.example`, the IP is
from a documentation range.

`scripts/make_holdout.py` generates the files and `ground_truth/*.csv` (same columns and rules
as `eval/ground_truth/`, see `eval/README.md`). Score them with:

```
uv run python scripts/evaluate.py --ground-truth eval/holdout/ground_truth \
    --docs eval/holdout/docs --out eval/holdout/results.md --label "held-out"
```

**Rule:** do not change detectors, thresholds or allowlists because of these results. A fix
for a gap seen here must be justified and tested without these files, and the held-out set
should then be replaced by new files to stay held out.
