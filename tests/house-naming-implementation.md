# House naming coverage improvements — 2026-09-29

Implemented the four priority fixes and the two small follow-ups. On the same
recovered corpus, PDF/XML acceptance increased from **65,181 / 240,623 (27.09%)**
to **202,063 / 240,623 (83.97%)**. The increase is **136,882 filenames**.

All 65,181 previously accepted names still parse and retain every previous record
field. All 333,368 native `filenames.py` outputs are unchanged. No parser
exceptions or ambiguous matches occurred in this corpus. These are filename
coverage and regression results, not verification of document contents.

## Changes and measured gains

| Change | Newly accepted filenames |
| --- | ---: |
| Case variations in fixed tokens, codes, extensions, and revision markers | 46,688 |
| Date-first numbered committee documents: SD and QFR | 39,598 |
| Date-first MbrRoster, CPg, and TOC documents | 1,566 |
| GPO CHRG publication identifiers, including suffixes | 34,714 |
| Committee votes without the extra literal HMTG segment | 8,441 |
| Committee transcript filenames | 2,912 |
| Witness biographies/statements/support/disclosures under HMTG or HMKP | 2,912 |
| Witness lists under HMTG or HMKP | 51 |
| **Total gain** | **136,882** |

The gains are disjoint: a filename counted under case variations is not counted
again under a document family. The witness-list layout uses the same collection
parameter as the other witness documents.

The package now has 42 kinds, up from 38. Four additional kinds handle numbered
committee documents, unnumbered committee documents, committee transcripts, and
published hearings. The existing vote kind accepts an explicit second layout;
existing witness kinds preserve the collection through `meetingType`.

## Output behavior

`parse()` preserves the exact filename in `input`. Each successful match includes
its typed `record` and `canonical_filename`. Fixed tokens and code fields accept
ASCII case variations; free text retains its spelling. A canonical filename may
differ in case, or use the guide's vote layout with the literal HMTG segment.
Every one of the 202,063 accepted records successfully renders and re-parses.
Of those, 145,272 render to the identical original spelling.

For example, `HHRG-112-HM00-20110310-SD001.pdf` produces:

```json
{
  "kind": "committee-document-numbered",
  "meetingType": "HHRG",
  "congress": 112,
  "committeeCode": "HM00",
  "meetingDate": "20110310",
  "documentType": "SD",
  "documentNumber": "001",
  "extension": "pdf"
}
```

`CHRG-118shrg049104057.pdf` preserves the leading-zero identifier:

```json
{
  "kind": "published-hearing",
  "congress": 118,
  "publicationType": "shrg",
  "publicationNumber": "049104057",
  "publicationSuffix": "",
  "extension": "pdf"
}
```

Part, volume, addendum and errata suffixes remain literal `publicationSuffix`
values such as `-pt1-err`, `-volII`, and `-add1`. The parser does not guess
equivalent numeric meanings for those suffixes.

Old witness input records without a collection still render as HHRG; validated
and parsed records expose the default as `meetingType: "HHRG"`. Inputs naming
HMTG or HMKP retain that prefix. `validate()` fills declared defaults without
mutating the caller's record. `render()` still requires canonical code values.

The catalog lists corpus-derived `observed_examples` separately from guide
examples. Source sections, wording, code definitions, committee reference data,
footnotes, and all 160 published example occurrences are unchanged.

## Verification and remaining limits

- **813 tests pass:** package runtime tests and all repository filename tests,
  including exact field expectations for real observed filenames and negative
  controls for malformed dates, missing metadata, and unsupported repairs.
- Generated catalog and schema checks pass. The Node portability check compiles
  58 Unicode regexes and passes 40 filename/40 trailing-newline checks.
- All **333,368** recovered input names ran through both parsers, with complete
  native outputs retained. Input and source hashes stayed fixed during the run.
- Every prior acceptance and field was checked against the saved baseline;
  the unchanged extractor was compared by complete output equality.
- Direct review covered representative outputs from each added family, the GPO
  leading-zero identifier, and examples that remain rejected.

The audit's 8,503-vote estimate included 62 shapes beyond simple vote IDs, such
as `Vote1-10`, `Vote10-hr865`, `VoteMotion`, and `VoteSummary`. These remain
unmatched; the implementation does not silently flatten ranges or treat extra
bill references as vote IDs. The final result is 11 below the earlier combined
projection: 62 vote variants remain, while the shared witness layout adds 51
witness-list names beyond the original estimate.

The remaining PDF/XML population contains 38,560 unaccepted names. Other document
extensions and extensionless URL routes remain outside the package's PDF/XML
filename scope. Across all 275,676 document-extension filenames, acceptance is
73.30%. Retaining the broader `filenames.py` extractor remains necessary.

The corpus was rebuilt after `output/` was deleted and contains 22 more document
spellings than that deleted snapshot. It is not claimed to be the identical
original population. No new downloads, commits, or pushes were made.

## Reproduction and evidence

```sh
.venv/bin/python -m pytest -q packages/house-naming/tests tests/test_filename*.py
.venv/bin/python packages/house-naming/tools/build.py --check
node packages/house-naming/tools/check_ecmascript.mjs
.venv/bin/python tests/compare_filename_engines.py \
  .cache/filename-engine-comparison-20260929/new-verification-run \
  --inventory .cache/filename-engine-comparison-20260929/inventory.parquet
```

The retained final run is
`.cache/filename-engine-comparison-20260929/implemented-final/`:

| File | Evidence |
| --- | --- |
| `summary.json` | Counts, input/code hashes, timing, and mechanical checks |
| `comparison.parquet` | Every input's results from both parsers |
| `paired-outputs.jsonl.gz` | Complete native outputs |
| `regression.json` | All prior acceptances/fields retained; extractor outputs and guide evidence unchanged |
| `reviewed-examples.json` | Exact raw outputs reviewed for representative cases |
| `source/` | Frozen source files and experiment note |

The sibling `check_implementation.py` reproduces the baseline-output comparison.
The earlier `run/` and `rejections/` directories remain the pre-implementation
evidence. An intermediate `implemented/` run documents the finding that led to
preserving GPO publication numbers as strings; `implemented-final/` supersedes it.
