# Printed citations and separated measure references: results

Accepted run: `.cache/filename-engine-comparison-20260929/citation-references-first/`.
Previous accepted extractor: `question-wording-context-qualified/`.

The updated extractor adds specific fields to **402 filenames** across the full
**333,368-name inventory**. Strict parsing remains unchanged for every input;
all **2,563,974 observed field spans** match the original text. **1,632 tests
pass**, including 31 new source and boundary cases. Generated JSON, ECMAScript
checks and `git diff --check` pass. The independent native parser and official
guide definitions remain unchanged.

## Direct comparison

The native parser and the previous House extractor miss separators inside
measure abbreviations such as `S-Res`. Both accept spaces and periods there.
House now also accepts hyphens and underscores through the existing rule and
measure vocabulary. This is an extension of the shared interpretation, not a
second measure parser.

| Source filename | Before | Now |
| --- | --- | --- |
| `s-res-206-062519` | Date retained; `206` generic in House, no measure fields in either parser. | `sres` measure reference with number `206`; date retained separately. |
| `S_Res_120_Managers_Preamble_Amendment.pdf` | No measure reference. | Senate resolution `120`; original title remains available. |
| `09-21-22_h._res._1298_as_amended_tally_sheet.pdf` | Date retained; no measure reference. | House resolution `1298`, with the date and surrounding text retained. |
| `S. Hrg. 115-693.pdf` | Native: extension only. House: name and generic numeric assumptions. | Printed Senate hearing citation, Congress `115`, citation number `693`. |
| `HRPT-113-HRept113-125.pdf` | Outer HRPT fields and opaque payload. | Original fields plus the embedded House report citation `113-125`. |
| `H. Rept. 118-XX (H.R. 3935).pdf` | Bill `3935` only. | Report citation with Congress `118` and placeholder `XX`; independent bill reference retained. |

The gains are:

- **210 measure references:** 193 Senate resolutions, eight Senate concurrent
  resolutions, seven Senate joint resolutions, one House resolution and one
  House bill. All 205 discovery candidates that previously lacked any measure
  number now expose one. Five additional names emerged from full comparison.
- **192 printed citations:** 164 Senate hearings and 28 House reports. Three
  reports preserve placeholders rather than acquiring invented report numbers.
  Senate report variants pass constructed controls; none were added in this
  corpus.

Printed citations use separate `citation_congress` and `citation_number` fields.
A Senate hearing number does not establish its GovInfo jacket/package number.
This distinction follows [GovInfo's hearing documentation](https://www.govinfo.gov/help/chrg).
House report citation components follow its
[report citation documentation](https://www.govinfo.gov/help/crpt).
Neither a citation nor a bill reference verifies the file's contents or resolves
its identity, and one reference's Congress is not assigned to another.

## Preservation and checks

Every changed field was compared with the prior accepted output. **131 generic
numeric fields** become specific fields at exactly the same raw spans: 76 measure
numbers, 28 citation numbers and 27 citation Congress numbers. The text of 131
removed name/subject fields remains covered by the new source fields. No shared
field metadata, existing coded field or existing code meaning changes.

Another **75 outputs change only their suppressed alternatives**, chiefly where
a possible citation overlaps an already assigned structured field. There are
477 changed outputs in total. The new reference rule respects package and witness
slots; ordinary testimony dates following bare `Hrg` do not become citations.

The 31 focused cases failed in 18 places before implementation and all pass
afterward. They cover actual PDF and URL-slug pairs, leading zeros, placeholders,
multiple citations, adjacent transcript dates, date-shaped citation numbers,
protected structured IDs and incomplete/embedded-word negative controls. The
full omission audit found no unexplained native-field omissions. Raw citation
components were inspected across all 190 initially selected matches; the full
run additionally exposed two underscore-placeholder HRPT examples.

`citation-targets-before.json` retains direct native/House examples. Full outputs
are in `extractions.jsonl.gz`; all changed outputs are in
`iteration-differences.jsonl.gz`. `candidate-review.json`, `field-review.json`,
`omission-audit.json` and the validation manifest retain the review evidence.
Broad discovery is compressed in `citation-discovery.json.gz`; it includes
false discoveries such as package prefixes and bare-Hrg dates, not just matches.

## Remaining work

This is development evidence on the reused corpus, not a claim of complete
semantic filename interpretation. Ordinary names, local identifiers and malformed
numeric dates still need attention. The next discovery inventory contains 368
date-shaped sequences with three- or five-digit final components, including
`Transcript_03.01.20231.pdf`. Some currently expose a short-date candidate from a
fragment instead of retaining the complete malformed shape. That inventory is
not yet classified and is not a count of confirmed defects.

The native application consumers remain unchanged. This work is local and
uncommitted; no source documents were downloaded.
