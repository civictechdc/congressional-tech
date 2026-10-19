# Resolution references: accepted comparison

`house-naming` now extracts 48 GSA numbered references and 92 literal committee
or GSA resolution phrases. This adds 236 field occurrences across 140 filenames.
Every previous complete output is identical after removing those additions.

For `BILLS-116GSA2020-37ih.pdf`, the new fields are `reference_marker=GSA`,
`reference_year_token=2020` and `reference_number=37`. Congress 116, the existing
local identifier and the introduced-version code remain unchanged. The reference
does not establish a meeting date, fiscal year, project identity or adopted action.

The discovery scan selected 188 names. The 48 unchanged candidates comprise
16 already labeled resolutions, 29 person-document names containing the letters
`gsa`, one actual date form, and two joined lowercase continuations without a
supported word boundary. Their full source text remains available.

Eight saved House XML entries across six meetings confirm the reference and
phrase spellings. A `GSA 2020-37` reference occurs in a 2019 meeting, illustrating
why its year-shaped component must not set the meeting date. A retained Senate
receipt confirms that a descriptive resolution filename came from the publisher's
redirect URL. This checks source provenance and wording, not PDF contents.

| Verification | Result |
| --- | --- |
| Fixed filename inventory | 333,368 |
| Typed adapter versus engine | All equivalent |
| Raw reconstruction / field spans | 333,368 / 2,576,588 checked |
| Prior complete outputs | Preserved, apart from the 140 reviewed additions |
| New native-parser omission flags | None; prior details unchanged |
| Tests | 2,473 passed, including 44 focused cases |
| Corpus mechanical gate / rule collisions | Passed / zero |
| Filenames with residual text in audited fields | 3,253 → 3,202 |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

The shared catalog owns both rules. A known local-ID slot supplies the boundary
before a joined version code; reference digits reserve their spans before date
scans. Negative controls preserve `BiggsA`, actual dates and witness fields.

Evidence under `.cache/filename-engine-comparison-20260929/`:

- `resolution-references-discovery.json`, `resolution-references-source-review.json`
  and `resolution-references-senate-source.json`: selected names and retained sources.
- `resolution-references-unchanged-review.json`: all unchanged cases and reasons.
- `resolution-references/wording-review.json`: every addition and preservation check.
- `resolution-references/validation-manifest.json`: acceptance and source hashes.
- `resolution-references-corpus/coverage.json`: full mechanical checks.

This reused development corpus does not establish unseen accuracy or complete
semantic interpretation. Four damaged or truncated structured filenames remain
incomplete. Changes are local and uncommitted.
