# Core retained-source workflow qualification

The core workflow has three independent results: acquisition retains bytes and
receipts; a rebuild derives filename rows and grouped documents; publication
selects one validated pair. A failed publication does not erase completed
acquisition. `raw-capture-summary.json` records `acquisition_status`,
`catalog_status`, and `planning_status` separately. The progress sidecar records
the last processing stage and process memory.

Intermediate source rows, source occurrences, recovery references, and document
groups use temporary SQLite tables. The rebuild writes Parquet in batches and
reuses a document group only when its inputs, membership, and interpretation
rules still match. Changes that join or split groups force recomputation.
Retained receipts remain the evidence from which these outputs can be rebuilt.

Publication writes two immutable files, validates their contents and shared
`catalog_id`, then changes `indexes/catalog.json` only if the previous selection
is still current. Readers select both files from that one manifest. Interrupted
or competing writers leave the previous selection readable. Standalone local
writers also preserve legacy root files while preparing the first generation.

If an acquisition worker fails, the collector stops submitting work, records
successful work already in flight, and saves progress before reporting failure.
The recovery tests check this behavior separately from index publication.

## Counting units

| Summary field | Unit and scope |
| --- | --- |
| `accounting.known_urls` | Distinct normalized URLs in download state, including pages, files, exclusions, and retryable failures |
| `accounting.urls_by_source_family` | URL membership counts by retained source family |
| `accounting.capture_tasks_submitted` | Fetch or retained-body replay tasks submitted this run |
| `accounting.capture_tasks_completed` | Tasks whose result was classified and recorded this run |
| `accounting.native_request_dispatches` | Commands assigned an ID before native worker execution, including fallback commands |
| `accounting.http_request_starts` | Unknown (`null`): wire starts are not instrumented |
| `accounting.usable_capture_results` | Completed results classified `saved`, including source pages with usable linked content |
| `accounting.unique_retained_body_keys` | Distinct nonempty body keys referenced by the saved capture index, including legacy entries without digests and error/provider bytes; not a storage-existence check |
| `accounting.url_outcomes` | Current URL outcomes, including challenges, missing responses, parse failures, exclusions, and saved sources |
| `accounting.filename_rows` | Derived filename/source rows; aliases and source occurrences can produce multiple rows |
| `accounting.grouped_documents` | Derived document groups, including metadata for files whose bytes have not been captured |

The legacy `attempted` field means submitted capture tasks. The legacy
`http_requests` field means native request dispatches. Neither field proves
completed HTTP requests. URL totals, bodies, filename rows, and document groups
measure different things and cannot be substituted for each other. A retained
body can hold a failure page; its presence does not establish a usable document.

## Pinned local benchmark

Prepare a read-only mirror and a reference pair from the same input snapshot.
The reference directory contains `document-filenames.parquet` and
`documents.parquet`. Run each candidate in a fresh Python process and a new
output directory:

```sh
PYTHONPATH=. .venv/bin/python .github/scripts/offline-python.py -m scripts.benchmark_core_rebuild \
  --mirror .cache/congressional-tech-raw \
  --reference .cache/core-workflows-20261004/baseline-indexes \
  --output .cache/core-workflows-20261004/candidate \
  --workers 2 --max-peak-gib 8
```

Optional `--seed PATH` values must match those used for the reference.
`--repair` forces reinterpretation rather than reusing interpretation caches;
record the same policy for comparable arms. Normal qualification leaves body
inspection disabled. All rebuild writes go into the output overlay. Network
connections are disabled by the launcher.

The report pins every mirror object actually read, including missing reads,
and every requested key listing. Repeated reads must return the same bytes.
It pins seeds, reference files, the output pair, and its selection manifest,
then checks observed inputs and outputs again after comparison. Unread document bodies are outside this metadata benchmark's input
inventory. It records elapsed
rebuild time, object reads and bytes by storage family, processing stages, and
process memory. Linux samples aggregate resident memory for the parent and its
worker children every 250 milliseconds. Sampling can miss shorter spikes and
sums shared pages conservatively. Other platforms leave the aggregate budget
unqualified. Stage memory includes a cumulative parent-process high-water mark,
not an isolated allocation count for that stage. Hashing consumed mirror bytes
runs inside the timed rebuild; its time is reported separately. Reference hashing,
post-run verification, and semantic comparison run outside that interval.
The parent-process peak can include input inventory preparation; the aggregate
Linux sample covers only the rebuild.
The report also pins source code hashes, revision, and relevant package versions.

Semantic qualification hashes each complete canonical JSON record and sorts
the fixed-size hashes in SQLite. It compares the resulting record sets,
including duplicate counts, and exact field schemas. It preserves IDs, aliases,
source occurrences, classification, failure fields, nulls, list order, and
record multiplicity. Top-level schema metadata, including generation ID and
input fingerprints, is excluded; field metadata remains part of comparison.
Equal row counts alone cannot pass qualification. Scratch storage grows with
the number of records rather than the size of their nested evidence.

If a completed rebuild's comparison fails, compare its retained output without
rebuilding:

```sh
PYTHONPATH=. .venv/bin/python .github/scripts/offline-python.py -m scripts.benchmark_core_rebuild \
  --compare-only --reference PATH_TO_REFERENCE_PAIR \
  --candidate-root PATH_TO_RUN/objects \
  --original-report PATH_TO_RUN/benchmark.json \
  --output PATH_TO_NEW_COMPARISON_DIRECTORY
```

This writes a separate `comparison.json` and preserves the original report's
status. It checks the selected generation and catalog ID against that report,
pins the comparison inputs, and verifies them again afterward. New benchmark
reports also supply original output hashes. Older reports lack those hashes,
so recovery reports explicitly leave historical byte identity unverified.

The full Linux metadata-rebuild budget is below 8 GiB. A fixture
smoke test cannot establish this full-corpus result. CI runs the benchmark
against a small retained archive and uploads its report, alongside recovery
tests that cover receipt/index interruptions and partial collector failures.
A verification cache hit may skip the smoke report; the cache identifies the
same code revision and installed dependency environment. Full qualification
requires the pinned corpus run above on the target Linux worker and retained
report evidence.

The capture table and some URL/body lookup collections still grow with the
archive. A passing full-corpus run establishes the budget for that snapshot,
not a constant memory bound for archives of any size. Standalone local refresh
also has repeated capture scans that the production retained-store rebuild
does not use. Metadata qualification does not measure a new body download,
hosted GitHub Actions execution, or publication to live R2 storage.

## Verified local result, 4 October 2026

The frozen `candidate-final-code` run passed complete record and field-schema
comparison against the reference pair. It also passed the final checks on
consumed inputs, code, reference files, output files, and the selection manifest.
The report pins 24,370 consumed or missing object keys; unread bodies remain
outside that inventory.

| Whole-pipeline measurement | Result |
| --- | --- |
| Filename rows, equal in both outputs | 671,035 |
| Grouped documents, equal in both outputs | 553,914 |
| Sampled aggregate Linux resident memory | 3.96 GiB; passes the 8 GiB budget |
| Rebuild elapsed time, excluding comparison | 2,285.49 seconds / 38 minutes 5 seconds |
| Sampled temporary storage before the final sort-index change | 15.99 GiB, including open deleted SQLite sort files |

This ran on Linux aarch64, Python 3.12.15, PyArrow 23.0.1, with two workers,
three container CPUs, and a 10 GiB container limit. Memory qualification uses
process resident memory, not the container's total including filesystem cache.
These timings do not establish a speedup over the earlier macOS measurement.

The final source adds one SQLite index on `output_documents(sort_name,id)`.
That line was qualified separately against all 553,914 completed documents:
the original and indexed queries produced identical ordered payload hashes and
row counts. The index occupies 58.48 MiB and eliminates the temporary payload
sort. The isolated query took 24.41 seconds with the index versus 382.66 seconds
without it; sampled scratch fell from 11.63 GiB to 5.26 GiB. These probes used
reconstructed rows and concurrent one-CPU containers, so their physical sizes
and timings describe the isolated query, not another whole-pipeline run.

The 3.96 GiB and 38-minute whole-pipeline results therefore belong to the frozen
source immediately before that one-line change. Final hosted CI disk capacity
and whole-pipeline resource use after the index change remain unmeasured.

Final local validation passed 6,569 offline tests and 31 subtests. The five
native fetch tests skipped by that run passed separately with the existing Rust
binary. Ruff, actionlint, and the scoped whitespace check passed. Independent
semi-formal reviews closed the blocking findings; the growth limits above
remain explicit.

Local evidence is retained under `.cache/core-workflows-20261004/`:
`linux-results/final-full-linux/benchmark.json`,
`final-linux-temporary-storage.json`, `final-linux-environment.json`,
`output-sort-comparison.json`, the original/indexed sort reports, and
`review-publication.json`, `review-workflows.json`, and `review-bounded.json`.
`completion.json` records the final source hashes and validation logs.
