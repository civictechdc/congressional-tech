# Filename metadata comparison after the House naming upgrade

The previous House metadata gaps are closed on the tested examples and full
accepted population. House provides cleaner field boundaries. The internal
extractor still provides useful detail inside some retained text and recognizes
more filename layouts. It also emits misleading overlapping candidates.

A = `congress_api.filenames.parse_filename`; B = `house_naming.Engine.parse`.
This analysis covers **333,368** recovered literal filenames/URL basenames.
All **24** recorded source/input hashes matched current files before and after
analysis, so the latest full native outputs were reused without downloading or
reparsing documents. No production parser changed during this comparison.

## Coverage and agreement

| Measure | Result |
| --- | ---: |
| Names accepted by House; also recognized by the internal extractor | 246,213 |
| Previously accepted House names retained | 202,063 |
| Newly accepted House names | 44,150 |
| PDF/XML names accepted by House | 211,521 / 240,623 (87.91%) |
| All document-extension names accepted by House | 246,213 / 275,676 (89.31%) |
| PDF/XML names rejected by House with an internal outer layout | 8,008 |
| PDF/XML names with internal partial extraction only | 14,250 |
| PDF/XML names without meaningful extraction by either | 6,844 |
| Other document extensions rejected by House | 361 |
| Extensionless basenames/routes, excluded from document coverage | 57,664 |
| Other extensions | 28 |

Recognition does not certify field accuracy. An internal outer layout may still
contain unresolved text; House acceptance means a typed naming record.

The revised alignment checked **1,446,352 House scalar fields**:
**1,445,728** matched an internal capture or equivalent explicit classification;
**229** were empty defaults; **282** were accounted for by combined/split text.
The remaining **113**, all newly accepted names, received a separate raw review.
Every difference is explained by field boundaries in the table below. No
unexplained House scalar contradiction remained under this alignment. This does
not establish the correctness of every role or every extra internal candidate.

All 202,063 previously accepted names aligned without those remaining exceptions.
The old field mapping would have incorrectly flagged new House fields as missing.
The original diagnostic statuses remain retained alongside their adjudication.

## Changes that now agree

- **Appropriations:** 209 accepted records, including 207 explicit routing-slot
  fiscal years and 164 committee codes. The original `description` remains.
- **Publication suffixes:** 443 structured values agree: 182 parts, 14 volumes,
  199 addenda and 48 errata. Values remain literal, including Roman numerals and
  empty values for unnumbered markers.
- **Witness identifiers:** all 2,480 House `witnessIdType: bioguide` classifications
  correspond to the internal identifier-shaped capture. Neither verifies identity.
- **Report classification:** the 1,051 former `conference-numbered` records now
  use the neutral `published-report` kind. The original guide convention remains
  in `matched_conventions`; conference status is not inferred from the generic name.
- **Version detail:** four stage occurrences and one annotation agree with A.
  Five combined House `versionSuffix` values correspond to separately captured
  occurrence/annotation text in A.

## Where House provides cleaner boundaries

These five groups account for all 113 initial alignment exceptions:

| Pattern | Names | Internal A | House B |
| --- | ---: | --- | --- |
| En-bloc amendment IDs | 40 | `EB8-Enbloc-8` combined amendment token | `amendmentId=EB8`, `enblocId=8` |
| Named amendment IDs with revisions | 19 | `CMT-ANS_02-U1` combined token | `amendmentId=CMT-ANS_02`, `revision=1` |
| Bill descriptions with revisions | 43 | `-CommitteePrint-U2` combined suffix | `versionSuffix=-CommitteePrint`, `revision=2` |
| Appropriation subjects with revisions | 2 | `Amdt-1-U1` descriptor | `subject=Amdt-1`, `revision=1` |
| Vote labels | 9 | `document_token=VoteRC`, `document_number=1`, or `VoteMotion` with empty number | `voteId=RC1`, or `voteId=Motion` |

These are differences in structured fields, not discarded filename bytes. All
113 native records and exact reconstruction checks are saved in
`adjudicated-113.json`. A often also supplies the revision/en-bloc field; the
problem is its overlapping combined capture. House also provides explicit
pre-introduction descriptions (18 names) and report-component parts (six names)
that A retains in larger text fields.

## Useful detail still structured only by the internal extractor

| Pattern | Names | Direct comparison | Practical meaning |
| --- | ---: | --- | --- |
| Rules Committee Print reference | 94 | `BILLS-116HR3401EAS-RCP116-21.pdf`: A has `print_congress=116`, `print_number=21`; B has `versionSuffix=-RCP116-21` | Clear candidate for additional scoped House fields. |
| Bill references within amendment subjects | 106 | `SConRes14ReconciliationDirectives`: A has SConRes 14; B retains the full `subject` | Includes 27 distinct subject strings, including padded numbers and local suffixes. Preserve the subject and qualify the extracted reference. |
| Bill references within committee-print subjects | 14 | `CPRT-113-HPRT-RU00-HR1900a.xml`: A has HR 1900; B has `subject=HR1900a` | Letter/local suffix meaning is not established. |
| Bill reference within vote ID | 6 | `CRPT-116-ED00-Vote10-hr865-20190226.pdf`: A has HR 865; B has `voteId=10-hr865` | Preserve the literal vote ID alongside any related-bill fields. |
| Fiscal-year text outside the routing slot | 17 | 14 `FY16BVE` amendment subjects; two additional `FY18` subject tokens; one `FY2018` in prose where the routing slot is empty | Useful descriptive metadata, but not evidence that an absent routing-slot year was supplied. |

House preserves all this text. These are missing structured fields, not loss of
raw input. The reverse inventory contains **164 names** with additional measure
candidates after excluding person-ID collisions, witness/date crossings and
repetitions of the already assigned main bill. The categories overlap: 106
amendment subjects, 38 amendment IDs, 14 print subjects, six vote IDs and one bill
suffix; one name contains both a subject and amendment-ID reference.

The 38 amendment-ID cases require care. For example:

```text
BILLS-118-HR7159-F000471-Amdt-HR7156.pdf
A: HR 7159 plus another measure-shaped reference HR 7156
B: measureType=HR, measureNumber=7159, amendmentId=HR7156
```

The second number must not silently replace the primary measure. Another case,
`BILLS-116-1010-J000292-Amdt-HR101-Johnson-JOHNOH_009_xml.pdf`, contains numeric
subject `1010` and `HR101` in the amendment ID. Filename evidence alone does not
resolve that discrepancy.

The additional bill-suffix case also demonstrates overcapture:
`BILLS-115HR5759ih-HR575921stCentAct.pdf` gives A a second candidate **HR 575921**.
The main slot says HR 5759; the suffix plausibly joins that number to “21st”. It
is unsafe to adopt every extra internal bill capture as a verified reference.

## Internal overlap problems remain

| Pattern | Same 202,063 old names | All 246,213 accepted names |
| --- | ---: | ---: |
| Bill-shaped reference inside a Bioguide-shaped ID | 1,428 | 2,051 |
| Revision-shaped token inside a person-ID slot | 250 | 353 |
| Bill reference crossing witness/date slots | 7 | 7 |
| Bioguide-shaped token inside a terminal revision | 7 | 7 |
| Extra eight-digit date-shaped identifier, with no valid calendar reading | 1,017 | 1,970 |
| Six-digit date-shaped token inside a Bioguide-shaped token | 16,810 | 24,799 |

The old-cohort counts are unchanged. Larger totals result from the expanded
accepted population, not changed internal behavior. Internal date fields include
qualification notes/candidate lists; they are not asserted valid dates.
For example, `S000030` also generates S 30, while House keeps the person-ID slot.
A further 1,347 names have broad amendment tails in addition to cleaner pieces
(649 en-bloc cases and 698 revision cases).

## What still fails House recognition

Of the 8,008 PDF/XML outer layouts only A recognizes, 6,568 are BILLS names.
Important internal rule groups include 3,480 legislative-text names, 1,743
descriptive drafts, 225 appropriation layouts, 168 report-file names and 41
sponsored-amendment layouts. Rule groups overlap and are not additive.

Examples include `BILLS-1131129ih.pdf` (no printed measure type),
`BILLS-113pih-BACPACAct.pdf` (descriptive draft), and
`BILLS-113-FC-AP-FY2014-AP00-TransHUD.pdf` (missing measure slot). A can retain
partial structure without inventing the absent field. Keep that capability.

The next useful House additions are scoped Rules Committee Print references and
carefully bounded references inside subjects/vote IDs. Keep raw text and explicit
field roles. Avoid merging all internal search captures into the typed record.
This report proposes those additions; it does not implement them.

## Evidence and reproduction

Base: `.cache/filename-engine-comparison-20260929/`.

- `metadata-upgraded-final/paired-outputs.jsonl.gz`: complete native A/B outputs.
- `metadata-upgraded-final/summary.json`: corpus, parser hashes and runtime checks.
- `metadata-head-to-head-current/summary.json`: scalar alignment and field inventory.
- `metadata-head-to-head-current/differences.jsonl.gz`: complete difference/reverse queue.
- `metadata-head-to-head-current/adjudicated-113.json`: every initial scalar exception.
- `metadata-head-to-head-current/reverse-useful-candidates.json`: remaining references.
- `metadata-head-to-head-current/overlap-by-cohort.json`: stable-cohort overlap counts.
- `metadata-head-to-head-current/review_differences.py`: literal adjudication/reverse audit.
- `metadata-head-to-head-current/review-hashes.json`: supplemental evidence hashes.

Run the revised alignment into a new directory:

```sh
.venv/bin/python tests/recompare_filename_metadata.py \
  .cache/filename-engine-comparison-20260929/metadata-upgraded-final \
  .cache/filename-engine-comparison-20260929/implemented-final \
  .cache/filename-engine-comparison-20260929/metadata-recomparison-replay
```

The supplementary overlap run uses `tests/compare_filename_metadata.py`; only
its span-collision flags are used here, not its obsolete scalar/missing-field
claims. The full automated population is larger than the manual sample: manual
review covered all 113 scalar exceptions, the distinct remaining subject shapes,
fiscal-year cases, and representative remaining references/collisions. No PDF
contents, external identities or unseen-corpus accuracy were certified. Counts
are literal names, not unique documents. Production sources remain unchanged;
comparison scripts and reports are local and uncommitted.
