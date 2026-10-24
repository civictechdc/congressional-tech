# Review of the CS300 data-model sketch

Reviewed: `cs300-data-model.md`, with `cs300-rereview-rev5.md` (design rev 5 at `69080fac`). The
lens is the same as `iceberg-parquet-review.md`: Iceberg, Parquet, query plans and the browser
reader, plus consistency with the owner's decisions. Checks ran read-only in DuckDB from the
project venv on the Oct 19 inputs.

## Verdict

This is a strong sketch, and the first time the whole model is written down field by field. It
fixes real errors: the `captures` key, archive-member endpoints, record roles, the import-day
definition by run, and dropping the hash from `url_state`. Its invariants list is the right
acceptance test.

Four problems remain. One makes the export refuse every release as specified. Two are
contradictions between owner decisions that need the owner. One would mis-schedule retries.

## Findings

### 1. HTML link keys contradict each other: the export would refuse every release (major)

Invariant 7 lets "an HTML real body belong to several" documents, because HTML connects nothing
(§3.3 `same_body … format <> 'html'`). Invariant 16 requires every real body to have a key that
resolves to exactly one row, and the export refuses collisions.

Measured: **265 page-like, successful HTML bodies appear at 2–44 URLs** (585 URLs). Each
becomes 2+ documents sharing one body key, so invariant 16 fails on every release.

**Fix (recommended):** let real HTML bodies connect through `same_body` like every other format.
- "HTML connects nothing" dates from revision 4, when HTML bodies were mostly error pages. Now
  error pages, landing pages and placeholders are excluded before edges are built (§3.1).
- Under decision 8 (one document per distinct content), identical bytes are the same content.
- Invariant 7 then reads "every real body belongs to exactly one document".

The alternative, keying HTML documents by a `document_id` prefix, adds a second key rule for no
user benefit.

### 2. `url_state` built from a per-capture table miscounts and can miss failed fetches (major)

§3.5 derives `url_state` by `arg_max` over `captures`, which has one row per capture entry. A
receipt line is one attempt but holds up to 22,354 entries, so counting rows overcounts
`attempts`.

A failed attempt with no body exists only if the line still yields a row. In today's index:
- 1,041,863 of 2,596,054 lines have no body;
- their rows are `metadata` rows with `http_status` NULL;
- so the statuses that drive retry scheduling are missing.

**Fix, keeping one table:**
- Every receipt line yields at least one row: a line-only row (`capture_index = 0`, `sha256`
  null) when `captures[]` is empty.
- Line fields (`requested_url`, `retrieved_at`, `http_status`, `outcome`, `mode`) are populated
  on every row. The backfill from receipts restores the statuses the old index dropped.
- `url_state` aggregates over `DISTINCT (receipt_key, receipt_line)` and is keyed by
  `requested_url`, the fetcher's queue key (`raw_archive.record_prepared` keys state by
  `requested_url`), not `url` or `context_url`.
- The ordering is total: `(retrieved_at NULLS FIRST, receipt_key, receipt_line)`, because about
  1.0M legacy rows have no `retrieved_at`.

### 3. Decisions 8 and 14 conflict for PDFs (major; owner call)

Decision 8 merges same-text files at one endpoint; the owner's example was a PDF (BILLS-112hr1063ih,
identical text, re-packaged by GPO). Decision 14 deferred PDF parsing. §2.5 resolves the
conflict silently: until `pdf_text` exists, PDFs get no fingerprint, so same-endpoint PDF pairs
(75 endpoints today) stay separate documents. The owner's own example would split in two.

The fingerprint parser's scope is only 297 bodies (1.38 GB, by the sketch's own count). Running
PDF text extraction for those candidates costs seconds and doesn't touch the deferred
full-corpus pass. **Recommendation:** the fingerprint parser includes PDF text for candidates
only. Decision 14 still governs the corpus.

### 4. "A document needs a real file" vs recoveries on dead links (major; owner call)

The third pass (item 1) recommends that a document needs at least one real file. Caption
segments (453,751), metadata records (98,205), playlists and API bodies would then feed only
`url_state` and occurrences. That brings `list` from 1.24M rows to about 0.5M.

Agreed, with one exception. Decision 10 shows every recovery on the dead link it recovers, and
§3.6 attaches recoveries to "the document whose source file has `original_url`". Dead links are
fileless. If fileless rows leave, all 5,587 recoveries become orphans, which invariant 12
reports but nothing shows.

**Rule:** a document needs at least one real file **or** at least one recovery.

### 5. `real_files` pseudo-SQL: `OR` precedence (minor)

```
and format in ('pdf','zip','xml','docx','doc')
    or (format = 'html' and page_shaped(url) and not error_signs(r))
```

Transcribed literally, the `or` lets every HTML row bypass the earlier conditions (`mode`,
`complete`, `http_status`, `bytes > 0`). Parenthesize the format disjunction. The `format not in
('json','m3u8','vtt')` line is then redundant.

### 6. `detail` as one stringly-typed fold (minor)

Folding sparse reading fields into `List<Struct<field, value>>` is right: two leaf chunks, few
requests, a stable schema. The fixed core shouldn't be strings:
- `occ_range` as `"start:len"` must be parsed before the occurrences read;
- recoveries as `"kind|key|imported_at"` break on any `|`;
- `document_id` as 64-char hex contradicts design principle 7 (binary hashes).

**Fix:** typed core columns `document_id fsb(32)`, `occ_start int32`, `occ_len int32` and
`recoveries List<Struct<kind dict, key string, imported_at date32>>`, plus the fold for
everything sparse. The extra leaves are fetched concurrently in the same round trip under
HTTP/2, with fewer bytes.

The 64 KB page and 1,024-row batch choice is fine. It supersedes my earlier ~256-row figure,
given the measured 868 KB offset index at 16 KB pages.

### 7. `links.parquet` needs page-level statistics, not just "statistics" (minor)

Point lookup uses hyparquet's `filter: {link_key: {$eq}}` with `usePageIndex: true`. That needs a
column index on `link_key`, i.e. parquet-rs `EnabledStatistics::Page` for that column. Chunk
statistics plus an offset index can't skip pages. With one row group, 16 KB pages and about 650
pages, the column and offset indexes total roughly 25 KB, read once per session.

### 8. Smaller items

- `capture_index int16`: today's maximum is 22,354, against a ceiling of 32,767. Use `int32`;
  it's free under RLE.
- `last_captured := max(first_fetched)` doesn't match its name. Either rename it ("newest
  version first captured") or use `max(last_fetched)`. Also state null handling for
  `saved_file` (all `first_fetched` null means the tie goes to `body_sha`).
- **The page-shaped regex list.** My 44,047 "file-like" count used a broader list than the
  design's: it added `/files/`, `/uploadedfiles/`, `/media/doc/` and more extensions. The third
  pass's 16,775 uses the design's exact list. The ~27k difference is CMS file routes on
  house.gov sites. Write the broader list into the E1 SQL and sample the delta's titles before
  fixing it.

## What the sketch gets right

- The `captures` key `(receipt_key, receipt_line, capture_index)` (2,596,054 lines vs 3,909,134
  rows).
- Endpoints as `(context_url, member_path)`: the fingerprint scope drops from about 545 GB to
  1.38 GB.
- `record_role` in `readings` and `filenames`, so the document population is defined.
- Import day defined by run (`run_id`), not by date (102,427 vs 82,474).
- Partitioning: `readings` by `(parser, parser_version)`, `filename_readings` by
  `catalog_version`, none for `captures`.
- Typed facet core in `filename_readings`.
- Binary keys throughout the lake.
- No hash in `url_state` (about 10 MB instead of 42.8 MB).
- A content-only `manifest.json`, with input records kept separate.
- Sizes restated at both document counts.
- Trimming new receipt lines: allowlisted headers, no duplicate header copies, no local paths.
- The invariants list (18 checks). Adopt it as the model's test suite, with invariants 7 and
  16 fixed per finding 1.

## Owner decisions on findings 1, 3 and 4 (2026-10-24)

- **Finding 1:** one entry. Identical real HTML bodies connect through `same_body`; a page saved
  at several addresses is one document (memory item 32).
- **Finding 3:** yes. The fingerprint parser reads PDF text for same-endpoint candidates only
  (about 300 bodies, 1.4 GB); the full every-PDF pass stays deferred (memory item 33).
- **Finding 4:** a document needs at least one real file or at least one recovery. That gives
  about 0.5M entries, and dead links with recoveries keep an entry. This matches memory item 29,
  recorded from the parent session.
