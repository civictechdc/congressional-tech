# Action wording and the complete clustering-report review

`house-naming` now retains ordered-reported, voice-vote, legislative-text and
reported/amended-by phrases as literal fields. The text following `by` stays
unresolved: it does not identify a committee or person, or verify an action.

| Check | Result |
| --- | --- |
| Fixed filename inventory | 333,368 |
| Changed filenames | 13 |
| Added observations / field occurrences | 13 / 27 |
| Previous complete results after removing those additions | All identical |
| Typed interface versus engine | All 333,368 equivalent |
| Character reconstruction / field spans | 333,368 / 2,576,352 checked |
| Tests | 2,429 passed, including 47 focused cases |
| Corpus mechanical checks / rule collisions | Passed / zero |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 newline-rejection checks |

Examples include `orderedreportedasamendedvoicevote`,
`LegislativeTextasReportedOutofCommittee` and
`reportedbyfinancialservices_vs_rcp`. Every changed filename was selected by the
discovery scan and reviewed before the full comparison. Two shorter qualifier
fields already existed; the larger phrases preserve them, so the 27 added field
occurrences contain 25 new name/span/value combinations.

The first focused run caught an incorrect split of `Bylaws` into `By` and `laws`,
and a hanging `pdf` absorbed into the following text. The rule now requires a
separator, visible CamelCase transition or explicit comparison context after
`by`, and stops before hanging `pdf`. Six other initial failures came from a
test expecting a different wording of the same caution; the corrected assertion
checks the voting-method note directly. The failed log remains saved.

Evidence lives in `.cache/filename-engine-comparison-20260929/`:

- `action-phrases-discovery.json`: all 13 selected names.
- `action-phrases-focused-first.log`: initial failures.
- `action-phrases/wording-review.json`: every addition and full-output preservation.
- `action-phrases/summary.json`, `omission-audit.json`, `iteration-summary.json`:
  comparison and audit results. The 19 previously reviewed native-parser omission
  flags are unchanged; this iteration introduces none.
- `action-phrases-corpus/coverage.json`: mechanical checks and remaining gaps.
- `action-phrases/validation-manifest.json`: accepted results and source hashes.

## All Markdown reports under output

Rechecked all 11 Markdown files recursively under `output/`, including the
segmentation profile, committee-local experiment, superseded first attempt,
restoration record and PDF content review. The complete paths and hashes match
the inventory in `complete-migration-final/validation-manifest.json`.
The detailed review is in [the migration report](house-naming-complete-migration-results.md).

The second experiment measured agreement with 11 broad source labels, not a new
taxonomy: global 77.84%, parent committee 79.65%, adaptive subcommittee/Congress
84.39%, locally fitted committee vocabulary 85.66%. The latter's 1.27-point gain
over adaptive grouping did not meet its declared 2-point advancement threshold.
The earlier 21 candidate families remain useful as a review checklist.

Current-reader probes now retain a relevant marker or wording for all 21 saved
representative examples, including the previously missing notices and summaries.
Those full outputs are in `action-phrases-category-probes.json`. This sample
does not establish category-wide accuracy. Opaque names and local abbreviations
still need explicit source associations, descriptions and committee context.

The PDF check favored filenames in two disagreements, source metadata in three,
and found a mixed document in one. Preserve those signals separately. No new
clustering run or automatic category replacement was introduced.

The full corpus is reused development evidence, not an unseen accuracy test.
Four damaged or truncated structured filenames remain incomplete. Mechanical
coverage does not prove complete semantic interpretation. Changes remain local
and uncommitted.
