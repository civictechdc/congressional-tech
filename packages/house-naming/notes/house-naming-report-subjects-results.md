# Numeric report subjects without invented report identities

`house-naming` now retains 71 numeric HRPT/SRPT subject slots as
`report_subject_token`, plus three previously missed joined Part markers and
numbers. That is 77 new fields across 71 filenames. The slot remains literal:
it does not become an official report number, bill number or embedded Congress.
Existing part readers handle the suffixes and reserve those numeric fields before
generic date or member-ID searches.

## What the raw sources establish

The initial 70-name numeric inventory had Congress.gov meeting metadata for 68
names and original House XML for 60. The wider 213-name HRPT/SRPT scan found one
additional numeric form, `HRPT-116-116-111-p1.pdf`; its retained meeting record
names H.R. 8. The combined source-metadata coverage is therefore 69 of the 71
changed names. Sixteen retained PDF bodies were hash-checked and their first two
pages extracted. Three first pages were also rendered and inspected: two had
empty/garbled extraction, and the third verified a filename/PDF discrepancy.

| Printed filename | Retained source evidence | Why the parser keeps the number's role unresolved |
| --- | --- | --- |
| `HRPT-114-1.pdf` | Cover: United States Secret Service: An Agency in Crisis; Preliminary Committee Report | No numbered House report citation appears on that cover; XML uses local legis-num 1 |
| `HRPT-114-122.pdf` | Single-page Rules Committee Record Vote No. 122, adopted 7-1 | A vote table, despite the report-style prefix |
| `HRPT-114-114-2Part1.pdf` | PDF: Rept. 114-12, Part 1, accompanying H.R. 527 | Printed subject 114-2 is not repaired to 114-12 |
| `HRPT-116-1053.pdf` | Meeting metadata names H. Res. 1053 | The numeric slot can refer to a measure |
| `HRPT-117-1.pdf` | PDF report number is 117-XXX | The filename's 1 is not the printed official report number |
| `HRPT-119-4550.pdf` | PDF: Report 119-233, accompanying H.R. 4550 | Report and measure numbers differ |
| `HRPT-119-7567-p1.pdf` | PDF: Report 119-620, accompanying H.R. 7567, Book 1 of 2 | Preserve printed p1 rather than substituting a report number or interpreting book structure |

The same basename can recur across unrelated source documents. `HRPT-118-1.pdf`
appears with multiple source descriptions, and its cached PDF is an impeachment
inquiry report with an unfilled report-number suffix. A basename alone is not a
document identity. No automatic correction, document classifier or identity
resolution was added.

## Verification

| Check | Result |
| --- | --- |
| Fixed corpus | 333,368 filenames |
| New fields / observations / changed filenames | 77 / 74 / 71 |
| Previous complete outputs after removing additions | All identical |
| Typed adapter versus engine | All 333,368 equivalent |
| Reconstruction / field spans | 333,368 / 2,577,860 checked |
| Tests | 2,757 passed; 151 focused existing/new cases passed |
| Native omission and fallback detail files | Identical to accepted prior run |
| Corpus mechanical gate / structural collisions | Passed / zero |
| Incomplete structured payloads | Four, unchanged |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

A negative control caught an unsupported joined p suffix: `123p1` was initially
accepted even though the existing p reader requires a delimiter. The corrected
rule requires that delimiter while supporting the source-proven joined Part
spelling. The failed trial remains saved. Constructed numeric subjects/parts
also verify that 12345 does not become a date and p111111 does not become a
Bioguide member ID inside the assigned report slots. Ordinary dates and member
IDs outside those slots remain recognized.

The comparison uses the previously accepted exact strict correction for joined
bill/Congress digits. This iteration changes no strict record or existing field.
Source hashes were checked after all validation. The reused corpus is development
evidence, not an unseen semantic accuracy estimate. Changes remain local and
uncommitted; complete semantic coverage is not established.

Evidence under `.cache/filename-engine-comparison-20260929/`:

- `report-subjects/validation-manifest.json` and `wording-review.json`.
- `report-subjects-corpus`, full/focused test and comparison logs.
- `numbered-hrpt-all-sources.json` and `report-subjects-additional-source.json`.
- `numbered-hrpt-pdf-review.json` and `report-subjects-visual-review.json`.
- `report-subjects-visual/`: the three inspected first-page renders.

A separate suffix inventory found three MP4 filenames, one MP3 filename and one
M3U8 filename whose suffixes are not yet captured as extensions. Four ASPX and
one CFM endpoint suffix also need separate consideration. They are recorded in
`unrecognized-suffix-discovery.json` for the next source-grounded comparison;
this iteration does not reinterpret them.
