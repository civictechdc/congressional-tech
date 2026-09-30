# Committee-print wording and local CPT fields

The full comparison found exactly the planned 33 additional fields across 24
filenames. Every previous output remains identical after removing only the two
new observations; the other 333,344 outputs are entirely unchanged.

- Fifteen names now expose literal committee-print wording as `print_token`.
  Six other apparent gaps already had that field and receive no duplicate.
- Eight legislative CPT tails now expose `local_identifier` plus the printed
  `ih` version. One more exposes CPT plus its local number; its existing `ih`
  field stays unchanged. CPT has no inferred expansion or document type.

The source review used 40 retained inventory records, including original House
XML-derived observations and Congress.gov document metadata. A tally-sheet
filename mentions adoption of a committee print; its wording does not establish
that the file itself is a print. Captain Ambrosi's `Cpt` and assigned amendment
IDs are excluded. No document was downloaded or newly rendered for this change.

| Check | Result |
| --- | --- |
| Full fixed corpus | 333,368 filenames |
| Exact additions / affected names | 33 fields / 24 names |
| Previous complete outputs preserved | All 333,368 |
| Typed adapter versus engine | All 333,368 equivalent |
| Field spans checked | 2,578,101 |
| Regression tests | 2,863 passed, including 42 new cases |
| Corpus mechanical checks | Passed; zero collisions |
| Source limits | Four incomplete payloads remain |
| Catalog / portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

Evidence is in `.cache/filename-engine-comparison-20260929/`:
`print-wording/`, `print-wording-corpus/`, the pre-edit
`print-wording-expected.json`, source/discovery records, focused/full preservation
checks and their logs. The validation manifest verifies source hashes, native
field accounting and exact preservation against `companion-abbreviations-final`.
The existing Congress-boundary correction is the only strict-baseline exception.

All 11 Markdown files under `output/` were checked again, along with the saved
representative signals from all 21 candidate families. See
[the consolidated review](house-naming-output-review.md) for the smaller-context
experiment and practical category findings.

These repeated inputs are development evidence, not proof of complete semantic
accuracy. Filename wording remains separate from verified contents. Changes are
local and uncommitted.
