# Catalog rebuild performance

Decision: Reduce the repeated work and disk expansion in catalog updates while preserving every published source, document group, and provenance value.

Observed problem: The recovery run processes 1,672,092 source rows, uses a 43.8 GB SQLite working file, and loops through document groups with repeated payload reads and per-row queries. Existing published Parquet files already retain reusable interpretations. The active recovery runtime is pinned and must finish unchanged.

Hypothesis: Sparse storage of Arrow-null fields, compact grouping state, and bulk comparison against the previous published pair will reduce local reads, writes, and grouping time. A second permanent copy of the full working database may cost more than reusing the published pair and is not assumed to be an improvement.

Arms: The committed implementation at ef050c2 versus the candidate implementation, using the same interpreter, input rows, schema, prior catalog, and worker count.

Cases: A frozen sample of real published source records; constructed endpoint/body bridges, splits, duplicate observations, failed shared responses, capture-only records, unchanged updates, and sparse updates. Real samples measure bounded performance; constructed cases check invariants and are not population estimates.

Held constant: Record order, retained inputs, compression settings, process configuration, and output schema. Run each performance arm three times in alternating order after a small smoke run. Limit each initial measurement to 20,000 source records and five minutes. Do not read the live recovery SQLite database or write to R2.

Decision rule: Adopt only with exact semantic equality for both Parquet tables (including null versus empty values and nested provenance), passing merge/split and publication tests, and a measured improvement in elapsed time or intermediate storage with no material regression in the other. Report measured scope; do not extrapolate a full-corpus runtime from a selected sample. If a proposed optimization fails this rule, retain its measurements and reject or revise it explicitly.

## Results

Bounded improvement; adopt the grouping changes. Three alternating repetitions used 10,211 real source records (7,262 document groups). Every source and document value, type, null, nested observation, and row position matched across all nine case/repetition pairs. Metadata also matched except the generated catalog ID and implementation fingerprint.

| Grouping case | Baseline median | Candidate median | Speedup | SQLite before → after |
| --- | ---: | ---: | ---: | ---: |
| Cold | 10.89 s | 6.66 s | 1.63× | 192.5 → 109.7 MB |
| Unchanged | 15.82 s | 7.71 s | 2.05× | 501.8 → 217.1 MB |
| 103 changed sources | 14.41 s | 7.86 s | 1.83× | 501.1 → 217.4 MB |

Unchanged updates reused all 7,262 groups. Sparse updates reused 7,159 and recomputed 103. Cold time ranged 10.87–11.07 s versus 6.49–6.72 s; unchanged 15.01–16.16 versus 7.66–7.72; sparse 13.74–14.64 versus 7.53–8.33. Temporary storage fell 43% for cold grouping and 57% for updates.

The bundle stores null-padded records sparsely, keeps integer group pointers in memory (eight bytes per source), compares previous groups with one indexed SQL pass, and decodes small changed groups once. Large groups retain the streaming path. Reuse requires every previous member and matching source signatures, including after splits and merges.

A separate constructed map lookup check (20,000 new keys followed by existing-key defaults, three repetitions) reduced SELECTs from 80,000 to 40,000 and median elapsed time from 0.163 to 0.102 s. This removes a redundant lookup; it is not a pipeline timing estimate.

Limits: This measures the grouping component, including paired export and validation, on selected records. It excludes receipt replay, context expansion, source interpretation, remote publication, and restart. Recovery ran concurrently, and filesystem caches were warm. No full-corpus runtime or peak-memory improvement is claimed. The code still scans the input catalog; this is more efficient group reuse, not a fully incremental pipeline. The active recovery runtime was unchanged. That session separately repaired durable preparation so a publication outage no longer deletes a completed build.

## Reproduction

The frozen source was catalog `9eb191117dbf4ba9ad8b3b03a9c0c6a4`, source Parquet SHA-256 `7d9e5759555951dcb5b3ef3eeecf9b34bb36c98baa1f7231099f8955acba4861`. Take the first 256 rows from each of the 40 row groups recorded in [the results](catalog-rebuild-performance-results.json), concatenate in that order, and preserve the source schema. The resulting sample has 10,211 rows and 61,014,071 Arrow bytes. The local sample and all paired outputs remain in `.cache/catalog-performance/`; the JSON records the sample hash and individual measurements.

Save baseline `catalog_staging.py` from `ef050c2` and run each arm in a separate process with the same package environment:

```sh
PYTHONPATH=packages/congress_api/src python scripts/benchmark_catalog_grouping.py \
  --sample SAMPLE.parquet --implementation BASELINE.py --label baseline --output NEW_BASELINE_DIR
PYTHONPATH=packages/congress_api/src python scripts/benchmark_catalog_grouping.py \
  --sample SAMPLE.parquet --label candidate --output NEW_CANDIDATE_DIR
```

Repeat three times in alternating order. Compare both files in each `cold`, `unchanged`, and `sparse` directory with Arrow `Table.equals`, then compare schema metadata excluding only `catalog_id` and `document_grouping_fingerprint`. Timing includes SQL tracing in both arms. macOS reports `ru_maxrss` in bytes; the portable harness retains platform-native units explicitly.
