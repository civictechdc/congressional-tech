# Source occurrence cache, 2026-10-27

A full offline source-leaf replay fell from **225.30 seconds to 30.60 seconds**
(7.36 times faster, 86.42% less wall time). All six output assets, totaling
5,452,166 bytes, are byte-identical between the baseline and candidate and match
those retained from the earlier qualified leaf. The returned source metadata,
including row slices, facets and occurrence counts, also matches exactly.

This is one sequential before/after run on a shared host, using retained real
source bytes for 6,614 owners and 20,234 observations. It establishes a local
improvement, not production throughput or whole-release speed. No new downloads,
remote writes, live runtime edits, worker changes, source-receipt changes or
access to the active preparation database were needed.

## Change and authority

The selected dependency leaf now supplies a bound occurrence reader. Selection
and physical-schema admission happen once for that reader; its private reference
copy prevents later caller mutations from retargeting it. Existing callers of
`source_occurrences` still receive fresh admission through that same maintained
entry point. Source rendering uses the reader for every owner in its one leaf.

`CatalogRows` now reuses its already admitted descriptor alongside its existing
one-core-table cache. Every call still hashes the complete supplied pin and
checks exact Arrow schema metadata before a cache hit. A changed pin re-enters
binding, format, schema, budget and complete-coverage validation. This avoids
moving trust to object identity or accepting a mutable caller reference.

Child parts already sort by `owner_row` and `occurrence_order` and validate every
owner. Their existing two-entry cache now retains those validated owner positions
with the table. Standard-library bisection finds the contiguous slice for an owner;
ordinal and count checks remain. Data and positions evict together. The extra
Python index is bounded by two selected parts, each no larger than `max_rows`;
no corpus-wide cache was added.

| Operation during full leaf rendering | Before | After |
| --- | ---: | ---: |
| Arrow schema decodes | 31,268 | 5 |
| Descriptor admissions | 11,424 | 1 |
| Rows examined by full owner-equality filters | 97,305,306 | 0 |
| Native input streams replayed | 2 | 2 |

Original values, ordering, nulls, Arrow schemas, observation identities and output
bytes remain unchanged. Source and renderer implementation identities change
because their maintained source hashes include the modified implementation. An
existing frozen runtime or checkpoint cannot silently adopt this implementation;
compatible activation remains a separate operational step.

## Verification

The unchanged focused baseline exited successfully. The final focused catalog
rows, dependency storage and source publication suites passed **41 tests**, with
six qualified-native-CLI tests skipped because `DOCSPEC_BINARY` is not configured.

Added regression cases cover repeated reads; metadata and descriptor mutation;
mutation after creating a deferred iterator; missing owners; null and empty lists;
null structs, duplicates and Unicode; owners crossing part boundaries; index and
table eviction; wrong child owners; and detached selection/reference bindings.
Existing tests retain corrupted counts, missing/duplicate ordinals and bounded
large observations. An independent subagent reviewed the final implementation
and tests and approved with no concrete findings; that review was static.

The additional dependency preparation, dependencies, coalesced batches and
observation publisher suites passed **86 tests**, with three native-CLI tests
skipped. Across both runs: **127 passed, nine skipped**. Commands used the same
explicit four-package `PYTHONPATH` shown in the replay command and `pytest
-p no:cacheprovider -q`, selecting the seven named test modules.

Focused modules: `test_catalog_rows.py`, `test_catalog_dependency_storage.py`,
`test_filename_native_sources.py`. Shared-path modules:
`test_catalog_dependency_preparation.py`, `test_catalog_dependencies.py`,
`test_catalog_coalesced_batches.py`, `test_filename_observations.py`.

## Replay and evidence

[Comparison](source-occurrence-cache-20261027/comparison.json),
[baseline](source-occurrence-cache-20261027/baseline.json),
[candidate](source-occurrence-cache-20261027/candidate.json) and
[source hashes](source-occurrence-cache-20261027/source-pins.json) retain exact
measurements, input digests and output digests. Baseline main was `7ec869f4`;
the candidate starts from `146931b3` with only the recorded scoped changes.
The two later main commits concern the separate local checkpoint recovery tool.

[Replay script](source-occurrence-cache-20261027/replay.py) uses the two retained
`native-input-*.arrow` files from
`output/release-finish-20261026/source-leaf-qualification`. It reconstructs a
one-part occurrence directory and its descriptor binding locally because the
original directory JSON was not retained. Its values, owner fields, schema and
orders come directly from the original Arrow bytes. Both arms use that same
reconstructed delivery metadata; this is not a fresh native runtime qualification
or an assertion that the reconstructed pin equals the production pin.

Run from either source tree, pointing `PYTHONPATH` at that tree's packages:

```sh
PYTHONPATH=packages/viewer_publication/src:packages/congress_api/src:packages/congress_shared/src:packages/docspec_client/src \
  /Users/mikewolfd/Work/congressional-tech/.venv/bin/python \
  docs/experiments/source-occurrence-cache-20261027/replay.py \
  /tmp/source-occurrence-replay \
  /Users/mikewolfd/Work/congressional-tech/output/release-finish-20261026
```

The script writes fresh local assets, result metadata and hashes only to its
first argument. Its store and native reader expose local in-memory data and no
network transport. Measurements include the complete maintained `render_source`
path, including output validation, details and facets, after retained input load.
