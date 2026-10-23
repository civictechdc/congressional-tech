---
id: ct-8od2
status: closed
deps: []
links: []
created: 2026-10-22T18:42:15Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-4t6s
tags: [parquet, r2, catalog, filenames, documents, viewer-publication, schema]
---
# Normalize & slim Canonical Catalog (filenames.parquet, documents.parquet, readings/*.parquet) & Viewer (review/rows): drop 47 duplicate source_* cols, fix 143.6 MB footer bloat, and compact 721 readings files (~500 MB saved)

Physical metadata and raw-data audit of filenames.parquet (1,683,430 rows, 353 root / 406 physical cols, 546.85 MB compressed), documents.parquet (1,241,157 rows, 356 root / 409 physical cols, 541.15 MB compressed), readings/*.parquet (721 files, 53.78 MB), dependency/family_mappings.parquet (397 KB), and review/rows/part-*.parquet (200,000 rows, 117.78 MB compressed) revealed:
1. 143.57 MB of Pure Parquet Footer / Metadata Bloat: filenames.parquet has 1,644 row groups (1,024 rows/RG) x 406 physical columns = 667,464 column chunks -> 81.32 MB footer (14.87% of the entire file!). documents.parquet has 1,213 row groups (1,024 rows/RG) x 409 physical columns = 496,117 column chunks -> 62.25 MB footer (11.50% of the entire file!). In dependency/family_mappings.parquet (256 RGs of 2,048 rows), the footer is 222.9 KB = 56.10% of the entire file!
2. 162.80 MB Compressed in 47 Duplicate Top-Level source_* Columns: All 47 fields inside source_occurrences: list<struct<...>> (115.90 MB compressed in filenames, 116.21 MB in documents) are ALSO materialized as 47 top-level source_* list<string> columns consuming 84.35 MB compressed (224.21 MB uncompressed) in filenames.parquet and 78.45 MB compressed (224.21 MB uncompressed) in documents.parquet.
3. 7x SHA-256 / body_key Duplication in filenames.parquet (185.3 MB compressed): stores body_key (42.69 MB), state_body_key (33.43 MB), sha256 (27.51 MB), state_sha256 (26.90 MB), stored_sha256 (26.86 MB), source_occurrences.source_body_key (14.23 MB), and source_occurrences.source_sha256 (13.68 MB).
4. Extreme Sparse Wide-Table & 'Everything-is-a-list<string>' Anti-Pattern: 74 physical cols in filenames.parquet and 78 in documents.parquet are 100.0% NULL; 277/406 (68.2%) in filenames and 288/409 (70.4%) in documents are >=99% NULL. 346 of 353 root columns are typed as list<element: string> (and all 47 struct fields inside source_occurrences are also list<string>), even though 163 of those columns never have >1 element (max_len <= 1) and represent scalars (http_status, state_status, congress, format, document_kind, source_receipt_line).
5. Small-File Problem in readings/*.parquet: 721 separate Parquet files with median size 91.3 KB (409 files under 100 KB, ~778 rows/file).
6. Viewer Review Export (review/rows/part-*.parquet, 117.78 MB): record_json (45.77 MB compressed / 169.36 MB uncompressed, 38.9% of file) repeats all 19 populated top-level columns + 483 B/row of null-key boilerplate (96.6 MB uncompressed boilerplate alone); canonical_url (13.86 MB compressed) is 100.0% identical to url across all rows; 9 columns are 100.0% NULL.

## Design

1. In packages/viewer_publication/src/viewer_publication/filename_native.py and filename_exports.py, increase Parquet row group size for filenames.parquet, documents.parquet, and family_mappings.parquet from 1,024/2,048 rows to 16,384-32,768 rows (cutting footer size by 16x-32x and saving ~135 MB immediately).
2. Drop the 47 top-level source_* columns that duplicate source_occurrences struct fields (deriving any needed top-level slice on read from source_occurrences or flat occurrences.parquet).
3. Deduplicate body_key / state_body_key / stored_sha256 in filenames.parquet, documents.parquet, and source_occurrences by retaining only the SHA-256 digest + boolean state flags and deriving R2 body keys via physical_body_object_key.
4. Prune the 74-78 all-null columns and convert single-valued list<string> columns (max_len <= 1) to native scalar types (int16, int64, string, bool).
5. Compact the 721 readings/*.parquet shards into 1-2 sorted Parquet files.
6. In review/rows/part-*.parquet, drop record_json (linking to R2 via sha256), drop canonical_url (100% == url), and drop the 9 all-null columns.

## Acceptance Criteria

1. filenames.parquet and documents.parquet footer overhead drops from 143.57 MB to <10 MB.
2. Dropping the 47 duplicate source_* columns, redundant body_key/sha256 copies, and all-null columns reduces filenames.parquet + documents.parquet total compressed size by >=350 MB with zero loss of information.
3. readings/ is compacted from 721 tiny files to 1-2 files.
4. review/rows/part-*.parquet drops from 117.78 MB to ~55 MB with all 19 populated fields preserved as typed columns.

