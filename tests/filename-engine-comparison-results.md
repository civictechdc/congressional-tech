# Filename parser comparison — 2026-09-29

This is the pre-implementation baseline. See the
[implemented fixes and final regression results](house-naming-implementation.md)
for current coverage (83.97% of recovered PDF/XML names).

**Decision: keep `congress_api.filenames.parse_filename` as the corpus extractor.**
`house_naming.Engine.parse` 3.0.0 provides validated records for its supported
conventions, but cannot replace the extractor across the observed corpus. This
experiment changed neither production parser.

Follow-up: the [complete rejection inventory](house-naming-rejections.md)
accounts for every rejection and tests case, separator, and numeric-padding
differences, with a complete per-name Parquet inventory and grouped examples.

## Population and recovery

The untracked `output/` directory disappeared while the comparison was being
prepared. The user confirmed that someone else appears to have deleted it.
We rebuilt the filename inventory from 14 retained local document inventories,
association files, and download receipt journals. No documents were downloaded.

The rebuilt input contains **333,368 distinct literal names and URL basenames**:

| Input group | Names |
| --- | ---: |
| PDF/XML filenames | 240,623 |
| Other recognized document extensions, mostly HTML | 35,053 |
| URL basenames without an extension | 57,664 |
| Other extensions | 28 |

The first two groups total **275,676 document filenames**. The deleted inventory
had 275,489 aggregated rows containing 275,654 distinct spellings. The rebuilt
document population is 22 larger; proximity in count does not establish set
equivalence. These results cover every recovered name, not a proven exact
restoration of the deleted snapshot. Counts describe names, not unique document
contents or download successes.

Both primary arms received identical literal strings. We did not repair case,
whitespace, spellings, dates, or extensions. URL basenames were percent-decoded
once during inventory recovery. Source paths, hashes, origins and examples are
retained in the recovery artifacts.

## Coverage

The parsers answer different questions. An extractor layout match identifies
the outer filename structure and can preserve opaque text. A House-engine
acceptance requires a complete supported convention, its field validation, and
exact rendering back to the input. These are **coverage measurements, not
accuracy rates**.

| Measurement | `filenames.py` | `house-naming` |
| --- | ---: | ---: |
| Document filenames: outer layout / accepted convention | 254,312 / 275,676 (92.25%) | 65,181 / 275,676 (23.64%) |
| PDF/XML only: outer layout / accepted convention | 219,529 / 240,623 (91.23%) | 65,181 / 240,623 (27.09%) |
| Document filenames with fields beyond extension and opaque text | 268,676 | 65,181 accepted records |
| Partial extraction without an outer layout, document filenames | 14,364 | No partial-extraction API |
| Whole names recognized only by this arm, document filenames | 189,131 | 0 |

Neither arm recognized a complete layout/convention for 21,364 document
filenames. Every House-engine acceptance was within the extractor's layout
coverage. The House engine accepted 17 distinct record kinds on this population.

Document-extension counts by printed filename family:

| Family | Names | Extractor outer layout | House accepted | Additional case-only diagnostic successes |
| --- | ---: | ---: | ---: | ---: |
| HHRG | 127,094 | 127,094 | 50,866 | 42,180 |
| CHRG | 69,406 | 69,406 | 0 | 0 |
| BILLS | 32,216 | 32,216 | 12,095 | 4,501 |
| CRPT | 9,757 | 9,742 | 1,058 | 6 |
| HMKP | 9,026 | 9,026 | 769 | 0 |
| HMTG | 5,175 | 5,175 | 349 | 0 |
| HRPT | 213 | 213 | 44 | 1 |
| CPRT | 179 | 179 | 0 | 0 |
| AMNT | 4 | 4 | 0 | 0 |
| Other | 22,606 | 1,257 | 0 | 0 |

The engine models House naming conventions, so its lack of GPO and other
families is a scope limitation when considering it as a corpus-wide replacement.

## What explains the differences

### Lettercase accounts for 46,688 rejected PDF/XML filenames

A separate post-run diagnostic used the House engine's own grammar to build
case-adjusted records. For all 46,688 candidates, the engine validated and
rendered a filename differing from the original only in lettercase, then accepted
that rendered name. Those results do not change the primary acceptance count.

Examples:

- `HHRG-113-AG00-Wstate-ColbyJ-20130314.pdf` fails strict parsing because the
  convention uses `WState`. The diagnostic includes 35,594 witness-statement
  filenames, whereas only 2 match that convention literally in the primary run.
- `BILLS-112-HR3116-C001063-Amdt-1DD.PDF` fails because of the uppercase extension.

Case tolerance alone would bring demonstrated House acceptance to 111,869 names:
40.58% of document filenames, or 46.49% of PDF/XML filenames. This remains far
below the extractor's layout coverage. This was a diagnostic, not an implemented
case-tolerant parser.

### Entire supported shapes are absent from the House engine

- `CHRG-106hhrg53880.pdf`: the extractor identifies Congress 106, `hhrg`, and
  publication number 53880. The House engine reports `no-matching-convention`.
- `HMKP-112-HM00-20110622-SD001.pdf`: the extractor identifies Congress 112,
  committee HM00, date 20110622, document token SD, and document number 001.
  The House engine reports `no-matching-convention`.
- `00 052621 NIH Testimony1.pdf`: neither recognizes a complete layout. The
  extractor preserves the name and records `052621` as an ambiguous six-digit
  token. The House engine rejects whitespace as `unsafe-or-empty-filename`.

### Useful named fields differ in 109 accepted records

For **65,072 of the 65,181** accepted House records, every compared field value
was also present among extractor fields. All compared core identifiers, dates,
and stages were present. The remaining cases fall into three groups; every
reported difference was inspected, with full native outputs reviewed for
representative records and all three report-part examples:

| Cases | Difference | Practical meaning |
| --- | --- | --- |
| 90 | House `description` combines appropriations routing and subject; the extractor separates them. | Representation difference; preserve the extractor's more detailed fields. |
| 16 | House exposes a preintroduced-bill `description`; the extractor retains it within `suffix`. | Useful opportunity to expose a named description without losing the original suffix. |
| 3 | House exposes a conference-report `part`; the extractor retains it within `payload`. | Useful opportunity to expose the part token separately. |

Raw examples:

- `BILLS-113HR-FC-AP-FY2014-AP00-Agriculture.pdf`: House description is
  `AP-FY2014-AP00-Agriculture`. The extractor separately captures AP, FY2014,
  AP00, and `descriptor=Agriculture`. The House engine's own decision text says
  its broad description branch does not validate that internal structure.
- `BILLS-113hjres-PIH-FOOD.pdf`: House `description=FOOD`; extractor
  `suffix=-FOOD`, alongside `measure_token=hjres` and `version_token=PIH`.
- `CRPT-114hrpt-HR22-NOCOVSIG.xml`: House `part=NOCOVSIG`; extractor retains
  `payload=HR22-NOCOVSIG` and separately identifies HR22. The other two part
  tokens are `JES` and `Sig`. The comparison left `part` explicitly unmapped;
  raw review confirms these are not currently named part fields in the extractor.

Agreement means scalar value presence, not that field relationships or document
contents were verified. The extractor sometimes records additional references
or candidate tokens. For example, `C001063` also produces a `short_date_token`
of `001063`; the rule explicitly says it infers no date or century. Consumers
must preserve that distinction rather than treating every token as a fact.

## Mechanical checks and performance

All **333,368** recovered names were processed. Neither parser raised an
exception. Input and parser hashes stayed unchanged during the primary run.

- Extractor: all names reconstruct exactly; 2,696,850 field spans point back
  to their original text; no competing structural layouts were found.
- House engine: all 65,181 accepted records render exactly to their input;
  no ambiguous acceptances were found.
- No document-extension name lacked a child parse inside a recognized BILLS
  or committee-file wrapper. Twelve such cases remain among other extensions
  and extensionless routes. A child parse may still contain opaque text.

One warm-process pass alternated which parser ran first. Parser-call time alone
was **18.61 seconds** for the extractor and **3.82 seconds** for the House engine;
the complete harness took 43.32 seconds. Median calls were 0.0614 ms and
0.0039 ms, respectively; p95 calls were 0.0830 ms and 0.0434 ms. The House engine
rejects most inputs early, so these times do not measure equivalent work.

## Recommended next step

Keep one corpus-facing extractor and reuse `house-naming` for shared vocabulary
and supported structured conventions. Before removing overlapping extractor
rules, bring over the useful description and report-part fields, preserve literal
spelling, and verify coverage again. If strict House conformance is useful to a
consumer, expose it separately from successful extraction.

The replacement criterion failed: the House engine does not retain the existing
coverage. No production changes, commits, or pushes were made for this experiment.
This corpus already informed the extractor's rules, the extractor already uses
the House package's vocabulary, and no document contents were checked. Neither
independent semantic accuracy nor performance on unseen names is established.

## Reproduction and retained evidence

From the repository root:

```sh
.venv/bin/python tests/compare_filename_engines.py \
  .cache/filename-engine-comparison-20260929/new-run \
  --inventory .cache/filename-engine-comparison-20260929/inventory.parquet
```

Use a new output directory. The original run's `source/` directory contains
frozen parser, catalog, harness, recovery-script and pre-run-note copies. The
working experiment note subsequently gained a clearly labeled diagnostic section.

Evidence under `.cache/filename-engine-comparison-20260929/`:

| File | Contents |
| --- | --- |
| `inventory.parquet` | Every recovered literal input with provenance |
| `inventory-recovery.json` | Fourteen source inputs, hashes, recovery counts and limits |
| `rebuild_inventory.py` | Local inventory reconstruction |
| `run/summary.json` | Coverage, field comparisons, timing, environment and hashes |
| `run/comparison.parquet` | Per-name results for both primary arms |
| `run/paired-outputs.jsonl.gz` | Complete native outputs and comparisons for all names |
| `run/raw-review-samples.json` | Full native outputs for the ten manually reviewed examples |
| `run/field-differences.json` | All 109 records with field differences |
| `run/case-diagnostic.parquet` | All 46,688 case-only diagnostic candidates and rendered names |
| `run/diagnostics.json` | Diagnostic counts |
| `inspect_results.py` | Case diagnostic and raw-review extraction script |

The rebuilt inventory and native outputs are local, ignored cache artifacts;
they are not committed backups of the deleted `output/` directory.
