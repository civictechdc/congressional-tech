# Native comparison: all field differences accounted for

The native-field audit now distinguishes 19 reviewed refinements from actual
unreviewed omissions. Neither filename parser changed. All 333,368 extraction
outputs are byte-identical after decompression to `bracket-numbers`.

| Refinement | Native fields | Evidence |
| --- | ---: | --- |
| Opaque amendment suffix divided into specific fields | 5 | Original House XML retains `KOOO395`, `Amdt`, and each amendment number |
| `ispdf` divided into `is` and hanging `pdf` | 7 | All seven Senate download URLs redirect to `...is.pdf` |
| Empty suffix moves before hanging `pdf` | 7 | Same literal split; no source characters are lost |

The auditor checks the retained characters and field boundaries. Existing
codes, labels, candidate meanings and contexts cannot use these accounting
categories. Broad descriptions, name fallbacks and generic identifiers cannot
stand in for specific replacement fields. The hanging-PDF check requires a
recognized version, adjacent literal `pdf`, and the exact source span.

These are reusable checks of the field representation, not a filename exception
list. The bounded acceptance review nevertheless requires exactly these 19
changes across the 12 inspected filenames, with every other audit row unchanged.

## Verification

- 333,368 extraction results and all 10,659 fallback comparison rows are
  byte-identical after decompression to the prior accepted run.
- Exactly 12 of 31,761 native omission-audit rows change: 19 classifications,
  with all original fields and all other classifications preserved.
- **Zero unreviewed native-field omissions** remain. This is field accounting,
  not proof that every semantic interpretation is correct.
- All 2,579,188 field spans and every typed-adapter result are checked in the
  fresh full comparison.
- 3,056 tests pass, including 32 new audit controls. Removing components,
  repairing `KOOO395` into different text, changing a code, or substituting a
  broad fallback causes the refinement check to refuse acceptance.
- Existing corpus mechanical evidence remains valid: every implementation hash
  is unchanged, with zero collisions and the same four incomplete payloads.
  The corpus was not rebuilt because its implementation and outputs did not
  change. Source and evidence hashes are verified in the new manifest.

Source review reads 17 inventory records, five original meeting-document XML
entries and seven saved redirect receipts. The original malformed sponsor token
is not repaired, and a filename version does not establish current bill status.
No new files were downloaded or document bodies opened.

The first preparation probe mistakenly assumed every omission inside a selected
row was unreviewed; some rows also contain already-accounted-for fields. The
corrected probe selects only the original `needs_review` items. The declared
19-field scope and acceptance criteria are unchanged.

Evidence is retained under `.cache/filename-engine-comparison-20260929/`:
`native-refinement-source-review.json`, `native-refinements-expected.json`,
`native-refinements/`, and the unchanged `bracket-numbers-corpus/`. The new run's
`validation-manifest.json` records exact output hashes and the audited scope.

Changes are local and uncommitted. The overall goal remains open: four damaged
or truncated source names and ambiguous local wording still prevent proving
complete semantic interpretation of every filename.
