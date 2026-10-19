# Literal filename extraction: implementation and comparison

`house-naming` now exposes `Engine.extract()` and the `house-naming extract`
command. They read source fields from real filenames, including filenames that
do not conform to a renderable naming convention. The package remains standalone;
it does not import the native `congress_api` parser.

The final run is `.cache/filename-engine-comparison-20260929/extraction-named-dates/`.
It compares the new extraction against the frozen native outputs in `drafts-final`
on the same **333,368 literal inputs**. These are development examples recovered
from local captures, including URL basenames; they are not an unseen accuracy test.

| Check | Result |
| --- | ---: |
| Inputs processed without an exception | 333,368 |
| Existing strict parsing outputs preserved exactly | 333,368 |
| Inputs reconstructed exactly from retained pieces | 333,368 |
| Observed field spans checked against source text | 2,532,475 |
| Inputs with a recognized outer layout | 300,733 |
| Inputs with explicit last-resort assumptions | 31,167 |
| Inputs with additional fields versus native extraction | 42,960 |
| Inputs retaining every native raw field signature | 301,764 |
| Changed meanings on shared coded fields | 0 |
| Tests passing | 1,100 |

There are source observations beyond an extension for **333,367** inputs. This
does not mean 333,367 filenames are fully understood. Some observations identify
only a literal label, an opaque ID, query-shaped text, or an assumed name. The
remaining `offered.zip` retains its extension and complete text; the user's ZIP
exclusion prevents treating its stem as a person name. Strict convention
acceptance remains **252,515**, unchanged by this work.

## Useful behavior moved into the package

The catalog contains 99 extraction rules. Specific source layouts run before
generic token searches and the user's final name/identifier fallbacks. The API
keeps original text, character offsets, candidate meanings and rejected matches.
It recognizes non-PDF extensions without inventing a file format or asserting
anything about file contents.

| Literal example | Extracted information or correction |
| --- | --- |
| `BILLS-116ANStoHR1988ih.pdf` | Congress 116, `ANS`, `to`, HR 1988 and `ih`; previously these remained in a broad description. |
| `BILLS-115SAHR3219HR3162HR2998HR3266-RCP115-30.pdf` | All four measure references and the Rules Committee Print's Congress and number. |
| `CHRG-106hhrg53880` | Congress, publication family and number without inventing a PDF extension. |
| `HHRG-113-HM08-Bio-BejtlichR-20130320.docx` | Committee, biography code and meaning, subject, date candidate and actual Word extension. |
| `HHRG-119-AS00-Wstate-S000522-20260101.pdf` | Witness-statement meaning and Bioguide-shaped ID; the ID does not become Senate bill 522 or a short date. |
| `BILLS-119ANSServices.pdf` | Full `Services` description; the possible `es` ending receives no asserted bill-version meaning. |
| `Hamilton Testimony Update 3-4-21.pdf` | Update wording and an ambiguous date; no invented revision number 3. |
| `Smith-February-29-2024.pdf` | Calendar-valid date candidate; 2024 does not also become a generic identifier. |
| `Smith-February-31-2024.pdf` | Original date components and an invalid-calendar note. |
| `sammypdf.pdf` / `tobias-tedtimony.pdf` | User-requested name assumptions with the discarded-looking suffix retained separately. |

## What the disagreements establish

The omission audit classifies every native field absent from accepted observations.
Reasons include invalid calendar candidates, a match crossing an already assigned
ID or date, the same literal retained under a more precise field name, and an
extension separated from an opaque payload. Rejected candidates keep their full
fields and source spans in `suppressed`; they are not silently deleted.

This classification explains the mechanical differences. It is not an independent
proof that every suppression or new interpretation is semantically correct.
Representative raw checks exposed and corrected lost code meanings, lost contained
references, dates crossing part/revision numbers, trailing dates classified as IDs,
and written-month dates whose years became generic identifiers. Earlier runs
remain available with their original results.

The fallback comparison invokes the real native `resolve_unmatched_filename`
helper for names without a new outer layout. That is a direct helper comparison,
not a claim that the previous production caller invoked that helper for every
one of those inputs. Changed fallback assumptions remain individually inspectable.

## Validation and retained evidence

The existing guide text, definitions, codes, examples, committee directory and
footnotes remain unchanged. Every strict result matches the saved baseline;
source hashes stayed stable during the final comparison. Generated JSON checks
pass. Node compiled 100 portable naming expressions, accepted 54 positive filename
cases and rejected their 54 trailing-newline variants. These portability checks
apply to naming schemas; extraction rules use Python regular expressions.

A standalone import check blocked every `congress_api` import while extracting
legislative, witness-document and named-date examples successfully.

Evidence in the final run:

- `summary.json` and `extractions.jsonl.gz`: counts, hashes and complete outputs.
- `differences.jsonl.gz`: every changed field signature and code comparison.
- `omission-audit.json` and `omission-audit.jsonl.gz`: every omitted native field,
  its reason, and checks of rejected-field source spans.
- `fallback-comparison.jsonl.gz`: changed last-resort interpretations.
- `reviewed-examples.json`: complete outputs for the examples reviewed directly.
- `validation-manifest.json` and `source/`: validation results, hashes and source snapshots.

## Remaining work

Some descriptive text and fallback names still contain unresolved internal
structure. Date candidates do not establish the meeting date, short years do not
establish a century, and a Bioguide-shaped token does not establish a person's
identity. Further semantic review must use retained raw examples and independent
source evidence where needed.

The native parser remains the comparison baseline and current consumer path.
This iteration adds the standalone extraction API; it does not replace existing
`congress_api` consumers. No changes were committed or pushed in this iteration.
