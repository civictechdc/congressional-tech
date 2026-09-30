# Trailing bracketed numbers: accepted extraction

One catalog rule now exposes 149 previously opaque numeric components as
`local_number_token`. It preserves the exact digits, including leading zeros,
without claiming that the number identifies a copy, revision, report part or
document sequence.

Examples include `CHRG-113shrg91664(1).pdf`,
`Prepared Statement-Boyd-2022-03-10 (1).pdf`, and
`Witness List 3-10-22 SENR Cmte Hrg[1].pdf`. The publication number, date, person
text and other prior fields remain unchanged. In `ABC Testimony (00303050).pdf`,
all eight digits survive separately; its rejected compact-date candidate also
remains inspectable.

The 150th discovered case, `MAUREEN RIORDAN Resume (62621).pdf`, keeps its existing
plausible short-date reading. The new rule does not override dates or concrete
identifiers. Mismatched brackets, nonterminal components, query text and assigned
amendment slots do not receive this additional interpretation.

## Verification

- All 333,368 filenames compared with `title-years-final`; exactly 149 new
  fields across 149 names. Every prior complete output is preserved after
  removing those additions; 333,219 outputs are entirely unchanged.
- Typed adapter and engine agree on every input; 2,579,188 field spans checked.
- 3,024 tests pass, including 36 new cases. Catalog artifacts, canonical
  ECMAScript regex checks and whitespace checks pass.
- Corpus mechanical gate passes with zero collisions and stable source hashes.
  Four incomplete source payloads remain.
- No new native-field loss. All 10,659 fallback comparison rows are unchanged,
  and the 19 previously reviewed native audit flags remain unchanged.

One native omission-audit row changes its accounting reason. For `00303050`,
the checker now finds the identical literal as a numeric field, before consulting
the retained invalid-date receipt. Its reason changes from
`invalid_calendar_candidate` to `same_literal_other_field`; all other 31,760
rows are identical. The initial validator expected byte-identical audit output
and failed. The original validator and exact before/after row are retained; the
final validator requires precisely this reviewed change, with no new losses.
No parser change or second full run was needed after that audit review.

Source review reads three retained inventory records, including original link
attributes, and two redirect receipts confirming the unusual numeric filenames.
No document bodies were opened or downloaded. The meaning of the trailing
numbers remains unknown; this adds literal structure, not verified content.

Evidence is under `.cache/filename-engine-comparison-20260929/`:
`bracket-numbers-expected.json`, `bracket-numbers-source-review.json`,
`bracket-numbers-receipts.json`, `bracket-numbers-audit-change-review.json`,
`bracket-numbers/`, and `bracket-numbers-corpus/`. The accepted run contains
`validation-manifest.json` with source and evidence hashes.

The broader review still distinguishes actual missing components from retained
surnames, titles and local abbreviations. A residual-text count is not a count
of lost fields. Complete semantic interpretation of every filename remains
unproven. Changes are local and uncommitted.
