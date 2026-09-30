# Extracted filename metadata: head-to-head results

Compared all **333,368** recovered literal filenames/URL basenames. On the
**202,063** filenames both parsers recognize, `house_naming` generally provides
clearer field roles and fewer misleading candidates. The internal extractor
provides useful additional structure in several families and covers more names.
Neither output is a complete replacement for the other as currently implemented.

A = `congress_api.filenames.parse_filename`; B = `house_naming.Engine.parse`.
These results analyze the complete native outputs of the latest implementation
run, not the earlier strict House parser. All recorded source hashes still
matched the working files. This analysis changes no production parser.

## What agrees

For **201,949 / 202,063** accepted names, every compared B scalar value occurs
in A's captures. Across all accepted names, **1,208,546** scalar checks found the
expected value. The remaining **114** checks are the 90 appropriations
descriptions, 18 pre-introduction descriptions and six report parts below.

Congress, bill type/number, stage, committee code, named meeting/vote date,
witness identifier, sponsor/member identifier, amendment/en-bloc identifier,
revision, document number and publication number all have their expected values
somewhere in A. That is containment, not proof that all additional A candidates
are correct or that either parser's assigned roles match document contents.

Much of the difference is representation:

| House field or role | Accepted filenames | Internal representation |
| --- | ---: | --- |
| `meetingDate` | 141,203 | Generic `date_token` plus enclosing rule |
| `voteDate` | 8,441 | Generic `date_token` plus enclosing rule |
| `witnessId` | 89,812 | `subject_token` |
| `sponsorBioguideId` | 8,634 | `bioguide_token` in a sponsored-amendment layout |
| `memberBioguideId` | 5,691 | `subject_token` plus `bioguide_token` |
| `kind` | 202,063 | Outer/inner rules and literal document markers |

House makes these roles easier to consume. It does not independently identify
the witness or validate the document against a meeting. Internal fields retain
exact raw spelling, offsets, rule provenance and candidate/uncertainty notes.
House retains the entire original `input`, typed fields and canonical filename,
but does not expose per-field source offsets. Integer typing and code-case
normalization are representation changes, not additional source evidence.

Literal markers implicit in House kinds are not lost: for example `WState`,
`Bio`, `TTF`, `PIH`, and `SUS` are represented by the corresponding kind.
Internal code labels and vocabulary URLs are convenient annotations; House
also exposes code definitions through `Engine.lookup`.

## Useful information in each direction

Counts refer to filenames, not distinct documents. Categories can overlap.

| Pattern | Count | Internal A | House B | Direction |
| --- | ---: | --- | --- | --- |
| Appropriations routing/subject | 90 | Fiscal-year tokens in all 90; explicit AP routing codes in 45; recognized subject tokens in 72; separate descriptor | `description` retains the combined text | A gives more queryable structure |
| Published-hearing suffixes | 136 | Separates literal part/volume/addendum/errata markers and identifiers | Retains the combined `publicationSuffix` | A gives more structure; B preserves the text |
| Bioguide-shaped witness IDs | 2,480 | Recognizes the identifier shape in addition to the witness token | Keeps the same string as `witnessId` | A adds a useful identifier classification, not verified identity |
| Pre-introduction descriptions | 18 | Description remains inside `suffix` | Explicit `description` | B gives more structure |
| Conference-report component tokens | 6 | Component remains inside `payload` | Explicit `part`: JES (3), NOCOVSIG (2), Sig (1) | B gives more structure |
| Amendment identifier plus trailing metadata | 755 | Correct separate fields coexist with a broad amendment-tail capture | One `amendmentId`, separate `enblocId`/`revision` | B is easier to consume without reconciling overlaps |

The amendment-tail cases comprise 529 en-bloc filenames and 226 other amended
filenames with revisions. House retains 139 nonempty publication suffixes;
internal marker rules decompose 136, leaving three opaque in both outputs.
Fiscal years are literal tokens: one of the 90 appropriations names lacks a
year in the routing slot but includes `FY2018` in its description. The internal
search finds it there; this does not fill the absent source slot.

### Direct examples

`BILLS-113HR-FC-AP-FY2014-AP00-Agriculture.pdf`

```text
A: scope_token=FC, committee_token=AP, fiscal_year_token=2014,
   committee_code=AP00, descriptor=Agriculture,
   appropriation_subject=Agriculture
B: stage=FC, description=AP-FY2014-AP00-Agriculture
```

`CHRG-107shrg87708-volII.pdf`

```text
A: publication_marker=vol, publication_identifier=II
B: publicationSuffix=-volII
```

`BILLS-113hjres-PIH-FOOD.pdf`

```text
A: measure_token=hjres, version_token=PIH, suffix=-FOOD
B: kind=bill-preintroduced, measureType=hjres, description=FOOD
```

`CRPT-114HRPT-S1177-NOCOVSIG.xml`

```text
A: payload=S1177-NOCOVSIG, measure_token=S, measure_number=1177
B: measureType=S, measureNumber=1177, part=NOCOVSIG
```

`BILLS-113-HConRes51-S000522-Amdt-051-Enbloc-2.pdf`

```text
A: amendment_token=051-Enbloc-2, amendment_token=051,
   amendment_identifier=051, enbloc_number=2
B: amendmentId=051, enblocId=2
```

These examples omit common fields for readability. Complete native results,
including original filenames and exact spans, remain in the paired outputs.

## Extra internal candidates that are misleading

The following counts apply only to the 202,063 accepted House names. The
comparison checks span collisions against the structured filename slots;
it does not assume every extra capture is useful metadata.

| Pattern | Filenames | Evidence and practical meaning |
| --- | ---: | --- |
| Bill reference inside a Bioguide ID | 1,428 | `S000030` is captured as both an ID and `S` + `000030`. There is no additional Senate bill established by that slot. |
| Bill reference crossing witness/date slots | 7 | In `...-Wstate-_S-20160511.pdf`, A combines the witness's final `S` with the meeting date into a Senate-bill candidate. |
| Revision inside a person ID | 250 | `U000031`/`V000081` also become revision 31/81. B keeps them in the person-ID slot. |
| Bioguide-shaped terminal revision | 7 | `-U849615` is also captured as a Bioguide ID; B keeps it as a revision. |
| Eight-digit identifier also emitted as date-shaped token | 1,017 | 949 publication IDs, 64 supporting-document IDs, three amendment IDs, one bill number. Every extra date token has **zero valid calendar candidates**. |
| Six-digit date-shaped token inside Bioguide-shaped text | 16,810 | Numeric portions such as `000032` are also returned as `short_date_token`. A explicitly does not assign a date/century to these tokens. |

For example, `BILLS-112-HR3116-S000030-Amdt-1AAA.pdf` yields both HR 3116
and an extra S 30 candidate internally. House yields HR 3116,
`sponsorBioguideId=S000030`, and `amendmentId=1AAA`.

`CHRG-108shrg39104100.pdf` yields both `publication_number=39104100` and
`date_token=39104100` internally, with an empty calendar-candidate list. House
exposes only `publicationNumber="39104100"` for that token. The internal parser
does not assert that the invalid date is real, but consumers must inspect the
qualification instead of treating every named capture as usable metadata.

The earlier one-way check understated this problem: it found only 737 extra
bill-number/type cases because it inspected those fields only when B also had
bill fields. The bidirectional pass also catches false bill candidates in
witness/member records. Likewise, only four of the 250 person-ID/revision
collisions have a genuine revision field in B to compare against.

## House also overstates one classification

**1,051** filenames receive `kind=conference-numbered` from the generic
`CRPT-{congress}hrpt{number}` layout. Internal A calls this `published-report`
and preserves `publication_code=hrpt`. For example, `CRPT-112hrpt466.pdf`
becomes a conference report in B without a conference-specific filename token.

GovInfo documents this layout as a House report and exposes conference status
as separate searchable metadata. The kind is therefore too specific to infer
from the filename alone. **1,051 is the affected classification count, not a
claim that all 1,051 are incorrectly classified.** No census of report contents
was performed. Sources: [GovInfo CRPT help](https://www.govinfo.gov/help/crpt),
[H. Rept. 112-466 details](https://www.govinfo.gov/app/details/CRPT-112hrpt466).

## Where House produces no record

| Population | Filenames | Internal output |
| --- | ---: | --- |
| PDF/XML accepted by House | 202,063 | Outer layout recognized for all |
| PDF/XML rejected by House, internal outer layout recognized | 17,466 | Structured fields plus any unresolved payload |
| PDF/XML rejected by House, internal partial extraction only | 14,250 | Some tokens/candidates; not a complete naming record |
| PDF/XML without either of those internal recognition levels | 6,844 | Raw filename/extension retained |
| Other document extensions rejected by House | 35,053 | 34,783 outer layouts; 114 partial extractions; 156 raw-only |
| Extensionless routes/basenames | 57,664 | Kept separate from document filenames |
| Other extensions | 28 | Kept separate |
| **All inputs** | **333,368** | |

Of the 17,466 PDF/XML outer layouts found only by A, 15,618 are BILLS names.
Important rejected-name patterns include:

| Internal pattern | PDF/XML names rejected by House | Example and extracted information |
| --- | ---: | --- |
| Sponsored amendment | 8,030 | `BILLS-112-CommitteePrint-D000096-Amdt-10.pdf`: subject, sponsor-shaped ID, amendment number; B requires a numbered measure |
| Legislative text | 4,422 | `BILLS-113-HR2879ih.pdf`: Congress, HR 2879, IH; B rejects this alternate separator layout |
| Descriptive draft | 1,743 | Retains local draft subjects and associated tokens |
| Appropriations layout | 344 | Additional AP/FY/routing/subject variants |
| Published report | 170 | `CRPT-112hrpt592-pt1.pdf`: report identity and part |
| Committee-routed print | 143 | `CPRT-113-HPRT-RU00-HR1105.pdf`: Congress, print/routing codes, HR 1105 |
| Vote with a complex identifier | 62 | `CRPT-114-JU00-Vote1-10-20160525.pdf`: committee, literal vote range, date |

Counts in this last table describe distinct filenames per rule and may overlap.
A recognized outer layout is not proof of complete metadata extraction. Some B
rejections are appropriate validation failures, such as a missing person ID.

## Recommendation and reproducibility

Use House's typed roles as the starting point for supported layouts, after
making the numbered-report kind neutral. Bring over the internal parser's
useful detail: appropriations routing/year/subject, publication suffix structure,
and Bioguide-shaped witness identifiers. Retain internal extraction for the
remaining filenames, but prevent search rules from reinterpreting already
assigned identifier slots. Do not merge every candidate into the typed record.

This is a recommendation; no implementation or adoption occurred in this turn.
Both parsers retain original input, so the structured-field differences above
are not losses of the literal filename itself. Neither parser currently turns
every witness token into a verified person, nor validates identifiers against
external records. The corpus was previously used to develop rules and is not
an unseen accuracy benchmark.

Evidence under `.cache/filename-engine-comparison-20260929/`:

- `implemented-final/paired-outputs.jsonl.gz`: complete native A/B results for
  every input, including field spans and comparison checks.
- `metadata-final/patterns.parquet`: one row per input with diagnostic patterns.
- `metadata-final/summary.json`: per-field/per-kind inventories, counts and hashes.
- `metadata-final/examples.json`: complete fields for representative differences.
- `metadata/misses.json`: all 114 initial scalar alignment exceptions.
- `metadata/extras.json`: all additional-value cases from that alignment.
- `metadata/manual-edge-examples.json`: direct reviews of rare overlapping tokens.

Reproduce the bidirectional pass, using a fresh output directory:

```sh
.venv/bin/python tests/compare_filename_metadata.py \
  .cache/filename-engine-comparison-20260929/implemented-final \
  .cache/filename-engine-comparison-20260929/metadata-replay
```

The script checks current sources against the frozen run, checks input hashes
before/after, and asserts that all 333,368 names and 202,063 acceptances were
processed. Identical overlapping A field spans are deduplicated. Manual review
covered all 114 scalar exceptions, all 64 extra meeting-date candidates, rare
revision/member-ID collisions, and representative examples of the larger groups.
The mechanically inventoried population is larger than the manually reviewed
sample. No document download or content-wide accuracy evaluation was performed.
