# Final data model review: Parquet, Iceberg, optimizer and query plans

Reviewed: `docs/engine-first-data-model.md` revision 2 at `977f9687`. Skills applied:
`parquet-optimization`, `iceberg`, `iceberg-optimizer`, `explain-plan`. Measurements ran
read-only with pyarrow and DuckDB from the project venv on the Oct 19 inputs; temporary files
were deleted. As before, no DataFusion `EXPLAIN` was run, because none exists without a
from-scratch engine build. The plans below are sketched from the SQL and docspec's operator
behavior.

## Verdict

**Sound, with no blockers.** The earlier contradictions are resolved: HTML link keys,
`url_state`, the `detail` core and the `links` statistics. The lake design is deliberately
small: append-only, identity partitions only where queries filter, Basin doing maintenance.
That is the right call at this scale. Two medium items remain, both about the new link-context
feature and the phone decision. The rest are settings and wording.

## Findings

### 1. Link-context joins need a normalized URL key (medium)

`linked_from` joins `page_links.child_url` to member source URLs (§4). Joining the exact
strings misses variants. Measured: **64,860 of 1,158,426 captured URLs (5.6%)** fall into groups
that differ only by scheme (`http`/`https`), `www.`, case or a trailing slash. Earlier traces
showed both `http://docs.house.gov/…` and `https://docs.house.gov/…` for the same files.

**Fix:** a `url_key` used only for joins: lowercase scheme and host, drop `www.`, the default
port, the fragment and a trailing slash, and keep the path's case. Identity (`source_id`,
`requested_url`) keeps the exact URL. Accepted variants beyond that come from provenance
`url_variants`, which the model already lists. Measure the `linked_from` hit rate in M2.

### 2. Bytes per occurrences view are unbounded on phones (medium)

`occurrences.parquet` now has 13 leaves (link context added) with "offset index on every
column; 64 KB pages", but no page row limit, unlike `detail`'s 1,024 rows. A view reads one page
per leaf, so a long-text leaf such as `link_text` or `url` can return a page of 64 KB of encoded
values to show a handful of rows.

**Fix:**
- Set `data_page_row_count_limit` (512–1,024 rows), with `write_batch_size` no larger, on
  `occurrences` as on `detail`.
- Give the canary a **bytes-per-view budget** for `detail` and `occurrences` (for example
  100 KB per view, set from F0), alongside the heap budget the phone decision added.

### 3. `list.parquet` encoding and row groups (low; measured)

On 1,133,195 sorted document filenames (473,728 distinct):

| Encoding | Size |
|---|---:|
| Dictionary (the default) | 3.22 MB |
| `DELTA_BYTE_ARRAY`, no dictionary | **2.54 MB (−21%)** |
| Same, in 65,536-row groups | 2.57 MB |

Settings:
- `filename`: dictionary off, `DELTA_BYTE_ARRAY`. hyparquet decodes it only in V2 data pages,
  which `PARQUET_2_0` writes.
- 65,536-row groups, so the worker decodes `list` incrementally on phones and shows the first
  rows sooner, for 0.03 MB.
- Facets: dictionary on (as specified).

### 4. State the lake's writer settings in the data model (low)

The design says file and row-group sizes come from table properties (design §9), but the data
model, which defines the tables, doesn't list them. Add per table, using standard Iceberg
properties:

| Table | `format-version` | `write.target-file-size-bytes` | Row group | Compression |
|---|---|---|---|---|
| `captures` | 2 | 128 MB | 131,072 rows | zstd(3) |
| `readings` | 2 | 128 MB | 65,536 rows | zstd(3) |
| `filename_readings` | 2 | 128 MB | 65,536 rows | zstd(3) |
| `page_links` | 2 | 128 MB | 131,072 rows | zstd(3) |

All use chunk statistics, no Bloom filters and no sort-order dependence (Basin compaction may
not preserve sort; the model re-sorts). Use format v2, not v3: every reader is iceberg-rust 0.10.1
and nothing needs v3 features (the `iceberg` skill's decision rule). Optionally declare each PK
as Iceberg `identifier-field-ids`. That documents it but isn't enforced; the invariant tests
are the enforcement.

### 5. `captures` and `page_links` are two commits, not one (low)

§2.4 says `page_links` is filled "in the same ingest commit pass". Iceberg has no multi-table
transaction, so this is two commits, and either can land without the other.

**Fix:**
- Make each table's work list independent: receipt keys absent from that table.
- The inputs record already holds both snapshot IDs; add both high-water marks.
- The model treats a lagging `page_links` as missing link context, not as an error.

### 6. Stale `url` references after the `url_state` fix (low)

§4's `url_state.parquet` row still says order `url`, and the ER diagram joins
`URL_STATE ||--|| ENDPOINT : "url"`. Both should be `requested_url`, matching §3.5.

## Checked and fine

- **`captures.sha256` encoding.** I expected parquet-rs's 1 MiB dictionary limit to bloat it
  (3.9M rows over 1.04M bodies). Measured on 2,867,269 rows sorted by URL in 131,072-row
  groups: 49.9 MB with dictionary at a 1 MiB limit, 50.5 MB at 8 MiB, and 48.2 MB plain. ZSTD
  captures the repeats either way, so leave the default.
- **Partitioning.** Identity partitions only where the model filters: `readings` by
  `(parser, parser_version)`, `filename_readings` by `catalog_version`. `captures` and
  `page_links` aren't partitioned. Nothing is over-partitioned.
- **Optimizer gate.** Low query frequency (one model run a day), small tables and tiny daily
  appends (315 KB for `captures`). So, per `iceberg-optimizer`: no sort or z-order compaction,
  no Bloom filters, no manifest-clustering work; Basin bin-pack compaction at 128 MB plus
  expiry (30 days, last 5). M1's 400-append test is the right check on manifest growth.
- **Release files.** `links` has a page-level column index, `detail` has a typed core plus one
  fold with offset indexes and a row limit, footers are under 512 KB, there are no Bloom filters
  and the files are content-only manifests. All consistent with the hyparquet 1.31.2 reads.

## Query-plan sketch (DataFusion 53 through docspec; 4 threads, explicit pool)

| Step | Plan shape | Largest state | Note |
|---|---|---|---|
| Placeholders (bodies at more than 100 URLs) | `COUNT(DISTINCT context_url)` per `sha256`, rewritten to a two-level group-by | about 2.9M (sha, url) pairs, a few hundred MB, spillable | Write it as a nested `GROUP BY` so the rewrite isn't needed |
| `real_files` | `captures` ⋈ `readings[sniff]` on `body_sha` (build: 1.04M × fsb(32) + dict, tens of MB); ⋈ `readings[html]` for HTML rows only | tens of MB | The format coalesce runs before the filter |
| `filenames` | `DISTINCT (sha256, filename, context_url, member_path)` plus a provenance name join | 1.7M rows | — |
| Edges and CC | Group by `body_sha` and by (endpoint, fingerprint), dense IDs, `u32` union-find in memory (C4) | dense-ID assignment of a few hundred MB, then 16 MB of arrays | The node cap refuses giant components |
| `linked_from` | Earliest `page_links` row per `url_key` (aggregate), then join to members on `url_key` | about 1–2M keys; keep `text` off the build side, join on keys, then attach | Needs finding 1's key |
| `url_state` | `DISTINCT (receipt_key, receipt_line)` over 3.9M rows, then `arg_max` per `requested_url` | 2.6M lines, 1.16M groups | Spillable aggregates |
| Release sorts | `list` by (filename, first_captured, document_id), about 0.5M; `occurrences` by (list_row, ordinal), about 4.7M before the rule | — | Rechunk to fixed row counts before writing (C3) |

None of these needs more than about 1–2 GB, so a 5 GiB pool on the 16 GB runner is ample. M2's
throwaway harness should confirm each row of this table and report the hash-join build sizes.

## Owner decisions on this review (2026-10-24)

- **Finding 1, normalize every link.** The join key `url_key` normalizes scheme, `www.`,
  host case, default port, fragment and trailing slash. It also strips query parameters
  **except an allowlist** derived from aggregating every query string in the captured URLs
  (analysis to follow). Identity keeps the exact URL.
- **Finding 2, no per-view byte budget.** The canary does not enforce bytes per view. The
  `occurrences` page row limit stays a recommended layout setting, not a gate.

## Query-string analysis and decision (2026-10-24)

Script: this session's scratchpad `qparams.py` and `qstrip.py`, over successful captured URLs
on Oct 19.

- 13,930 of 1,158,426 captured URLs (1.2%) carry a query string, with dozens of keys across
  22+ hosts.
- **Most parameters change content.** Among URL groups that differ only by one parameter:
  - `download`: 916 groups, all serving different bodies (the Senate `/download/<slug>` landing
    page vs the `?download=1` PDF);
  - `file_id` 19, `id` 9, `docid` 8, `offsetmark` 4, `documentid` 2, and `dbname`, `date`,
    `file`, `newsid`, `url` and `v` 1 each: all different bodies;
  - only `_gl` (Google Analytics linker) served the same body (1 of 1).
- **Scheme and `www.` variants are safe:** 25,287 of 25,355 http/https and `www.` groups served
  identical bytes (99.7%).

**Decision (owner): strip only trackers.** `url_key` drops `utm_*`, `_gl`, `gclid`, `fbclid`,
`mc_cid`, `mc_eid` and `_ga`, sorts the remaining parameters, and keeps every other parameter.
This replaces the earlier "allowlist" wording. A keep-list would need 40+ keys, and any key it
missed would merge different documents. With a strip-list, the worst failure is a missed match.

## What the non-tracker parameters actually are, and two more decisions (2026-10-24)

Sampled from captured URLs (scratchpad `qsamples.py` and `qcats.py`):

| Group | Examples | Captured URLs | Rule |
|---|---|---:|---|
| Document identifiers | `index.cfm?a=Files.Serve&file_id=<GUID>` (House/Senate CMS file servers); GPO `getdoc.cgi?dbname=…&docid=f:….pdf`; `documentsingle.aspx?DocumentID=`; `PRArticle.aspx?NewsID=`; WordPress `?p=`; THOMAS `cpquery?…report=…&start_from=…`; floor `?date=`; `Download.aspx?file=…xml` | about 7,500 (5,517 Files.Serve, 828 getdoc) | keep |
| Representation selectors | Senate `?download=1`, `format=json/xml`, API `limit` | about 1,200 | keep (different files) |
| Wrappers | Proofpoint `urldefense…?u=`, Constant Contact `rs6.net/tn.jsp?…&p=`, `exit.asp?link=`; archive `web.archive.org/web/<ts>[id_]/<url>`, `webharvest.gov/…/<ts>id_/<url>` | 26 redirect wrappers, 620 archive | **unwrap for matching** |
| Page state | congress.gov `q`, `s`, `r`, `overview`; SharePoint `formmode`, `resultindex`; Twitter/X `s` | about 290 | **strip on those hosts** |
| Not documents | YouTube API, Wayback CDX API, HLS `sd`/`rebase`, Senate `/404?notfound=` | the rest | irrelevant (excluded by the real-file rule) |

Links found on archived pages are rewritten into Wayback form, so without unwrapping, recovered
pages can never be matched to files captured at the original address.

**Decisions (owner):**
1. **Unwrap both.** `url_key` sees through the redirect wrappers (Proofpoint `u=` with its `-XX`
   and `_` decoding, Constant Contact `p=`, `exit.asp?link=`) and the archive wrappers (Wayback
   `/web/<ts>[modifier]/<url>`, webharvest `/<collection>/<ts>[modifier]/<url>`) to the inner
   address, then normalizes it.
2. **Ignore page state on known sites.** The same short strip-list as the trackers, scoped by
   host: congress.gov `q`, `s`, `r`, `overview`; SharePoint `formmode`, `resultindex`;
   twitter.com and x.com `s`.

These rules apply to matching only. Identity and stored addresses stay exact. The wrapper and
strip lists live in the E1 SQL beside `page_shaped`, each with a test sample.
