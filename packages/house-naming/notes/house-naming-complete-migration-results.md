# Filename ownership migration and category review

The filename reader, Pydantic result models, bill vocabulary, corpus command and
filename documentation now belong to `packages/house-naming`. Active application
and test imports use that package. The old `congress_api` filename modules are
removed. Raw legislator ingestion and service-date scoping remain with the
legislator source model; the naming package accepts an optional Congress-keyed
surname mapping and has no application dependency.

`Engine.extract` remains the single literal reader. The typed interface adapts
its results. The corpus command now uses the same residual-text algorithm as
the engine's corpus helpers. The base package requires neither Pydantic nor
PyArrow; install the `typed` or `corpus` extra for those interfaces.

## Verification

| Check | Result |
| --- | --- |
| Package, filename and comparison tests | 2,157 passed |
| Source-model tests | 15 passed |
| Full extraction comparison with the accepted GovInfo-publications baseline | All 333,368 results identical |
| Typed adapter compared with `Engine.extract` | All 333,368 results identical after field-name mapping |
| Character reconstruction and field spans | 333,368 filenames; 2,575,150 field spans checked |
| Corpus rule collisions | Zero; mechanical gate passed |
| Saved corpus artifacts | 12 unchanged; coverage differs only in implementation hashes |
| Residual-report correction | 1,948 field reports across 1,064 filenames now recognize already captured amendment/document identifiers as covered text |
| Installed wheel | All 20 package files match source; engine, typed API and both commands work with `congress_api` blocked |
| Base engine dependencies | Works with Pydantic and PyArrow blocked |
| Catalog generation and ECMAScript checks | Three generated artifacts verified; 100 regexes compile; 54 positive and 54 newline-rejection checks pass |
| Active imports of removed modules | None; historical frozen-comparator loading is retained |

The first trial caught a saved-output difference: synthesized residual fields
lacked their empty metadata keys. The typed adapter now supplies the established
shape, with a regression test. That trial remains saved. The previously reviewed
five native-parser suffix differences remain unchanged; the current reader
captures their more specific sponsor and amendment fields.

Evidence is retained under `.cache/filename-engine-comparison-20260929/`:

- `complete-migration-final/validation-manifest.json`: accepted checks and source hashes.
- `complete-migration-final/iteration-summary.json`: zero extraction changes.
- `complete-migration-corpus-final/coverage.json`: full corpus checks.
- `complete-migration-artifact-comparison.json`: every saved artifact compared;
  each residual correction checked against exact source-character positions.
- `installed-smoke.json` and `wheel-source-equality.json`: installed-package checks.

These checks establish migration fidelity on the retained development corpus.
They do not establish complete semantic interpretation of every filename.
Changes are local and uncommitted.

## All output documentation reviewed

Read all **11 Markdown files** recursively under `output/`, including the full
original and superseded plans and results:

- `filename-clustering/README.md`
- `filename-clustering/RESTORED.md`
- `filename-clustering/segmentation/README.md`
- `filename-clustering/experiment-20260929/plan.md`
- `filename-clustering/experiment-20260929/README.md`
- `filename-clustering/experiment-20260929/raw-review.md`
- `filename-clustering/experiment-20260929/content-check-plan.md`
- `filename-clustering/experiment-20260929/content-check/README.md`
- `filename-clustering/experiment-20260929/attempt-1/plan.md`
- `filename-clustering/experiment-20260929/attempt-1/README.md`
- `filename-clustering/experiment-20260929/attempt-1/raw-review.md`

The validation manifest records their paths, hashes and line counts. The
restoration note explains how the deleted output was recovered. The corrected
experiment supersedes the first attempt's handling of conflicting parent
committees; its adaptive result is 84.39%, rather than the older 84.36%.

## What the categories add

The original analysis interpreted 56 automatic clusters as 21 candidate
families. Filename-hint rules supplied the family counts. The committee-specific
experiment compared methods against **11 broader source categories**, merging
some of those distinctions. It did not establish a second, finer taxonomy.

The 21-family list provides a useful review checklist:

| Group | Distinctions to preserve |
| --- | --- |
| Hearing publications | Published hearing records; hearing/markup transcripts |
| People and testimony | Witness statements; member/opening statements; biographies; disclosures; witness lists; nominee/advance-policy questionnaires |
| Legislative work | Bills/resolutions/text; amendments/substitutes; votes; committee/conference reports; committee prints |
| Supporting material | Exhibits/support documents; correspondence/support letters; questions/responses for the record |
| Meeting and document administration | Rosters; cover pages; tables of contents; notices/agendas; summaries/fact sheets |

The current reader retains a relevant marker or wording for the saved example
from 19 of the 21 families. Some markers such as `CPg`, `QFR`, `MbrRoster` and
`Transcript` remain literal tokens without display labels. This sample check
does not establish category-wide accuracy. Five further examples each from the
notice and summary families confirm that generic notice/summary wording remains
unstructured. No new classifier or taxonomy was installed.

The committee-specific review adds concrete findings beyond that first list:

| Finding | Current behavior and next useful action |
| --- | --- |
| Rules Committee prints | `BILLS-116HR5-RCP116-13.pdf` already yields `RCP`, Congress 116 and print 13. Preserve this subtype when a consumer groups legislative documents. |
| Opaque filenames with explicit companion formats | `DF_004_xml.pdf` cannot identify a print from its own text. Saved XML explicitly links it with `CPRT-113-HPRT-RU00-HR2804.xml` and identifies Rules Committee Print 113-38. Use that source association in the application; do not invent a global `DF` meaning. |
| Committee-local abbreviations | `tt_bates.pdf` has an explicit native Truth in Testimony type. `BILLS-119HR8800ih-ISO.pdf` retains `ISO`, whose subcommittee meaning comes from the source description. Review recurring local conventions with their committee/Congress context before assigning meanings globally. |
| Notices and announcements | `05-13-20_sbc_forum_announcement.pdf` retains its words and date but lacks an announcement marker. Its XML says `HT` while its description says Forum Announcement. Add literal wording recognition; preserve the conflicting source claims. |
| Summaries and explanatory statements | Generic summary wording remains unstructured. The segmentation audit also found 27 native descriptions containing explanatory statement. Descriptions are useful additional evidence; these counts are not verified contents. |
| Manager's amendments | `BILLS-1197567pih-ManagersAmendment.pdf` retains `ManagersAmendment` in its suffix without identifying the phrase separately. This is another concrete wording gap. |
| Transcript errata | `HMKP-119-GO00-20260318-CPg.pdf` yields the printed `CPg` marker, while the source description says Transcript Errata. That distinction requires the description or content, not a filename-only rule. |
| Misleading outer prefixes | The current reader extracts `Vote` from `CRPT-118-HM00-Vote015-20230426.pdf` and `Amdt` from the reviewed `BILLS` amendment. An outer collection prefix does not replace these more specific fields. |
| Mixed or mislabeled contents | The reviewed `Wstate-…-SD002` file contains disclosure and biography pages; the reader retains both witness and supporting-document markers. Other PDFs demonstrate that `Bio` and `BILLS` names can misdescribe content. Keep filename observations, native types, descriptions and content assessments separate. |

The corrected experiment supports using committee context to discover local
patterns: source-label agreement rose from 77.84% globally to 84.39% with
adaptive subcommittee/Congress grouping. Its content spot-check found two
disagreements favoring filenames, three favoring source metadata, and one mixed
document. These findings support targeted rule review and preservation of source
context; they do not justify automatic replacement of native types.

Current-reader probes are saved in `category-check.json` and
`context-category-probes.json` under the same cache directory. The former checks
21 representative names plus ten notice/summary examples; the latter checks 15
specific names from the segmentation and content reviews. The saved raw XML/JSON
examples and source-label mapping were also read directly. No clustering was
rerun for this review.
