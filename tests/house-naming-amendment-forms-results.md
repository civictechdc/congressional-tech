# Amendment forms: 251 literal labels recovered

One catalog rule now exposes preamble, resolving-clause, title and substitute
amendment wording that both the native parser and the previous House extraction
left inside broader text. The complete comparison adds exactly 251 fields to
251 of 333,368 filenames. Every prior result remains intact; the other 333,117
complete outputs are identical.

| Printed form | Added labels | Example |
| --- | ---: | --- |
| Preamble amendment | 91 | `S. Con. Res. 10 Preamble Amendment.pdf` |
| Substitute amendment | 79 | `H.R.1036_Substitute_Amendment.pdf` |
| Resolving-clause amendment | 67 | `S. Res. 456_Resolving_Clause_Amendment.pdf` |
| Title amendment | 14 | `S. Res. 97 Title Amendment1.pdf` |

These are filename counts, including download slugs and PDF names, not distinct
document counts. Labels preserve the complete printed phrase, original spelling,
separators and offsets. They establish neither an official amendment identity nor
verified document contents. Existing numbered amendment references remain
separate. All 227 candidates already covered by a longer manager's-amendment
label remain unchanged.

## Verification

- All 3,143 tests pass, including 44 new spelling, boundary, Unicode,
  percent-escape, protected-slot, numeric-reference and repeated-phrase controls.
- Exact pre-edit predictions match every added field. Removing only those
  additions restores every prior complete result, including diagnostics,
  suppressed candidates, source pieces and fallback readings.
- The typed adapter agrees on all 333,368 inputs; all 2,579,439 field spans are
  checked. Canonical parsing and its existing narrowly reviewed correction remain
  unchanged.
- The native omission summary and all 31,761 detailed audit rows are unchanged,
  with zero unreviewed native-field omissions. All 10,659 fallback comparison rows
  are also unchanged.
- The rebuilt corpus passes its mechanical checks with zero structural
  collisions. Its shared-token inventory is identical to the previously audited
  inventory; the new labels change no token boundaries.
- Generated JSON checks, portable canonical-regex checks and source-hash checks
  pass. Both full runs completed within their 30-minute limits. No trial failed
  and no acceptance criteria changed.

The source review checked five retained inventory entries against five original
redirect receipts, covering all four forms and a hanging-`pdf` download slug.
Those receipts confirm the source filenames; no new downloads or PDF-content
classification were performed.

Evidence is retained under `.cache/filename-engine-comparison-20260929/`:
`amendment-forms-expected.json`, `amendment-forms-source-review.json`,
`amendment-forms/validation-manifest.json`, the full comparison and native audit
inside `amendment-forms/`, and `amendment-forms-corpus/`.

The broader goal remains unproven. Four damaged or truncated source payloads and
ambiguous local wording still prevent a claim of complete semantic interpretation.
This repeatedly used corpus is development evidence, not a future-file accuracy
estimate. Changes remain local and uncommitted.
