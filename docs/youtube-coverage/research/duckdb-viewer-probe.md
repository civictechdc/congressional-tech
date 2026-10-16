# DuckDB-Wasm viewer probe

October 14, 2026. Catalog `5272bb4b85ed4549b1fcc3008077bf6d`: 1,672,092 source records and 1,235,122 groups.

**Decision: keep the current viewer reader.** DuckDB can express the filters in SQL and read complete nested provenance directly from Parquet. The tested implementation preserves the results, including recovered files, but adds startup cost and makes warm interactions slower. It is an experiment, not a production change.

## What was compared

The production `createFilenameCatalog` reader, using Hyparquet 1.31.2, was compared with `@duckdb/duckdb-wasm` 1.33.1-dev57.0, the npm `latest` tag at the time of the probe. The latter reports engine v1.5.4. Both read the same locally retained publication and verified recovery overlay. DuckDB used its single-thread Node/Wasm runtime, existing group mappings, SQL filters, and Arrow results; it did not use native Python DuckDB.

Three fresh processes per arm ran the same sequence on Node 26.9.0 with a 1 GiB V8 heap limit. Timings include local reads and decoding, but exclude module imports before the timer, network transfer, UI rendering, and browser worker startup. V8's heap limit does not limit Wasm linear memory or total process memory. The operating-system cache and concurrent machine load were uncontrolled; these ranges describe the runs, not population percentiles.

| Operation | Current reader | DuckDB-Wasm |
|---|---:|---:|
| Initialize, prepare navigation, show first 50 | 169–176 ms | 1,292–1,717 ms |
| All records: None saved | 79–90 ms | 563–1,130 ms |
| First filename search: `lindenbaum` | 1,736–2,733 ms | 1,226–1,849 ms |
| Next filename search: `becerra` | 140–177 ms | 1,246–1,430 ms |
| `lindenbaum` plus `testimony` | 833–946 ms | 1,124–1,342 ms |
| Missing document kind | 45–46 ms | 554–670 ms |
| Complete Becerra source detail after searches | 339–403 ms | 2,404–3,822 ms |

The first filename search has overlapping timing ranges; it does not establish a universal speed improvement. The current reader caches decoded search columns. The DuckDB prototype queries Parquet again, although its file cache avoids most repeat disk reads. Materializing a search table might improve warm SQL queries, but that adds preparation work and memory and was not tested.

DuckDB's direct detail read consumed 3,620,864 file bytes versus 7,978,809 through the current detail path. This is a real reduction for this specimen, but not a measured network-speed improvement. Its node filesystem block reads must not be counted as browser HTTP requests.

Peak resident memory over the sequence was 872–880 MiB for DuckDB and 934–972 MiB for the current reader. DuckDB used more memory immediately after initialization (342–346 MiB versus about 94 MiB) and reached 429 MiB of Wasm linear memory after detail decoding. Neither sequence establishes a safe phone memory budget. The exception-handling Wasm module alone is 35.9 MB, or about 8.1 MB when locally gzip-compressed; this is an asset-size estimate, not measured deployed wire traffic.

## Correctness and simplification

All seven cases matched the independent reference's **complete ordered group-ID sets**: default browse, no saved responses, saved responses, both filename searches, the combined search/classification filter, and missing classification. Totals, first-page preferred source rows, and displayed filenames matched the production reader. Three page-sized repeats also matched.

The recovery overlay covers 8,312 source positions and 8,312 groups. It changes 107 groups from unsaved to saved; the SQL query excludes all 107 from “None saved,” preserving the total of **48,994**. Saved status is evaluated across the group, while filename and classification conditions apply to the same source row before grouping.

A separate recovered-PDF detail check preserved all original source fields and the accepted recovery object: **348 fields**, with no mismatches. That specimen already points to the same retained body in both places; the check does not assume they must differ.

The Becerra case returned all **347 fields and nine observations**, exactly equal to the current reader, directly from Parquet. This shows that DuckDB avoids the earlier direct-Hyparquet nested-detail failure for this selected record. It does not establish correctness or memory bounds for every unusually large observation list.

SQL makes the relationship explicit:

```sql
SELECT DISTINCT groups.group_id
FROM read_parquet('filenames.parquet', file_row_number = true) AS source
JOIN source_groups AS groups ON source.file_row_number = groups.source_row
WHERE contains(lower(source.filename), 'lindenbaum')
  AND list_contains(source.document_kind, 'testimony');
```

The complete probe also handles recovered filenames, nulls, group flags, accepted recovery status, counts, and ordering. Replacing those JavaScript scans with SQL is a concrete simplification. It does **not** yet remove navigation files, group-identity rules, recovery validation, or publication versioning. Supporting the runtime and result conversions would add responsibilities. No net reduction in maintained production code has been established.

## Next decision

Do not replace the production reader on this evidence. The smaller `parquet-wasm` detail experiment remains a more focused candidate for removing the custom observation representation without loading an entire query engine. DuckDB becomes more compelling if users need arbitrary combinations of filters, joins, or aggregations that the current viewer cannot express.

A later DuckDB experiment should first measure a narrowly materialized search table against the existing decoded-column cache. Only a favorable result warrants browser HTTP-range and actual mobile-memory testing. Those checks were deliberately left **unmeasured** here so this research would not delay saved-copy access. DuckDB's documentation says partial remote reads depend on the HTTP implementation; its built-in extension can follow a different path from explicit JavaScript URL registration. That distinction needs a real browser check before any network claim. [DuckDB-Wasm overview](https://duckdb.org/docs/current/clients/wasm/overview), [file registration](https://duckdb.org/docs/current/clients/wasm/data_ingestion).

## Reproduction

The ignored `.cache/duckdb-viewer-probe/` directory contains the predeclared `experiment.md`, frozen manifest and digest-verified recovery overlay, pinned package, `baseline.mjs`, `duckdb.mjs`, `duckdb-all-results.mjs`, independent `reference.py`, `verify.py`, three run outputs per arm, `verification.json`, and `report.json`. The first full-result DuckDB run checks equality; its timings are excluded from the page-sized comparison above. The experiment note records fixture/import corrections and an Arrow ESM/CommonJS interoperation failure, resolved by serializing through the public IPC insertion API. No production dependency or publication format changed.
