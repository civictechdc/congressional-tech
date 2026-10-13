# Static filename viewer

The public `/filenames/` page reads Parquet in a Web Worker using Hyparquet.
It needs no Python service and receives no R2 credentials. It shares the reviewed
HTML and presentation code with the optional local viewer.

The Pages build downloads `indexes/catalog.json` from `congressional-tech-raw`,
then the exact immutable documents and filenames pair selected by that manifest.
It verifies both SHA-256 hashes, byte sizes, row counts, and catalog IDs. The
publication script repacks those files with larger row groups and verifies every
value and the full Arrow schema after rewriting. No catalog data is committed to
Git. The original R2 objects remain unchanged.

The browser publication contains:

- Complete source and grouped-document Parquet files, retaining all columns.
- A filename-sorted Parquet table for displaying result pages.
- A three-column document summary for details. The group's source ID comes from
  its preferred source, whose identity the catalog validates during publication.
- A shared observation dictionary and per-source reference lists, stored as
  independently Brotli-compressed JSON blocks. Each compressed part expands to
  at most 1 MiB. Identical observations share storage; the reader restores every
  original observation, null field, duplicate, and ordering. Oversized individual
  values span multiple parts. The publisher reconstructs and compares all source
  observation lists against Arrow before writing the manifest.
- Small binary arrays mapping source rows to groups, preferred sources, original
  document rows, and group status. Integers are unsigned 32-bit little-endian.
  Status bits are saved response (1), document scope (2), missing kind (4), missing
  family (8), and API-only group (16).
- 256 source-ID prefix files. Each entry contains a 32-byte SHA-256 source ID and
  its four-byte little-endian row position, allowing stable review links without
  loading all IDs on startup.

Search checks every source URL in a group. Field and facet filters must match the
same source row; missing classification filters check the grouped document.
“No saved responses” checks all group members even when another filter matches
only an unfetched alias. Choose “All records” to include API/source references.
Nested source observations retain their original page, title, and link grouping.

Recorded links also carry their upstream hearing/page relationships. Receipt
`publisher_occurrences` are interpreted as individual page-to-URL observations;
descendants retain those observations as `linked_ancestor` with `linked_page`
evidence. Original labels and receipt locators remain paired. An inherited
relationship does not transfer another document's type, witness, or saved body,
and it does not merge the linked files into one document group. Links may arrive
in either order; duplicate observations and cycles reach a fixed point.
Tentative matches, such as similar filenames, do not establish transitive
relationships. Redirect cycles retain one copy of each inherited observation.
Sitewide RSS/Atom feeds and sitemaps remain direct references; they do not
connect unrelated events through their shared navigation links.

The next catalog update automatically backfills older recurring receipts once,
then records `source_lineage_version` in the Parquet metadata. This replay uses
retained receipt metadata and existing source observations. The viewer shows a
hearing-to-page-to-file chain when those individual URL pairings establish a
complete path; ambiguous flat URL lists remain separate source notes.

Catalog information loads just the manifest. Ordinary browsing loads flags and
preferred-source rows; searching loads group mappings, and opening a detail
loads document-row mappings and builds group membership lists. Concurrent
queries share pending navigation loads without sharing cancellation.

Queries load only needed columns over validated HTTP byte ranges. Detail reads
prefetch only requested columns and decode ordinary source metadata eight
columns at a time. Nested observations use the bounded JSON blocks, so selecting
one row does not expand neighboring sources' observation lists. The reader still
returns all source fields for technical review and copied JSON. Nested-observation search streams row
groups, and compressed bytes and ordinary query columns have bounded caches.
The UI cancels superseded searches and details. A mismatched snapshot link is
rejected rather than silently showing a different record.

Saved-file status and content findings describe the published catalog. The
static page does not retrieve private R2 bodies, recheck file hashes, inspect PDF
pages, or rerun house-naming. Those operations remain in the local Python viewer;
the public page labels its evidence accordingly and links to the publisher copy.
Receipt files, archived bodies, and credentials are not published by this build.

## Build and check

Install the existing Python archive dependencies and the site npm dependencies.
To publish from an already downloaded catalog:

```sh
python apps/site/scripts/publish-filename-viewer.py --source .cache/filename-viewer-r2
npm run build --workspace apps/site
npm run preview --workspace apps/site -- --port 8791
```

For an authenticated build, use `--fetch` with `CLOUDFLARE_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY` set in the build environment.
The checked-in Pages workflow already uses repository secrets for this step.
Do not place those values in frontend configuration.

```sh
npm run test:explorer --workspace apps/site
npm run check:explorer-types --workspace apps/site
npx --workspace apps/site --no-install astro check
pytest tests/test_document_filename_viewer.py tests/test_published_hearing_cover.py
```

The browser tests generate actual Parquet, compare static query results with the
Python catalog, verify complete detail records, test cancellation and invalid
byte ranges, and exercise the shared metadata panel. `PYTHON` can select the
fixture interpreter; `EXPLORER_PYTHON` selects the existing Explorer interpreter.

Pages deploys after site changes, a manual dispatch, or a successful non-push
archive workflow on `main`. Every build rereads the selected R2 snapshot and
checks the total publication against the existing one-billion-byte budget.
Publication manifest version 2 uses a `viewer-v2` directory beneath the R2
generation, separating its assets from older viewer layouts. Build into a clean
output directory when switching layouts; retaining old generated assets counts
against the size budget. Snapshots show their publication date and catalog identity. An already open tab
keeps its selected snapshot; reload after an update if its files are unavailable.
