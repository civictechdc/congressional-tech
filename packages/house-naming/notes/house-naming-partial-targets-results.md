# Partial substitute targets: accepted improvement

Two incomplete House filenames now expose **six additional fields**: the written
substitute marker, the word `to`, and the visible target text in each basename.
The reader reuses the existing `substitute-target` catalog rule only after the
normal legislative payload rules fail. No new regex or category was added.

The retained House XML contains both 145-character basenames verbatim. One is
reused for ten distinct amendment entries. Missing sponsor IDs, amendment numbers,
versions and extensions cannot be reconstructed from those truncated names.
The reader keeps each raw payload, exact field offsets and original diagnostics.
It does not turn partial target text into a complete legislative layout.

## Verification

- **2,233 tests pass**, including 17 new incomplete-source, boundary, offset,
  existing-layout and review-list checks.
- All **333,368** complete extraction results remain identical after removing
  only the two reviewed new observations. There are no other changed inputs.
- Every new field agrees with the visible source text; each has its original
  span and no invented official code or meaning.
- The typed adapter agrees with the engine on all inputs. Strict results and
  diagnostics remain unchanged from the accepted baseline.
- The corpus checks **2,575,626 field spans**, reports zero structural collisions
  and passes its mechanical gate. Source hashes remain unchanged during the run.
- The native omission audit is identical to the previous accepted audit.
- Generated schemas, ECMAScript checks and `git diff --check` pass.

All four incomplete legislative payloads remain on the review list: these two,
the truncated HR8432 title and the damaged `BILLS-115s585rfh.xmlhttps:` basename.
The latter two outputs are unchanged. Residual free text remains visible.
The lone numeric opaque identifier reported by the corpus's fallback metric is
also unchanged; that metric is not proof of missing extraction.

Evidence is under `.cache/filename-engine-comparison-20260929/`:
`partial-targets/validation-manifest.json`, `partial-targets/partial-target-review.json`,
`partial-targets/iteration-summary.json`, `partial-targets-corpus/coverage.json`,
and `partial-targets-tests.log`. Source inspection is retained in
`remaining-structured-raw-xml.json` and `remaining-structured-origins.json`.

## Relationship to the category experiments

The [complete migration review](house-naming-complete-migration-results.md)
lists all 11 Markdown files read under `output/`, including the smaller
committee/subcommittee/Congress experiment, its superseded attempt and the PDF
content check. Adaptive grouping improved source-label agreement from 77.84% to
84.39%; its 11 broad evaluation categories did not establish a finer taxonomy.

The immediate wording gaps identified there were addressed in the accepted
[category wording iteration](house-naming-category-wording-results.md): 470
additional literal fields across 466 names. Notices, announcements, summaries,
explanatory statements and manager's amendments no longer depend only on a
generic free-text field in those reviewed cases. This iteration adds six more
fields in the damaged-source cases without changing that work.

Local shorthand such as `tt` and `ISO`, explicit companion-format associations,
and conflicting source descriptions still require their associated source
records. A filename-only rule cannot safely assign those meanings globally.
The experiments remain useful evidence for targeted review; no clustering
classifier or automatic replacement of source types was adopted.

This is acceptance on a repeatedly used development corpus, not proof of complete
semantic accuracy. Changes remain local and uncommitted; the broader filename
interpretation goal remains unfinished.
