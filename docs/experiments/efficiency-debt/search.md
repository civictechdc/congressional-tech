# Broad browser search: retain the current exact scan

The bounded row-group candidate did **not** meet its declared latency target.
Keep the reader at exact merged baseline `3757f55ed33ea390895c20a2007cb08eb39ce519`.
The candidate eliminated repeated normalization and reduced active source-column
estimates, but doubled retained decoded work and slowed cold arbitrary searches.
No product source or data format changes ship for `ct-4zer`.

## Decision and measurements

The target, fixed before comparison, required at least 25% faster warm wide-field
search, at least 90% less repeated normalization/decode work, unchanged results,
no case median more than 20% slower, decoded/compressed estimates within 64/48 MiB,
and process RSS below 1 GiB. Each arm had a 90-second deadline and a 768 MiB Node
heap ceiling. RSS was checked every 20 ms between event-loop turns; this is a
sampled experiment guard, not a hard native-allocation bound.

The fixture contains 8,192 deterministic sources in 4,096 paired document groups,
32 physical source row groups of 256 rows, about 1 KiB URL/arbitrary list values,
20% null arbitrary values, and 113 unique nested Unicode observations referenced
by 8,192 sources. The five cases cover broad URLs, sparse arbitrary fields,
same-source congress AND with numeric paging, Unicode observations and null JSON
fields. Three repetitions per case run cold (new application caches) and warm
(the same reader). Local file ranges use the same bytes for both arms; OS caches
are not cleared. Node is pinned to 22.22.2.

| Case | Cold baseline → candidate | Warm baseline → candidate |
| --- | ---: | ---: |
| Source URL | 62.78 → 68.87 ms | 36.72 → 37.54 ms |
| Wide arbitrary field | 49.73 → 63.13 ms | 32.24 → 32.27 ms |
| Same-source AND and page 2 | 60.13 → 78.60 ms | 36.25 → 34.20 ms |
| Unicode observations | 65.54 → 75.17 ms | 45.13 → 47.72 ms |
| Null-field observation JSON | 63.13 → 65.93 ms | 45.04 → 47.19 ms |

All 30 result hashes match across arms. The warm wide-field target failed
(0.1% slower); cold wide-field and AND medians regressed 27.0% and 30.7%.
The candidate is rejected without changing the targets.

## What work changed

The candidate consumes one physical source row group at a time and retains
normalized search text per row group in the existing cache. It uses the same
maintained Parquet reader and exact predicates. Its complete patch and source
hash are retained in the raw evidence, then reverted from the shipping tree.

| Cost | Current scan | Candidate | Meaning |
| --- | --- | --- | --- |
| Warm transfer | 0 additional bytes/requests | 0 | neither benefits from new transfer avoidance |
| Cold metadata | one source and one browse initialization | same | metadata ownership already works |
| Cold source decode | every selected physical source column/group | same rows | candidate serializes group consumption instead of six column workers |
| Warm source decode | 0 new column loads | 0 | current cache already avoids this work |
| Warm source text normalization | 8,192 values per arbitrary case | 0 | work-count assertions pass for all three scalar cases |
| Warm source/group scans | 8,192 / 4,096 visits | same | broad exact scan remains required |
| Warm scalar cooperative yields | 22 | 22 | event-loop scheduling remains in the path |
| Warm observation/reference scan | 113 / 8,192 visits | same | prepared text does not remove reference traversal |
| Warm observation logical decode/normalization | 0 / 0 | same | current cache already avoids these costs |
| Selected browse physical values | 23,552 per page, 47,104 for page 2 case | same | source-column preparation does not change browse chunk decoding |

Whole-case and local transfer times are measured. Metadata, physical decode,
normalization and scans are distinguished by counters rather than isolated CPU
timers. The unchanged scans, yields and browse decode are a reasonable explanation
for the weak warm-latency response, not a profile proving one exclusive bottleneck.

For the URL and wide arbitrary fields, current whole-column retained estimates
are 15,398,764 and 14,273,380 bytes. The candidate's maximum active column and
source-search batch estimates are 481,304 and 962,616 bytes, excluding native
decoder state and other operation-owned data. Yet peak decoded-cache estimates
increase **19,101,790 → 34,512,864 bytes**, and process high-water RSS increases
**171,622,400 → 179,617,792 bytes**. Both arms stay below the ceilings; reduced
source temporary storage is not a measured process-memory improvement.

A future improvement needs evidence that it reduces scans, reference traversal,
browse decoding or scheduling costs for useful different queries. This experiment
does not justify another index, data representation or result-cache route.

## Verification and retained history

The rejected candidate passed 17/18 catalog tests. Its remaining failure is the
old `columnLoads` work-count expectation (four group loads versus one whole-column
load), not a result mismatch. It was not promoted to complete behavior qualification.
After reverting, **all 104 filename tests passed** in 4.96 seconds, including exact
arbitrary values, nested/null/Unicode observations, same-source AND, recovery and
review behavior, ordering/paging, cooperative cancellation and independent shared
waiters. Current catalog and observation source hashes remain the merged baseline.

Reuse the committed
`docs/experiments/publication-remediation/evidence/browser-metadata-reuse.json`
for the retained actual-catalog result: **27.523 seconds, 1,014,639 matches**. Its
raw receipt paths are no longer present; the committed evidence retains their
hashes and samples. That historical probe is not a current latency guarantee.
No source acquisition, hosted/browser run, full-catalog qualification, workflow
change or public write occurred here.

Setup logs are preserved: the pre-integration draft failed its import before
creating data; a malformed document-representative fixture was refused; a one-group
publisher layout was measured as setup before correcting the consumed generated
fixture to the already-declared 256-row groups. Complete Arrow equality and the
generated manifest hash were refreshed after that synthetic layout rewrite.
Targets were unchanged. Paused-draft and cleanup/runtime recovery did not supply
an accepted baseline. The final paired comparison uses only fixture v4 and the
exact merged source baseline.

## Reproduce and evidence

`search-fixture.py` creates synthetic data only; it calls the maintained publisher
and explicitly fixes the generated source Parquet groups for this experiment.
`search-benchmark.mjs` measures the maintained local loader, records hashes,
work counters, retained cache estimates and process memory. Use an isolated locked
Python environment and the pinned Node runtime:

```sh
UV_PROJECT_ENVIRONMENT=output/efficiency-search-runtime/venv uv sync --locked --offline
output/efficiency-search-runtime/venv/bin/python docs/experiments/efficiency-debt/search-fixture.py NEW_FIXTURE
node --expose-gc --max-old-space-size=768 docs/experiments/efficiency-debt/search-benchmark.mjs NEW_FIXTURE BASELINE_JSON 3
PYTHON="$PWD/output/efficiency-search-runtime/venv/bin/python" node --test apps/site/src/components/filename-*.test.mjs
```

The candidate patch applies to `3757f55`. Re-run the same benchmark against the
same generated fixture after applying it, then revert it; it is an experiment,
not a supported alternative loader. Small committed hashes/results are in
[search-evidence.json](search-evidence.json). Raw receipts, failed setup logs,
plan, complete candidate patch, work-count/equality assertions and test log are
at primary `output/efficiency-debt-20261019/search/`. The work-count checks require
8,192 → 0 warm normalizations and unchanged 8,192 / 4,096 scan visits for all
three scalar cases. The candidate remains rejected even though those checks pass.
