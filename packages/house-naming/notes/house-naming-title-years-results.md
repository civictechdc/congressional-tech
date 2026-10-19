# Act title years: accepted literal extraction

One shared catalog rule adds 892 fields in 446 observations across 444
filenames. Every previous output remains identical after removing exactly the
predeclared additions; the other 332,924 outputs are entirely unchanged.

The reader retains `reference_marker` and `reference_year_token` separately:

| Filename wording | Extracted fields | Meaning limit |
| --- | --- | --- |
| `MortgageChoiceActof2013` | `Act`, `2013` | Printed title year, not the 2014 meeting date |
| `DroughtReliefActof1991` | `Act`, `1991` | Referenced Act year, not the bill's introduction year |
| `FACTActof2013` | `Act`, `2013` | Explicit acronym-to-title boundary |
| `Actof2019...Actof2019` | Two observations with distinct spans | Repeated references stay separate |

The changed set contains 329 `BILLS` names and 115 other names, with reference
years from 1933 through 2026. No enactment date, event date, Congress number or
document identity is inferred. Assigned person and amendment identifiers remain
protected. Existing fields and raw titles remain available.

Two names ending in `Act-of-20182` remain unsplit. A Senate source label spells
2018, but that separate observation does not establish what the final digit
means in the filename. One all-uppercase `...ACIDIFICATIONACTOF2023` title also
remains unsegmented because its word boundary is not explicit. The original
text is preserved in all three cases.

## Verification

- All 333,368 corpus inputs compared against the accepted `suffix-targets`
  outputs and the frozen native/strict baseline; one existing, reviewed strict
  Congress-boundary correction remains the only exception.
- All prior complete outputs preserved; typed adapter matches the engine for
  every input; 2,579,039 raw field spans checked.
- 2,988 regression tests pass, including 49 new title-year cases.
- Native omission and fallback detail artifacts are byte-identical after
  decompression to the previous run. The 19 previously reviewed native audit
  flags remain unchanged; no new native-field losses occur.
- Corpus mechanical gate passes, with zero structural collisions and the same
  four incomplete source payloads. Source hashes remained stable during both
  full runs and match the current code.
- Catalog artifact checks, canonical ECMAScript regex checks and whitespace
  checks pass.

Source review used 12 retained inventory records and four original House
meeting-document XML entries. No documents were fetched and no PDF body was
reviewed for this change. These are repeated development inputs, not a claim of
unseen semantic accuracy or complete interpretation of every filename.

The first 2,980-test run passed but additional probes exposed uppercase and
punctuated ordinal tails such as `2024TH` and `2024th.v2`. The initial full runs
were deliberately interrupted and retained. The corrected catalog boundaries
and eight added regression cases pass the original acceptance criteria; no
criteria were relaxed.

Evidence is under `.cache/filename-engine-comparison-20260929/`:
`title-years-expected.json`, `title-years-source-review.json`,
`title-years-ordinal-probes-first.json`, `title-years-final/`, and
`title-years-corpus-final/`. The final run contains the full preservation review
and `validation-manifest.json`, including source and evidence hashes.

Changes remain local and uncommitted. Complete filename interpretation remains
unproven; damaged source strings and ambiguous local wording still require
source context or explicitly retained uncertainty.
