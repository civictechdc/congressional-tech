# Filename viewer: performance findings and proposal

Reviewed October 13, 2026. Code: `9212013df06e2eaf4d81dc87adafbd75d8d19b69`.
Catalog: `4ca7d4a58bf04efc9e016e0cbacc3ef8`; 1,024,227 source rows and 708,541 groups.

**Recommendation:** keep the static architecture. Give browsing, searching, and opening a record their own small read paths. Fix detail memory amplification first, publish a narrow search index next, then defer navigation indexes and cache decoded results.

The original sections below record the research proposal. The implementation follow-up at the end records the changes and local verification for items 3 and 1 on October 13. Deployment status is recorded separately in GitHub Actions. Experimental data, scripts, and raw measurements are in [the local probe folder](../../../.cache/filename-performance/).

## Measurements and limits

Two fresh Node processes ran the existing JavaScript reader against the live GitHub Pages catalog, in the same sequence. These measure HTTP reads plus catalog decoding and query work; they exclude UI rendering. Neither run had the reader's in-memory cache initially. CDN cache state and network latency were uncontrolled. The second run was substantially slower on some network requests, so the range below is useful evidence, not a population percentile or a service guarantee.

| Operation | Two live-reader runs | Requests | Bytes delivered to reader |
|---|---:|---:|---:|
| Initialize and read first 50 results | 2.31–3.41 s | 8 | 12.35 MB |
| Next page, within cached block | 11–15 ms | 0 | 0 |
| All records, no saved responses | 0.21–0.57 s | 6 | 0.17 MB |
| First filename search: `lindenbaum` | 9.46–21.53 s | 258 | 10.62 MB |
| Another filename search after columns load | 111–155 ms | 1 | 0.04 MB |
| First `testimony` classification filter | 1.21–1.32 s | 126 | 0.27 MB |
| Open Lindenbaum detail after searching | 7.41–9.68 s | 5 | 10.36 MB |
| Reopen that same detail | 1.00–1.13 s | 1 | 0.15 MB |

MB means decimal megabytes. These are response-body bytes after HTTP decoding, not universally wire bytes: Pages already serves navigation `.bin` files with gzip. Parquet ranges contain compressed Parquet data. The detail row above is not a fully cold deep link: filename-table metadata was already cached by the preceding search. It uses the stable source ID, which also requires one ID-prefix lookup.

The live browser returned the expected eight search results and loaded the Lindenbaum detail without console errors. The available browser interface did not expose performance timelines or a tracing facility. LCP, CLS, INP, throttled-phone behavior, and production browser heap use were **not measured**. No Core Web Vitals score is claimed.

## 1. Bound the work needed to open one record

**Highest priority: reliability as well as latency.** Opening `Xavier Becerra (1).pdf` (source row 262424) exhausted the Node process's approximately 4 GB heap in both the live-file and local-file probes. Its own record has eight observations. Its 8,192-row source block contains 1,375,000 observations. Reading one row still decodes neighboring nested lists before returning the selected row.

The reader also loads all 337 document-table fields although the current detail UI uses only `filename`, `document_kind`, `document_kind_source`, and `source_id` from that document record. It loads the complete selected source record immediately, including technical evidence that is initially collapsed. Source-list reads request six columns but the custom prefetch still fetches the entire row group. See [catalog reads](../../../apps/site/src/components/filenames/catalog.mjs) (`read`, `selected`, `entry`) and [detail rendering](filename-viewer.mjs) (`renderSummary`, `renderDetails`).

Experiments on the Becerra record:

| Candidate | Result |
|---|---|
| Original 8,192-row block | Exhausted approximately 4 GB heap |
| Page indexes plus 16 KB pages, same row group | Still exhausted a 768 MB test heap; not a sufficient fix |
| 128-row Parquet shard | Preserved all 334 fields; 243.7 KB, about 128 ms locally; a later 128 MB heap-limit run failed |
| 16-record gzip JSON block | Preserved all 334 fields and all eight observations; 13.6 KB compressed, 405.9 KB decoded; passed under a 128 MB Node heap limit |
| 128-record gzip JSON block | Same exact target-record equality; 89.6 KB compressed, 3.06 MB decoded |

The gzip JSON blocks were also tested in a real browser worker through `DecompressionStream('gzip')`. Across two local-browser runs, the 16-record block decoded in **2.2–6.4 ms** and the 128-record block in **14.2–14.4 ms**. These exclude production network latency and the complete detail UI. They establish a promising access format for this specimen, not corpus-wide qualification.

**Proposed implementation:** retain complete Parquet downloads as the archive representation. Publish an additional, indexed detail representation whose blocks are bounded by decoded size as well as row count. Small compressed JSON blocks currently have stronger evidence than small Parquet blocks for this schema. Load the human summary first and original observations when requested; preserve exact values and all observations. Oversized individual records need separately addressable observation pages, not truncation. Compare every reconstructed record against Arrow before publication.

The publication-size cost must be measured across the full corpus before selecting a block size. The existing combined Pages artifact is already roughly 919 MB under its configured 1,000 MB budget. If the derived detail files exceed that budget, use static object/CDN hosting for the published assets or reduce duplicated derived data. This does not require a query backend or exposing the private raw archive.

## 2. Publish a narrow search file

The current filename search reads the full schema's 6.50 MB footer, then scans `filename` and `recovered_filename` in 126 row groups: **254 requests and 10.51 MB for the search columns alone**, plus four browse reads in this example. The classification filter spends 126 requests retrieving only 0.27 MB.

A local prototype contains seven existing source columns: filename, recovered filename, publisher URL, Congress, document family, document kind, and format. All 1,024,227 rows and all seven columns were compared with the original Arrow table and were equal.

| Layout | Whole derived file | Reads for filename search | Search-read bytes | Local column read + match time |
|---|---:|---:|---:|---:|
| 65,536-row groups | 9.47 MB | 33 | 4.36 MB | 0.25–0.55 s |
| One source-sized row group | 8.51 MB | 3 | 3.75 MB | 0.26–0.48 s |

Both prototypes returned the same eight group IDs as an independent scan of the original Arrow data. The one-group prototype removes **98.8% of search-column requests and 64.3% of search-read bytes** in this case. These timings are local-file measurements, not projected live-site latency.

**Proposed implementation:** scan this narrow file for common search/filter fields, using Hyparquet's public column-oriented `onChunk` callback. Retain the complete Parquet path for uncommon fields. Keep the existing source-to-group mapping: search and filter conjunctions must match the same source row, while saved-response status must still consider every URL in the group. Do not replace this with a canonical-filename-only search or independent group-level facet intersections.

Hyparquet specifically recommends row/column selection and notes the cost of converting column data into row objects. [Hyparquet documentation](https://github.com/hyparam/hyparquet#advanced-usage)

## 3. Defer startup indexes until needed

Initialization currently waits for four arrays totaling 10.47 MB before even returning catalog information. `groups.bin` (4.10 MB) is needed for searching/group lookup; `document_rows.bin` (2.83 MB) is needed for details. Neither is needed to show the default first results. The derived membership linked lists allocate another 6.93 MB and are only used by detail loading.

**Proposed implementation:** return manifest information immediately; load only flags and preferred-row navigation for simple browsing. Load group mappings for search and document/membership mappings for details. This defers **6.93 MB of decoded index data** and **6.93 MB of derived membership arrays** from the initial browse path. It does not promise an equivalent reduction in wire bytes because HTTP gzip is already enabled.

A later refinement can embed the preferred source locator in browse rows, avoiding the separate 2.83 MB preferred array on initial load. A small generated first-page file could also avoid reading the browse table's 1.82 MB footer before displaying 50 results. Measure these before adding another format.

## 4. Cache decoded records and share pending reads

The existing compressed-byte cache is useful: next-page reads and warm searches are already fast. However, reopening a detail still re-decodes its nested data and repeats its source-ID prefix request. The example costs about one second even with its Parquet blocks cached.

**Proposed implementation:** add a bounded decoded-entry cache keyed by catalog and source ID, cache ID-prefix lookups, and share in-flight metadata/index loads. Keep cancellation scoped so one superseded query cannot cancel data another active query needs. Use byte budgets for large decoded records; a four-column count alone does not bound memory. Yield periodically during long CPU scans so the worker can process cancellation messages.

Reusing decoded records should remove repeated decoding, but the end-to-end improvement has not yet been measured. Validate with repeated open/close and rapid typing sequences rather than assuming a cache hit is equivalent to instant rendering.

## Delivery order and acceptance checks

1. Add timing marks for catalog ready, results visible, detail summary visible, and original evidence ready. Record request counts and byte totals in a development-only audit harness. [User Timing API](https://developer.mozilla.org/en-US/docs/Web/API/Performance_API/User_timing)
2. Implement bounded detail access and narrow document/source-list reads. Test the Becerra failure case and records with the most observations; compare all returned values and copied JSON.
3. Add the narrow search file. Verify search results, recovered filenames, same-source filter conjunctions, and group-wide saved-response semantics across the entire corpus.
4. Defer startup indexes and add bounded caches. Verify stale snapshot links, cold and warm navigation, cancellation, and cache eviction.
5. Measure actual mobile Safari and Chromium under a recorded bandwidth/latency profile. Proposed budgets: ordinary detail block at most 256 KB compressed / 2 MB decoded; warm reopen under 100 ms on the reference desktop; first common-field search at most five data reads before browse-result hydration. Large records must use explicit paging rather than lose evidence.

Keep the publication-size gate and full source-value verification. The search prototype adds 8.51 MB; full detail-publication size is an unresolved adoption gate.

## Approaches not prioritized

- Replacing the static viewer with a backend or a different SQL engine: the measured costs are oversized reads, excessive request counts, and nested decoding. Those can be addressed within the existing architecture.
- Cosmetic bundle or font optimization: the viewer bootstrap, UI, and worker total about 212 KB uncompressed in the local build, with system fonts. Multi-megabyte data reads dominate this audit.
- Simply increasing fetch concurrency: it does not fix the memory failure or remove the 6.50 MB search footer.
- Merely enabling page indexes: the bounded experiment failed. [Parquet page-index documentation](https://parquet.apache.org/docs/file-format/pageindex/) explains their intended page-skipping role; it does not establish that this reader avoids every nested allocation.
- Treating Parquet min/max statistics or Bloom filters as an arbitrary substring index: this search uses case-insensitive `includes`. Such pruning needs a proven predicate-specific design. [Parquet Bloom filters](https://parquet.apache.org/docs/file-format/bloomfilter/)
- Recommending gzip as a missing server feature: the live navigation files already use it. Generation-specific files have a ten-minute cache lifetime; stronger immutable caching can help revisits if hosting allows it. [HTTP caching guidance](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Caching)

## Reproduction evidence

The ignored local folder `.cache/filename-performance/` contains:

- `probe.mjs`, `live.json`, `local.json`: original reader runs, followed by the reproducible Becerra memory failure.
- `probe-safe.mjs`, `live-repeat.json`: second live run that skips the known failing record.
- `search-probe.mjs`, `search-prototype-results.jsonl`, `search-prototype-repeat.jsonl`, `search-validation.json`: narrow-file measurements and equality checks.
- `detail-probe.mjs`, `shard-probe.mjs`, their output/error files: page-index and small-Parquet experiments, including failed memory-budget probes.
- `json-detail-probe.mjs`, `json-detail-results.jsonl`: bounded JSON decoding and exact target-record equality.
- `index.html`, `json-detail-worker.js`, `browser-detail-results.json`, `browser-detail-probe.jpg`: browser worker experiment and captured evidence.

The installed Hyparquet 1.31.2 reader files used by these probes were compared with the official npm package and matched. No dependency files were modified.


## Implementation follow-up: items 3 and 1

Implementation and local verification completed October 13, 2026. The measurements below describe that verification; they are not production performance measurements.

Item 3 now returns catalog information after reading just the manifest. Ordinary
browsing loads only flags and preferred-source rows. Searches load group mappings;
details load document mappings and build membership arrays. Shared navigation
loads survive cancellation by an individual caller, and failed loads can retry.

Item 1 keeps both complete Parquet downloads and all their Arrow values/schema.
Ordinary source metadata is decoded eight columns at a time. Detail summaries
use a three-column derived table, and source-list prefetches include only their
requested columns. Nested observations have a separate indexed representation:
identical observations share dictionary storage, and Brotli-compressed parts
expand to at most 1 MiB each. Large individual values can span parts. The reader
restores original field order, nulls, empty arrays, repeated observations and
observation order. Compression uses the existing decoder dependency.

A complete duplicate of source records was too large for the hosting budget.
Separating only nested observations and deduplicating their storage kept this
change within the existing budget without exposing R2 or changing the originals.
The publisher read back every reconstructed observation list for all 1,024,227
sources and compared it to Arrow; it also reverified every value and schema in
both full Parquet files.

### Verified measurements

Fresh local reader runs use Node 26.9.0 with a 256 MiB V8 heap limit. They include
local file I/O, decoding and catalog work; they do not measure production-network
latency or phone browser performance. The final run is saved as
[local-v2-final.json](../../../.cache/filename-performance/local-v2-final.json).

| Check | Result |
|---|---|
| Initial browse bytes delivered to reader | 12,351,187 → 5,420,960 bytes, 56.1% less; 8 → 6 requests |
| Deferred navigation data | 6,931,072 bytes, plus 6,931,072 bytes of membership arrays |
| Becerra detail, previously exhausting roughly 4 GB | 441 ms in final local run; 448 ms in an earlier run; completes with a 256 MiB heap limit |
| Exact Becerra source equality | All 334 fields match the original Arrow record |
| Largest observation list | All 11,967 observations returned under the same heap limit; 1.77 s in the final local run |
| Lindenbaum detail after Becerra | 128 ms local; 9 observations preserved; not a cold deep-link timing |
| All-record no-saved-response count | 48,435, unchanged in reader and actual browser |

The largest record still needs 287 reads in this probe. This work fixes its
memory failure; it does not establish fast production-network loading for that
outlier. A later request-coalescing or progressive-evidence change can address it.

The filename publication is 576,790,751 bytes, 62,290,688 bytes larger than before.
The built site plus the currently published Explorer files totals 981,281,204
bytes, leaving 18,718,796 bytes under the 1,000,000,000-byte gate. This is the
combined size calculation, not a new deployed artifact. The gate stays enabled
for future snapshots.

Validation: 62 browser/reader tests pass; Astro checks 48 files with no errors or
warnings; the production build succeeds. Added tests cover deferred requests,
concurrent cancellation, dictionary ordering/duplicates/nulls, UTF-8 split across
compressed parts, invalid references, and full Python-to-JavaScript reconstruction.
The actual browser loaded Becerra and Lindenbaum, showed the expected referring
websites and 334 source fields, and logged no errors. The copy action reported
success; the automation clipboard could not read its contents, so copied-value
parity is established by the returned record tests rather than clipboard readback.

A forced `Accept-Encoding: gzip` range probe initially suggested a hosting issue.
That request did not match normal browser behavior: Fetch adds `Accept-Encoding:
identity` for range requests. A normal live fetch returned the exact 1,024 bytes
and original file length. No ZIP wrapper or HTTP header override was added.
[Fetch Standard, HTTP-network-or-cache fetch](https://fetch.spec.whatwg.org/#http-network-or-cache-fetch)

This change does not implement the separate narrow-search index (item 2) or
cross-request decoded-record cache (item 4). Advanced searches over the complete
nested observation column still use the existing Parquet scan; the bounded path
applies to detail loading.
