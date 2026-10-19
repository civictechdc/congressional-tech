# Keep less publication state in the existing Catalog

The publication reader now retains **8,950,006 fewer Arrow bytes (43.9%)** for source rows in the bounded fixture. The publisher also drops six unused document columns before sorting browse rows, avoiding copies it previously discarded. **The controlled comparison demonstrates no overall process-peak or speed improvement.**

`Catalog(search_indexes=False)` reads eight grouping, identity, URL and facet columns and streams saved-response inputs in batches of at most 8,192 rows. The existing saved-response decision, memberships, preferred sources, document table and review binding remain authoritative. Interactive `search` and `entry` requests restore list columns through one method under the existing reader lock. Direct `searchable` requests use the existing locked column reader when the column is absent. Lazy operations require an open Catalog; ownership and reader closure stay with its context manager.

| Three fresh-process samples per arm, median | Baseline | Change |
| --- | ---: | ---: |
| Retained source Arrow bytes | 20,405,570 | 11,455,564 |
| Constructor seconds | 0.15374 | 0.15618 |
| Constructor process highwater bytes | 209,338,368 | 208,519,168 |
| Complete publication seconds | 5.35961 | 5.29077 |
| Complete publication process highwater bytes | 315,277,312 | 315,850,752 |

Retained Arrow bytes measure logical column data, separately from native buffers, imported libraries, allocator residency and other publication state. The modest timing and highwater differences do not establish a gain. Lowering retained columns alone does not control the process peak; identifying its remaining owner would require a wider stage-allocation investigation, outside this change.

All **269 actual payload files** match in size and SHA-256 across every publication sample; every manifest value matches after removing only `published_at`. This includes ordering, stable-ID shards, flags, browse rows, observations, details and review binding (five bound, three withdrawn). Both original Parquet readers close, and publication does not build search text indexes. The fixture's complete file inventory remains unchanged.

The existing viewer/review/binding checks pass against the frozen baseline (**60 passed**) and final code (**64 passed**). Four added cases cover lazy search and entry parity, direct column search, Unicode and nested source metadata, failed reload state and retry, concurrent promotion exactly once, and resource closure. `git diff --check` passes.

Baseline is `3b87599d27603195146afc36bb30e75ebda8af56`. The [harness](catalog_measure.py) reuses receipt/watchdog helpers from the earlier experiment but loads the actual baseline source from Git; it does not apply the rejected packed-membership change. Run it with the worktree's own environment:

```sh
UV_PROJECT_ENVIRONMENT="$PWD/.venv" .venv/bin/python docs/experiments/efficiency-round-two/catalog_measure.py run OUTPUT --fixture /Users/mikewolfd/Work/congressional-tech/output/efficiency-debt-20261019/catalog/run-3757f55c/fixture
```

The accepted run is primary `output/efficiency-round-two-20261019/catalog/run-2`; [compact evidence](catalog-evidence.json) pins fixture/source hashes, samples, limits and raw receipts/logs. `run-1` is retained but excluded from conclusions because baseline tests overlapped it. The declared child limits are 2 GiB sampled RSS, 600 seconds and 1 GiB owned output; no limit was reached. These are local bounded observations, not full-catalog qualification. The unchanged fixture has 30,906 document groups and 41,030 sources; historical real-row `source_occurrences` are typed nulls, supplemented by existing semantic edge groups. Focused tests separately exercise real nested metadata. No source acquisition, catalog rebuild, live publication, browser work, hosted workflow or held-out evaluation ran.
