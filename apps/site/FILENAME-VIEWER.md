# Static filename viewer

The public `/filenames/` page reads Parquet in a Web Worker using Hyparquet.
It needs no Python service and receives no R2 credentials. It shares the reviewed
HTML and presentation code with the optional local viewer.

GitHub Pages serves the interface. Filename-viewer data lives in R2 under
`congressional-tech-raw/viewer-publications/`, served at
`https://congressional-viewer-data.mdeeb.workers.dev/` (also available at
`https://congressional-data.spicygov.ai/`) by the read-only Worker in
`apps/viewer-data`. It accepts only known publication paths and exact saved-body
hashes through GET/HEAD. This route does not serve receipts or source indexes.
The bucket also has direct public object access at
`https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/`, enabled at the owner's request.
That endpoint exposes known object paths, including receipts and indexes; it does
not list the bucket. The viewer uses the existing Worker for production data and
decoded saved copies. Browsers receive no storage credentials.

Catalog alias links use `source_resolved_url` or a recognized URL wrapper only when
the target has one usable retained body. Conflicting destinations and body versions
remain unresolved. The recovery index preserves each literal source URL and is
rebuilt for every publication, including catalogs without manual recoveries.

“Open saved copy” uses the selected source's retained body, preferring an accepted
recovery when available. A group recovery is explicitly labeled as belonging to
another URL. The Worker streams the stored gzip object as its original bytes:
PDFs open in the browser; other formats download without running archived HTML
on the data host. Saved-response flags and saved-copy links exclude failed or incomplete captures,
known error pages, reviewed unusable HTML, and video payloads. Genuine reviewed
HTML and XML playlists remain available. Reviews bind decisions to exact source
URLs and body digests. Identified error pages remain excluded through redirect
aliases. Full source exports retain original evidence.

Saved copies ignore Range requests and return the whole file,
since compressed-storage offsets do not describe decoded-file offsets. This
requires no new data export or per-file publishing step.

The data publisher reads `indexes/catalog.json` from `congressional-tech-raw`,
then the exact immutable documents and filenames pair selected by that manifest.
It verifies both SHA-256 hashes, byte sizes, row counts, and catalog IDs. The
publication script repacks those files with larger row groups and verifies every
value and the full Arrow schema after rewriting. No catalog data is committed to
Git. The original R2 objects remain unchanged.

The publisher uploads a complete dataset to a unique `releases/<id>/` directory
and reads back every uploaded byte to verify its hash. It checks the public
manifest, byte ranges and cross-origin headers before selecting the release.
A conditional write updates `viewer-publications/manifest.json` only if no other
viewer publisher has advanced it, after rechecking the raw catalog selector.
If the raw catalog advances during publication, the previous viewer stays
selected and the next scheduled check publishes the new generation.
`catalogs/<catalog_id>.json` retains old review links. Release files never change.

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
- Direct detail navigation in `detail-navigation.bin`: each source row has four
  unsigned 32-bit little-endian values (group, preferred source row, member
  offset, member count). `detail-members.bin` contains the ordered source rows
  for each group. The browser range-reads 16 bytes and that group's member slice;
  it checks bounds, ordering, and inclusion of the selected/preferred sources.
  The publisher verifies every row and group before declaring both files.
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
preferred-source rows; searching loads group mappings. New publications let
individual details bypass those global arrays through the direct navigation
files. Older publications retain the global-index fallback. Resolved source IDs
have a bounded per-reader cache. Concurrent queries share pending global index
loads without sharing cancellation.

Queries load only needed columns over validated HTTP byte ranges. Detail reads
prefetch only requested columns and decode ordinary source metadata eight
columns at a time. Nested observations use the bounded JSON blocks, so selecting
one row does not expand neighboring sources' observation lists. The reader still
returns all source fields for technical review and copied JSON. Nested-observation search streams row
groups, and compressed bytes and ordinary query columns have bounded caches.
The compact provenance files are deliberate performance indexes over the full
Parquet data. A direct Parquet-Wasm detail reader was reverted after it increased
latency and memory; see the [paired measurements](../../docs/youtube-coverage/research/filename-performance-regression.md).
The publisher verifies every reconstructed observation against the original
Parquet before publication. These indexes preserve all provenance rather than
trading evidence for speed.
The static detail panel displays the file and saved-copy action before loading
source-page provenance. The provenance request also restores canonical redirect
labels for alternate sources; failures leave the file usable and offer a retry.
Deep links finish their initial detail response before starting the result-list
search. Local Python viewers can still return a complete detail in one response.
The UI cancels superseded searches and details. Review links load their retained
snapshot; missing snapshots fail visibly. The browser rechecks the latest pointer
on focus and every minute while visible. A new-data notice offers the latest
snapshot while preserving filters and the stable source ID. It never swaps the
data beneath an open review. Mutable pointers use `no-store`; release files have
immutable cache headers.

Saved-file status and content findings describe the published catalog. The
static page does not recheck file hashes, inspect PDF pages, or rerun house-naming.
Those operations remain in the local Python viewer; the public page labels its
evidence accordingly and links to both the publisher and retained copy. Archive
objects remain in R2 rather than being duplicated into the Pages build.

## Build and check

Install the existing Python archive dependencies and the site npm dependencies.
To publish the currently selected catalog using the existing R2 credentials:

```sh
python apps/site/scripts/publish-viewer-r2.py --report viewer-publication.json
npm run build --workspace apps/site
npm run preview --workspace apps/site -- --port 8791
```

Set `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY`
only in the publisher environment. Pages no longer needs these credentials.
The command skips unchanged catalogs before downloading or repacking anything.
`--prepared <directory>` reuses a verified local viewer publication only if its
source manifest equals the selected R2 catalog. `--archive-only --prepared ...`
retains an older snapshot without changing the current selection.

For local data development, build with
`PUBLIC_FILENAME_MANIFEST_URL=/congressional-tech/data/filenames/manifest.json`
and generate the local files with `publish-filename-viewer.py --source ...`.
Normal local previews use the same R2 publication as the website.
Deploy the file-serving Worker with `npm run deploy --workspace viewer-data`.

```sh
npm run test:explorer --workspace apps/site
npm run check:explorer-types --workspace apps/site
npm test --workspace viewer-data
npx --workspace apps/site --no-install astro check
pytest .github/tests/test_viewer_r2.py .github/tests/test_filename_publication.py .github/tests/test_raw_source_workflow.py
```

The browser tests generate actual Parquet, compare static query results with the
Python catalog, verify complete detail records, test cancellation and invalid
byte ranges, and exercise the shared metadata panel. `PYTHON` can select the
fixture interpreter; `EXPLORER_PYTHON` selects the existing Explorer interpreter.

Pages deploys interface changes independently. `publish-filename-viewer.yml`
publishes after successful non-push archive workflows and checks every 30 minutes
for catalogs selected by local recovery runs. It writes only the viewer prefix
and has a separate publication lock. It never runs acquisition or catalog updates.

Future GitHub capture batches update the catalog in a dependent job only after
capture verification and finalization succeed. That job retains the existing
`raw-source-mirror` workflow lock. Update/rebuild modes already publish a catalog;
validation-only code pushes never write archive data. The daily metadata update
remains available as a fallback. Active pinned local recovery runs are unchanged.

The UI distinguishes catalog update time from viewer publication time. These are
snapshot dates, not a claim that every ongoing fetch has already been included.
