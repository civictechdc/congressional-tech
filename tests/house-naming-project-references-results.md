# Project references: accepted comparison

`house-naming` now exposes four literal components in all 77 reviewed GSA-style
project references, adding 308 field occurrences. For `PDC-0002-WA21`, these are
`reference_prefix_token=PDC`, `reference_identifier_token=0002`,
`reference_suffix_token=WA` and `reference_year_token=21`.

Codes remain unexpanded: no location, century, project identity or verified GSA
association is assigned from the pattern alone. Thirty-one retained House XML
entries confirm varied source examples. Some source descriptions contain slashes
that their filenames omit; the reader does not reconstruct that missing punctuation.

Every previous complete output is identical after removing the new observations.
Existing literal FY fields remain alongside references ending in `FY20` or `FY21`.
Middle identifiers reserve their spans before generic date, measure and person-ID
scans. A real date outside the reference keeps its own reading.

| Verification | Result |
| --- | --- |
| Fixed filename inventory | 333,368 |
| Changed filenames / new fields | 77 / 308 |
| Typed adapter versus engine | All equivalent |
| Raw reconstruction / field spans | 333,368 / 2,576,896 checked |
| Tests | 2,512 passed, including 39 focused cases |
| Corpus mechanical gate / collisions | Passed / zero |
| Filenames with residual text in audited fields | 3,202 → 3,151 |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

Five historical native-parser differences now classify as the same literal in
another field, rather than invalid date candidates: `03230282`, `03060189`,
`00460072` (two filenames), and `07781822`. Each is now captured whole as a
reference identifier at the original positions. The 19 previously reviewed
native omission flags remain unchanged; there are no new unexplained omissions.

Evidence under `.cache/filename-engine-comparison-20260929/`:

- `project-references-discovery.json` and `project-references-source-review.json`:
  all selected names and retained XML entries.
- `project-references/wording-review.json`: all additions and exact preservation.
- `project-references/native-reclassification-review.json`: five reviewed audit changes.
- `project-references/validation-manifest.json`: accepted checks and source hashes.
- `project-references-corpus/coverage.json`: mechanical results and remaining gaps.

The residual-report spot-check also prevents unnecessary new rules: the inspected
`transcriptpdf` already retains `pdf` as `ignored_suffix`; `113-506.pdf` retains
both numbers through the requested fallback; and `offered.zip` follows the user's
ZIP exclusion. These outputs are saved in `project-references-next-review.json`.
Residual names and titles are not automatically extraction failures.

The corpus is reused development evidence, not unseen accuracy evidence. Four
damaged or truncated structured source names remain incomplete; these checks do
not establish full semantic interpretation of every filename. Changes remain
local and uncommitted.
