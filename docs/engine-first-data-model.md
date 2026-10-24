# Engine-first data model

Status: proposed, revision 3, 2026-10-24. The column-level companion to
`docs/engine-first-architecture.md` (cited as "design §n"). It starts from the CS300
reviewer's sketch (`docs/reviews/2026-10-24-design-review/cs300-data-model.md`), applies the
Iceberg/Parquet reviewer's two reviews of it (`iceberg-parquet-data-model-review.md`,
`iceberg-parquet-data-model-final-review.md`), and applies the owner's decisions through
Oct 24. Sizes are measured on the Oct 19 snapshot unless
marked *est.*

Conventions: Arrow types; `fsb(n)` is `fixed_size_binary(n)`; `dict` is a
dictionary-encoded string; `ts` is `timestamp[us, UTC]`. "PK" is the uniqueness a test
asserts. A fold is `List<Struct<field: dict, value: string>>`, one value per element, with
the field repeated for multi-valued facts.

## 1. Raw log

### 1.1 Body object

| Item | Value |
|---|---|
| Key | `bodies/sha256/<aa>/<sha>` for new writes. Older: `…/<sha>.gz` (every older body, 1.04M) and `…/<sha>.pdf` (the one-time uncompressed copies of older PDFs: 261,055 objects, about 403 GB). |
| Stored bytes | Original bytes, gzip-compressed when the media type compresses (HTML, XML, JSON, text), as-is otherwise. |
| HTTP metadata | `Content-Type` is the original media type; `Content-Encoding: gzip` when compressed; `ETag` is the MD5 of the stored bytes (single PUT only). Older `.gz` objects carry `Content-Type: application/gzip` and no encoding. |
| Custom metadata | None: identity is the key, integrity is the ETag. |
| Write | One create-only PUT (`If-None-Match: *`) with `Content-MD5`. A 412 means it exists. |
| Size | 1,036,256 bodies, 0.70 TB stored; largest 1.19 GB; none above 5 GB. |

### 1.2 Receipt line

One file per run, `receipts/<family>/<write-date>/<run>.jsonl.gz`, one JSON object per fetch
attempt or recovery import. Today's lines are 6–9 KB of plain JSON, mostly provider metadata
and duplicated header lists. The target line keeps the fields below, about 1 KB.

**Every line**

| Field | Type | Meaning |
|---|---|---|
| `run_id` | string | Writer run. Older lines carry it as `source_file`. Defines "the Sept 29 import run" for date labels. |
| `mode` | `fetch` \| `retained_import` | A real fetch, or recovered content imported for another link. |
| `family` | string | Source family (21 today). |
| `requested_url`, `url` | string | Requested and final URL. |
| `retrieved_at` | RFC 3339 | Fetch time. For imports, the recovered copy's own original time, so imports never feed capture-date labels. |
| `http_status` | int or null | Synthetic 200 for imports. |
| `outcome` | `stored` \| `unchanged` \| `failed` \| `retry_later` \| `size_limit` \| `request_failed` | The last two mean incomplete; capture retries them. |
| `complete` | bool | Body fully received. |
| `transport` | string | `direct`, `zyte`, … |
| `response_headers` | object | Allowlisted only: `content-type`, `content-length`, `last-modified`, `etag`, `content-encoding`, `date`, `cache-control`, `accept-ranges`. |
| `redirects` | list of {url, http_status} | — |
| `prior_attempts` | list of {url, retrieved_at, transport, http_status, sha256} | Earlier tries in the same run. |
| `links` | list of {url, basis, tag, text, attributes, source_xpath} | Links found in this body; they feed `page_links` (2.4). |
| `source_context.observations` | list of {url, source, pointer} | Why the URL was requested. |
| `writer` | {job, commit, lockfile_digest} | New. |
| `captures[]` | list | One entry per body the line references (median 1, max 22,354). |

**`captures[]` entry**

| Field | Type | Meaning |
|---|---|---|
| `pointer` | JSON path | Where in the record the body sits, such as `["content","body"]` or `["archive_members", i, …]`. |
| `context_url` | string | The URL this body is evidence for: the container's URL for archive members. |
| `member_path` | string or null | Path inside an archive. Older lines carry it as `original_path`. |
| `sha256` | hex | Identity. |
| `bytes` | int | Original size. |
| `media_type` | string or null | The server's claim; never used to classify. |
| `sniffed_format` | see 2.2 | From the first bytes. New. |
| `stored_md5`, `stored_bytes` | hex, int | Only on the line that stored the body. |
| `fidelity` | `exact-bytes` \| `saved-text` \| `saved-record` \| `retained-file` | How faithful the stored bytes are. |

**Recovery imports only** (`mode = retained_import`)

| Field | Type | Meaning |
|---|---|---|
| `publisher_requested` | bool | Always false. |
| `recovery_evidence.original_url` | string | The link this content recovers. |
| `recovery_evidence.imported_at` | RFC 3339 | — |
| `recovery_evidence.match_basis` | string | Such as `user_accepted_url_variant`. |
| `recovery_evidence.acquisition.{prior_access_category, match, source, recovered_url, section_link, evidence_sha256, observed_capture_timestamp}` | mixed | `prior_access_category` decides the display kind (3.6). |

**Dropped from new lines:** `download_state` and `preserve_download_state` (the old raw
index's row); full provider metadata and header copies; `response_header_items`; per-capture
copies of `retrieved_at`, `http_status` and `family`; local file paths in import lines.

### 1.3 Provenance records

`provenance/<kind>/<ts>.jsonl`, append-only; a correction is a new record that supersedes
an old one by `id`.

| Kind | Fields | Read by |
|---|---|---|
| `recoveries` (from `accepted.json`) | `id`, `original_url`, `recovered_url`, `body_sha256`, `kind`, `match_basis`, `evidence_sha256`, `identity_note`, `decided_by`, `decided_at`, `supersedes` | `recoveries` |
| `url_variants` | `id`, `canonical_url`, `variant_url`, `basis`, `decided_at`, `supersedes` | endpoint canonicalization |
| `reviews` | `id`, `target` (`link_key` or `document_id`), `verdict` (not_a_document, duplicate_of, title_override, kind_override, hide), `value`, `note`, `reviewer`, `decided_at`, `supersedes` | `reviews` |
| `verification` | `key`, `size`, `etag`, `sha256_verified`, `checked_at`, `job` | the weekly check |

## 2. Lake

Iceberg tables in Basin Catalog, append-only (design §5).

**Writer settings.** Every table uses Iceberg format version 2 (every reader is
iceberg-rust 0.10.1), a 128 MB target file size, zstd level 3, chunk statistics and no
Bloom filters. Row groups hold 131,072 rows for `captures` and `page_links`, and 65,536 for
`readings` and `filename_readings`. Nothing depends on sort order, because Basin compaction
may not keep it. The primary keys below can be declared as identifier fields, for
documentation only.

### 2.1 `captures`: one row per capture entry, and one per line without a body

| Column | Type | Notes |
|---|---|---|
| `receipt_key` | dict | — |
| `receipt_line` | int32 | — |
| `capture_index` | int32 | Position in `captures[]` (up to 22,354 today). A line whose `captures[]` is empty yields one line-only row with index 0 and a null `sha256`: 1,041,863 of 2,596,054 lines. |
| `pointer` | string | Informative. |
| `run_id` | dict | — |
| `family`, `mode`, `transport`, `outcome`, `fidelity` | dict | — |
| `publisher_requested`, `complete` | bool | — |
| `requested_url`, `url`, `context_url` | string | — |
| `member_path` | string, nullable | The **endpoint** is `(context_url, member_path)`. |
| `retrieved_at` | ts, nullable | Null for about 1.0M older rows. |
| `http_status` | int16, nullable | — |
| `sha256` | fsb(32), nullable | — |
| `bytes` | int64 | — |
| `media_type` | dict | — |
| `sniffed_format` | dict, nullable | Null on older rows; their format comes from `readings` parser `sniff`. |
| `stored_md5` | fsb(16), nullable | Creating line only. |
| `stored_bytes` | int64, nullable | — |
| `recovery_category`, `original_url`, `match_basis`, `imported_at`, `observed_capture_ts` | dict, string, dict, ts, ts | Import rows only. |
| `h_content_type`, `h_last_modified`, `h_etag`, `h_content_length` | dict, string, string, int64 | The header allowlist as columns. |

- **PK:** `(receipt_key, receipt_line, capture_index)`.
- **Line fields on every row:** `requested_url`, `retrieved_at`, `http_status`, `outcome`
  and `mode` come from the line, so every attempt keeps its status. Today's index stores
  bodiless lines with a null status; the backfill from receipts restores them.
- No `body_key` (derivable) and no `stored_sha256` (replaced by MD5).
- Not partitioned; sorted within a commit by `(url, retrieved_at)`.
- **Work list:** receipt keys not yet ingested, listed from date-shaped prefixes.
- **Size:** 157 MB compact; 315 KB on a normal day.

### 2.2 `readings`: one row per `(body, parser, parser_version)`

| Column | Type | Notes |
|---|---|---|
| `body_sha` | fsb(32) | — |
| `parser` | dict | `sniff`, `html`, `xml`, `json`, `fingerprint`; later `pdf_text` (2.5). |
| `parser_version` | dict | — |
| `status`, `error_type` | dict | — |
| `format` | dict | `pdf`, `zip`, `xml`, `html`, `json`, `vtt`, `m3u8`, `docx`, `doc`, `text`, `image`, `warc`, `other`, `empty`. |
| `record_role` | dict, nullable | `document`, `source_record` (metadata XML such as MODS, PREMIS, meeting and witness records), `caption`, `playlist`, `api`, `error_response`. |
| `title`, `heading` | string, nullable | HTML `<title>` and first heading, for the error-sign check. |
| `text_bytes` | int32, nullable | Visible-text size: the "tiny body" signal. |
| `error_signals` | list<dict> | Generic error words found. |
| `fingerprint` | fsb(32), nullable | Normalized-text digest; for a ZIP, the digest of its sorted member hashes. |
| `fields` | fold | Everything else. |

- **PK:** `(body_sha, parser, parser_version)`; partitioned by `(parser, parser_version)`;
  sorted by `body_sha`.
- **`sniff`** runs once over every older body: one ranged read of the first bytes,
  decompressing the start of a `.gz`. That is about 1.04M ranged GETs (about $0.37) and a few
  GB, under an hour. New bodies are sniffed by the fetcher.
- **`fingerprint`** scope: bodies at endpoints with two or more distinct complete real files.
  Today that is 148 endpoints, 297 bodies and 1.38 GB. For a PDF candidate it extracts the
  text (owner decision), so re-packaged PDFs such as BILLS-112hr1063ih merge without the
  deferred every-PDF pass.
- **Size:** today's 491,710 rows fold to 16.5 MB.

### 2.3 `filename_readings`: one row per `(filename, source_url, catalog_version)`

| Column | Type | Notes |
|---|---|---|
| `filename` | string | Basename or recovered name (32,574 differ from the URL's last segment). |
| `source_url` | string | Exact URL (the catalog qualifies 71 mirror URLs). |
| `catalog_version` | dict | Covers every vocabulary passed in. |
| `valid` | bool | Strict convention parse succeeded. |
| `document_kind`, `document_family`, `committee_code` | dict | Facets `list` shows. |
| `congress` | int16 | — |
| `date_token`, `measure_type`, `measure_number` | string, dict, string | — |
| `fields` | fold | The rest (about 106 field names). |

- **PK:** `(filename, source_url, catalog_version)`; partitioned by `catalog_version`.
- **Work list:** `(filename, source_url)` pairs in `captures` with no row for the current
  version (1,392,681 pairs today).
- **Size:** *est.* 32 MB per catalog version.

### 2.4 `page_links`: one row per link found in a fetched body

| Column | Type | Notes |
|---|---|---|
| `receipt_key`, `receipt_line`, `link_index` | dict, int32, int32 | PK. |
| `parent_url` | string | The page the link sits on. |
| `parent_sha` | fsb(32) | The page body. |
| `retrieved_at` | ts, nullable | When the page was fetched. |
| `child_url` | string | The linked URL. |
| `basis`, `tag` | dict | How the link was found. |
| `text` | string | The link's label, such as "Witness testimony". |
| `doc_type`, `add_date`, `publish_date` | dict, string, string | From the link's attributes where the page gives them. |

- Filled from receipts' `links[]` (owner decision: show link context).
- **Work list:** receipt keys not yet in `page_links`, its own list and its own commit;
  Iceberg has no multi-table transaction. A `page_links` that lags `captures` means
  missing link context, not an error. Both tables' high-water marks go in the inputs
  record.
- **Size:** *est.* 3–5M rows, 60–120 MB.

### 2.5 `pdf_text` (deferred)

`body_sha` fsb(32), `parser_version` dict, `page_count` int32, `text_fingerprint` fsb(32),
`text` large_string. PK `(body_sha, parser_version)`. One read of about 403 GB when the owner
schedules full-text extraction. *Est.* 1–5 GB compressed. Keep its text off hash-join build
sides. Fingerprint candidates don't wait for it: the `fingerprint` parser reads their PDF
text already (2.2).

## 3. Model outputs

One SQL plan over `captures c`, `readings r`, `filename_readings f`, `page_links l` and
provenance `p`. The logical body key is the string `bodies/sha256/<aa>/<sha>.gz`.

### 3.0 `url_key`: the normalized URL every link join uses

```
url_key(url) := lowercase scheme and host; drop "www.", the default port, the fragment
                and a trailing slash; keep the path's case; drop known tracker
                parameters (utm_*, _gl, gclid, fbclid, mc_cid, mc_eid, _ga); sort the
                remaining parameters and keep them all
```

- **Every link join uses it** (owner decision): `page_links.child_url` to member URLs,
  recoveries' original links to source files, and endpoint matching. On the Oct 19 data,
  64,860 of 1,158,426 captured URLs (5.6%) sit in groups that differ only by scheme,
  `www.`, case or a trailing slash, such as both `http://` and `https://docs.house.gov`.
- **Identity keeps the exact URL:** `source_id`, `requested_url` and `url_state` never use
  `url_key`.
- **Only trackers are stripped** (owner decision, from an aggregate of every captured
  query string). 13,930 captured URLs (1.2%) carry a query string, with dozens of keys
  across 22+ hosts. Where two URLs differ by one parameter, that parameter almost always
  changes the body: `download` in 916 of 916 groups (a Senate landing page against the
  `?download=1` PDF), `file_id`, `id`, `docid` and the rest in every case, and only `_gl`
  ever matched. A keep-list would need 40+ keys and would merge different documents for
  any key it missed; a strip-list can at worst miss a match. The tracker list is SQL,
  computed in the model rather than stored, so changing it rewrites nothing in the lake.
- **The rest of the normalization holds up:** 25,287 of 25,355 groups that differ only by
  scheme or `www.` (99.7%) served identical bytes.
- Provenance `url_variants` still adds accepted variants beyond what normalization
  catches.

### 3.1 `real_files` (a CTE)

```
format      := coalesce(c.sniffed_format, r[sniff].format)
record_role := from format and the reading: vtt → caption; m3u8 → playlist;
               API-shaped JSON → api; MODS/PREMIS/meeting/witness XML roots → source_record;
               error-like HTML → error_response; everything else → document

real_files  := rows of c where
    mode = 'fetch' and complete and outcome in ('stored', 'unchanged')
    and http_status between 200 and 299
    and sha256 is not null and bytes > 0
    and sha256 not in placeholders                    -- bodies seen at more than 100 URLs
    and record_role = 'document'
    and (format <> 'html' or (page_shaped(url) and not error_signs(r)))
```

Every condition is joined by `and`, so no HTML row skips the fetch, completeness, status or
size checks.

- Any content format counts (owner decision): PDF, ZIP, document XML, web pages, Word,
  web archives, images, text and others. Only the record roles above, error and landing
  pages, empty bodies and placeholders are excluded.
- `page_shaped(url)` is an exact list of regular expressions in the SQL. With only `.pdf`,
  `.zip`, `.doc`, `.docx`, `.xml`, `/download/`, `download=1` and `file_id=`, 16,775 HTML
  bodies are file-shaped; a broader list (adding `/files/`, `/uploadedfiles/`,
  `/media/doc/` and more extensions) gives 44,047. E1 starts from the broader list,
  samples the roughly 27k bodies between the two, and records the final count.
- `error_signs` := `text_bytes < 2048`, a generic error word in `title` or `heading`, or a
  placeholder body.

### 3.2 `filenames`: one row per source file

| Column | Type | Derivation |
|---|---|---|
| `source_id` | fsb(32) | `sha256(logical body key, filename, source_url)`, today's exact inputs |
| `body_sha` | fsb(32), nullable | — |
| `filename` | string | Recovered name if provenance says so, else the URL's last segment, else the member basename |
| `source_url`, `member_path` | string | The endpoint |
| `record_role` | dict | As in 3.1 |
| `is_real_file` | bool | `body_sha` in `real_files` |
| `first_fetched`, `last_fetched` | ts, nullable | Over `mode = fetch` rows only |
| `first_run` | dict | `run_id` of the earliest row |

1,683,430 source files today.

### 3.3 Edges and `documents`

```
same_body    := source files with the same body, where the body is a real file (web pages
                included: the same real page at several addresses is one document)
same_text    := source files at the same endpoint whose real files have equal fingerprints
components   := ConnectedComponents(nodes = source files, edges = same_body ∪ same_text)
listed       := components with at least one real file or at least one recovery
document_id  := sha256(sorted logical body keys of the component's real files),
                or sha256(sorted source_ids) when it has none
saved_file   := the component's real file ordered by first_fetched desc nulls last, then
                body_sha; with no fetch dates at all, the body hash decides
first_captured := min(first_fetched) over its real files
last_captured  := max(last_fetched) over its real files
date_kind    := 'captured'   if the saved file has a fetch date from a non-import run
                'import_day' if its only rows come from the Sept 29 import run
                'unknown'    otherwise
```

- Only `listed` components become explorer documents: *est.* about 0.5M. Captions,
  metadata records, playlists, API bodies and links that never yielded a real file stay in
  the lake and feed `url_state`.
- Import day is defined by run, not by date: 102,427 saved files carry only the import
  run's timestamp.

**Columns:** `document_id` fsb(32), `list_row` int32, `filename`, `saved_body` fsb(32)
nullable, `saved_media_type` dict, `saved_key` string (physical key: `<sha>`, `<sha>.gz` or
`<sha>.pdf`), `saved_kind` dict (`original` or `recovery`), `first_captured` and
`last_captured` date32, `date_kind` dict, `n_members` int32, and the facets from the saved
file's filename reading.

### 3.4 `members`

`(document_id, source_id)`, each fsb(32). Every source file of a listed document appears
exactly once.

### 3.5 `url_state`: one row per requested URL

`requested_url` string, `attempts` int32, `last_attempt` ts, `last_status` int16,
`last_outcome` dict, `next_attempt_at` ts, `links_scanned` bool.
- Keyed by `requested_url`, the fetcher's own key.
- Aggregated over distinct `(receipt_key, receipt_line)`, so an attempt counts once however
  many bodies its line references.
- The latest `mode = fetch` attempt wins, in the total order `(retrieved_at nulls first,
  receipt_key, receipt_line)`. Retryable
outcomes (`retry_later`, `size_limit`, `request_failed`) are due now; a 2xx waits the
family's recheck interval. No body hash: the 412 tells capture whether a body is new.
1,158,426 rows, *est.* 10 MB.

### 3.6 `recoveries`: one row per recovery

`document_id`, `original_url`, `kind` dict, `body_sha` fsb(32), `saved_key`,
`recovered_url`, `match_basis`, `evidence_sha256`, `identity_note`, `imported_at`,
`observed_capture_ts`, `decision_id`. Joined from `captures` import rows and provenance
`recoveries` on `(original_url, body_sha256)`.

| `prior_access_category` | Display kind | Oct 15 run |
|---|---|---|
| `recovered_document` | Recovered copy | 5,154 |
| `requested_content_in_official_hearing` | Excerpt from the official hearing record | 341 |
| Any official-substitute category (updated revision, introduced-bill counterpart, recorded votes, official report, complete statement, alternate amendment) | The named official substitute | 92 |

An unmapped category fails the build, so a new kind is never shown unlabeled.

### 3.7 `reviews`

Provenance `reviews` resolved to a `document_id` through `links` or directly; the latest
record per `id` wins.

## 4. Release files

`list` order is `(filename, first_captured nulls last, document_id)`, unique. Shared writer
settings: Parquet 2.0 pages, ZSTD, fixed rows per row group, chunk statistics, footer under
512 KB, no Bloom filters. Sizes are *est.* at about 0.5M listed documents, from measurements
at 1.24M.

| File | Columns | Order | Writer settings | Size |
|---|---|---|---|---|
| `list.parquet` | `filename`, `document_kind`, `document_family`, `committee_code`, `congress`, `format`, `first_captured` (date32, dictionary), `date_kind`, `saved_kind`. No ID. | list order | `filename` with dictionary off and `DELTA_BYTE_ARRAY` encoding (2.54 MB against 3.22 MB with a dictionary, measured on 1.13M sorted filenames); facets keep dictionaries; 65,536-row groups so a phone can decode as it goes; no page index | about 1.5 MB |
| `detail.parquet` | typed core: `document_id` fsb(32), `occ_start` int32, `occ_len` int32, `recoveries` List<Struct<kind dict, key string, imported_at date32>>; plus one fold of the sparse facts: `link_key`, `source_url`, `saved_key`, `saved_media_type`, `saved_kind`, `first_captured`, `last_captured`, `date_kind`, `member_count`, the saved file's readings (`r.*`) and filename reading (`f.*`) | list order | offset index on every leaf; 64 KB pages, write batches of 1,024 rows | 30–40 MB (74 MB measured at 1.24M for the fold alone); offset index about 100 KB; about 8 concurrent page reads per view |
| `links.parquet` | `link_key` fsb(8), `list_row` int32 | `link_key` | offset index and column index (page-level statistics) on `link_key`, about 25 KB together and read once per session, so hyparquet's `$eq` lookup skips to one page; 16 KB pages; one row group | 5–7 MB |
| `occurrences.parquet` | `list_row`, `ordinal`, `url`, `member_path`, `filename`, `first_fetched`, `last_fetched`, `outcome`, `is_saved`, `linked_from` (parent URL), `link_text`, `doc_type`, `add_date` | `(list_row, ordinal)` | offset index on every column; 64 KB pages with a page row limit of 512–1,024 and the write batch no larger | *est.* 15–25 MB with link context |
| `url_state.parquet` | 3.5 | `requested_url` | defaults | 10 MB |
| `manifest.json` | `schema_version`; `files[]` {name, sha256, md5, size, rows, row_range, shard}; `facet_counts`; `release_id` | — | deterministic, content only | 5–20 KB |
| `inputs/<input_digest>.json` | receipt-keys digest, row counts per parser version and catalog version, provenance digest, versions, snapshot IDs, run | — | one per input identity | about 2 KB |

- **`link_key`:** the first 8 bytes of a real file's SHA-256, one key per real file of
  every listed document. A document with no real file (recovery only) uses its
  `document_id`'s prefix. Recovery bodies are never keys.
- **`linked_from`:** for each member source file, its earliest `page_links` row matched on
  `url_key`, by `(retrieved_at, parent_url)`, so "where each copy was seen" names the page
  and the label.
- **No per-view byte budget** (owner decision): the canary enforces the heap budget only;
  page sizes and row limits are layout settings, not gates.
- A day with changes uploads about 70 MB.

## 5. Relationships and invariants

```mermaid
erDiagram
  BODY ||--o{ CAPTURE : "sha256"
  RECEIPT_LINE ||--|{ CAPTURE : "captures[]"
  RECEIPT_LINE ||--o{ PAGE_LINK : "links[]"
  CAPTURE }o--|| ENDPOINT : "(context_url, member_path)"
  PAGE_LINK }o--|| ENDPOINT : "child_url"
  BODY ||--o{ READING : "body_sha, parser, version"
  ENDPOINT ||--o{ FILENAME_READING : "(filename, source_url, catalog)"
  CAPTURE }o--|| SOURCE_FILE : "(body, filename, url, member)"
  SOURCE_FILE ||--o| MEMBER : "source_id"
  DOCUMENT ||--|{ MEMBER : "document_id"
  DOCUMENT ||--o| BODY : "saved_body"
  DOCUMENT ||--|| LIST_ROW : "list_row"
  LIST_ROW ||--|| DETAIL_ROW : "same order"
  LIST_ROW ||--o{ OCCURRENCE : "occ_range"
  LIST_ROW ||--|{ LINK : "list_row"
  BODY ||--o{ LINK : "link_key = sha256[0:8]"
  PROVENANCE_RECOVERY }o--|| DOCUMENT : "original_url"
  PROVENANCE_REVIEW }o--|| DOCUMENT : "link_key or document_id"
  URL_STATE ||--|{ CAPTURE : "requested_url"
  PDF_TEXT ||--|| BODY : "deferred"
```

**Keys between layers:**
- raw → lake: `(receipt_key, receipt_line, capture_index)` and `(receipt_key, receipt_line,
  link_index)`;
- body ↔ everything: `sha256`, binary;
- lake → model: `sha256` for readings, `(filename, source_url)` for filename readings,
  `(context_url, member_path)` for endpoints;
- model → release: `list_row`;
- public → release: `link_key`;
- release → raw: `saved_key` and occurrence URLs.

**Invariants a test asserts**

Raw and lake:
1. Every lake PK is unique. `captures` and `page_links` rebuilt from all receipts equal the
   appended tables.
2. Every `sha256` in `captures` has a body object, and every body's size and ETag equal its
   creating line's `stored_bytes` and `stored_md5`.
3. New receipt keys are date-shaped; every `stored` line carries `stored_md5`; every line
   carries `sniffed_format` and `writer`.
4. A parser version is complete when its work list is empty; the model reads only complete
   versions.
5. Every real file has a `format` and a `record_role`; every HTML real file has `title`,
   `heading` and `text_bytes` for the current HTML parser version.

Model:
6. Every source file of a listed document is in exactly one document; every listed
   document has at least one member, and at least one real file or recovery.
7. Every real body belongs to exactly one document, web pages included.
8. No document's body set contains a non-2xx body, an incomplete body, a recovery import, a
   placeholder, an empty body, or a body whose `record_role` isn't `document`.
9. `document_id` and `source_id` recompute from today's formulas (golden vectors).
10. `saved_body` is in the body set and is its newest real file. `first_captured` ≤
    `last_captured`. `date_kind = 'import_day'` only when every row of the saved body comes
    from the import run; recovery imports never set a date.
11. `url_state` has one row per URL and no import rows.
12. Every recovery resolves to a listed document or is reported as orphaned; every recovery
    has a display kind; no recovery body is a saved file or a link key.

Release:
13. `rows(list) = rows(detail)`; every `list_row` in `links` and `occurrences` is below
    `rows(list)`.
14. `list` is sorted by `(filename, first_captured nulls last, document_id)` and unique.
15. The `occ_range`s partition `occurrences` exactly.
16. Every `link_key` resolves to one row, and keys are unique (the export refuses
    collisions).
17. Manifest digests equal the uploaded objects'; `release_id = sha256(file list,
    schema_version)`; facet counts equal counts over `list`; an inputs record exists;
    `url_state` decodes.
18. A 404 on a release file makes the reader re-read the pointer.
