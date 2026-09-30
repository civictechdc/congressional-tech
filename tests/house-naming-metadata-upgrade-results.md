# House naming metadata changes — verified 2026-09-29

Implemented all seven requested changes in `packages/house-naming`. On the same
333,368 recovered filenames/URL basenames, accepted names increased from
**202,063 to 246,213**, a gain of **44,150**. All previous acceptances and scalar
metadata survived, allowing the explicitly approved report-kind correction.

## Behavior now implemented

1. **Report classification:** retain the guide's `conference-numbered` definition,
   examples, source references and rendering convention. Parse arbitrary numbered
   reports as `published-report`, with `documentType: report` and the printed
   `publicationType`. Each match retains `matched_conventions`, so the guide's
   conference convention remains attributable. No conference status is inferred.
2. **Appropriations:** support two/four-digit fiscal years and the observed extra
   separator after Congress. Extract the year, committee routing, literal subject
   and descriptive remainder within the retained `description`. Detailed guide
   conventions parse into this shared record. Explicit `suppl`/`CR` forms retain
   their type and sequence; a missing year slot stays missing.
3. **Publication suffixes:** hearings, reports and prints retain `publicationSuffix`
   and expose printed part/volume/addendum/errata values. Roman identifiers and
   leading zeros survive. Empty means an unnumbered marker is present; absence
   means no unique marker was extracted. Unknown/repeated components stay raw.
4. **Amendment subjects:** support literal targets such as `CommitteePrint`,
   `OversightPlan`, placeholders and bare local numbers. Preserve sponsor IDs,
   local amendment identifiers, en-bloc groups and revisions separately. A numeric
   subject does not establish a bill type. Letter/underscore identifiers in known
   amendment slots are retained.
5. **Observed layouts:** support alternate bill separators, version occurrences,
   parenthetical annotations, routed committee prints and complex vote IDs.
   A whole print subject such as `HR1105` also yields bill type/number; a title
   containing a similar substring does not. Vote ranges remain literal strings.
6. **HTML publications:** GPO hearing/report/print patterns accept `.htm`/`.html`.
   Other House naming conventions retain their existing PDF/XML bounds. The
   portable filename schemas use each pattern's declared extension values.
7. **Witness identifiers:** whole-slot Bioguide syntax adds
   `witnessIdType: bioguide` without modifying the witness ID or verifying identity.

Raw `input`, description and suffix values remain available. Derived fields are
included in the generated record schemas and validated by the runtime. Rendering
rejects supplied derived values that disagree with their retained source field.
No global substring sweep was introduced.

## Measured additional coverage

| Newly accepted family | Filenames |
| --- | ---: |
| HTML hearing publications | 34,692 |
| Amendments with literal subjects | 7,469 |
| Additional local IDs on numbered-measure amendments | 520 |
| Bill layouts/version suffixes | 942 |
| Appropriations layouts | 119 |
| Committee-routed prints | 141 |
| Published prints | 36 |
| Reports with parts or other supported report types | 169 |
| Complex vote identifiers | 62 |
| **Total** | **44,150** |

PDF/XML acceptance is now **211,521 / 240,623 (87.91%)**. Across all recognized
document extensions it is **246,213 / 275,676 (89.31%)**. Extensionless URL routes
are kept separate. Counts concern literal filenames, not unique document contents.

The accepted corpus now contains 209 structured appropriations descriptions
(207 explicit fiscal-year slots, 164 committee-routing slots), 2,480 classified
witness identifiers, four version-occurrence values and one parenthetical bill
annotation. New report/print kinds also expose retained publication metadata.

## Verification

- All **333,368** input names processed; **246,213** successful canonical
  render/reparse checks; **zero parser exceptions or ambiguous results** in this corpus.
- All **202,063** prior accepted records retain their scalar values. The **1,051**
  `conference-numbered` results now have the neutral parsed kind, with the original
  convention retained in `matched_conventions`.
- All **333,368 internal extractor outputs are unchanged**.
- Source text, definitions, original examples, committee reference data and
  source references remain unchanged. Every catalog `observed_examples` entry
  was checked against the retained inventory.
- All **888** package and repository filename tests pass; see the retained final test log.
  Tests cover exact metadata, aliases, conflicting supplied values, malformed
  dates and identifier/date/revision collisions. All 47 kinds have regression
  fixtures; constructed cases remain distinct from observed examples.
- Generated artifacts pass deterministic regeneration checks. Node compiles
  all 73 regexes and passes 45 positive / 45 trailing-newline checks.
- Direct review of saved outputs covered every new family and each combination
  of derived field names, including missing fiscal-year slots and opaque print
  subjects. Full inputs and parser outputs remain retained; manual review is a
  sample rather than document-content certification.

Existing rendering conventions remain callable. Parsed-kind migrations for
detailed appropriations and committee rules are also declared through `parse_as`;
those conventions share metadata records while remaining in `matched_conventions`.
No client needs a second filename parser to obtain the new fields. The existing
internal extractor remains available for other unsupported source spellings.

## Remaining bounds and evidence

Some names still lack a bill type or other required structure. For example,
`BILLS-1131129ih.pdf` does not state HR/S/etc. Forty-one internally recognized
sponsored-amendment layouts remain rejected, mainly because they have missing or
punctuation-only identifiers, plus unsupported compound groups. No type or ID is
invented to increase the match count. Filename parsing does not verify contents,
member identity, actual legislative status or download availability.

Final artifacts are under
`.cache/filename-engine-comparison-20260929/metadata-upgraded-final/`:

- `summary.json`: coverage, runtime, source hashes and mechanical checks.
- `paired-outputs.jsonl.gz`: complete native A/B outputs for every filename.
- `comparison.parquet`: searchable per-name acceptance and rule inventory.
- `upgrade-regression.json`: preserved records, intentional kind changes and gains.
- `upgrade-ambiguities.json`: empty in this corpus.
- `metadata-samples.json`, `derived-field-counts.json`: review examples and field counts.

Tests: `.cache/filename-engine-comparison-20260929/metadata-upgrade-work/integration-tests-final.log`.
Full comparison completed in about 73 seconds. No downloads, commits or pushes
were performed for this implementation.
