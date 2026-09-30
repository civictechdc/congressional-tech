# Source meaning fidelity: results

House extraction now retains more of the filename's meaning, with source
definitions available through the existing `lookup(context, code)` interface.
The qualified run is
`.cache/filename-engine-comparison-20260929/semantic-fidelity-verified/`.

| Check | Result |
| --- | ---: |
| Retained literal basenames compared | 333,368 |
| Unchanged strict parsing results | 333,368 |
| Exact source-field spans checked | 2,554,143 |
| Source-definition references checked | 495,219 |
| Lost or changed existing native code meanings | 0 |
| Tests passing | 1,213 |

Compared with the previous House run, **145,797 filenames** gain meanings or
explanations, with no added or removed raw-field signatures. This includes
137,758 collection-definition links, 16,667 explicit committee-amendment
definitions, 9,423 update-definition links and 99 clearer amendment-degree
labels. These categories overlap. All 72 real compound-identifier examples
retain their previous fields. Every native raw-field omission from earlier
extraction stages remains accounted for, with no uncategorized omission.

The extractor adds collection definitions to appropriate BILLS, CHRG, CPRT and
CRPT slots. It adds the committee-amendment definition to explicit Amdt slots,
links document updates and report components to their catalog entries, and
labels HAmdt/SAmdt with their amendment degree. The original catalog wording,
definitions, examples and source references remain unchanged.

Number notes distinguish a report part, a covered measure, an appropriation
sequence, an en bloc group, a same-day meeting sequence and an activity-report
quarter. Weekly notices identify their week-start date and explain non-Monday or
invalid values without changing the source. Descriptive version suffixes retain
their inferred-boundary note and candidates. Internal format wording such as
`xml` is explicitly distinct from the actual extension.

## Reviewed examples

- `BILLS-115-SAHR244-HAmdt2.pdf`: `HAmdt` now has the label
  “House amendment (second degree)”; lookup retains the original `HAmdt2` entry.
- `BILLS-113-027-L000579-Amdt-027-Enbloc-1.pdf`: amendment 027 and en bloc group 1
  remain separate, and the group number now explains its role.
- `CRPT-117hrpt20-p1.pdf`: report number 20 and part 1 remain separate.
- `BILLS-119hrTITLE-ORH.pdf`: the local ORH token no longer receives the
  Rules-resolution definition without the required ORH-Rule construction.
- `BILLS-112HRES-ORH-Rule-HR10.pdf`: the compound identifier preserves ORH whole;
  its RH ending is only a candidate, while the explicit Rules construction and
  covered measure remain separately readable.
- `HMTG-112-AG-Weekof20111206.pdf`: extraction retains December 6, 2011 and
  explains that it violates the Monday convention. Strict validation still fails.

Negative controls keep committee-vote CRPT prefixes and outer HMTG notice
prefixes unclassified. Generic amendment wording does not establish committee
consideration. Unknown amendment numbers do not become amendment degrees.

## Comparison improvements and correction

The comparison now retains differences in labels, notes and candidates, including
multiple observations of one source span. It also verifies that every observed
context/code pair resolves to a definition. A matching code string alone no
longer hides a label or explanatory-note difference.

Direct review of distinct native/House differences found vocabulary wording
differences such as “Introduced (House)” versus the catalog's “Introduced in
House,” added definition links, and wording changes in uncertainty notes. The
generic file-content disclaimer remains in the extraction API documentation;
it is not repeated on every catalog-backed field. Candidate sets agree on all
shared native fields in the final corpus run.

The full comparison caught seven regressions in the first expanded word-ending
safeguard: structured subtitle letters were treated as free text. The corrected
check applies only to compound identifiers. All seven real filenames now have
regression tests, including `BILLS-117SubtitleArth.pdf` and
`BILLS-119CommitteePrintSubtitleApp-U1.pdf`. The first run and the rejected
`semantic-fidelity-final` candidate remain available alongside the verified run.

This is reused development evidence, not proof that every filename is fully
interpreted. Seven malformed sponsor-slot cases are saved in
`next-sponsor-cases.json` for the next comparison; the source `KOOO395` must not
silently become a valid Bioguide identifier. Other opaque subjects and local
abbreviations also remain. Native source code and consumers are unchanged by
this iteration. All work is local and uncommitted.
