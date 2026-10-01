# Capture and normalization fidelity

Verified locally on September 28, 2026, against retained upstream files and a small set of fresh API responses. This work changes capture, replay and normalization. It does not claim a production backfill or deployment.

The rule is simple: retain the source's content and acquisition facts, then derive the common fields. Source labels, classifications and relationships remain available even when our normalized categories differ. A local reparse never becomes a new upstream observation.

| Source | Retained input and repair | Direct verification |
| --- | --- | --- |
| Congress.gov meetings and committees | Complete JSON records remain in gzip JSONL. Meeting captures now record the actual retrieval time, write atomically, retry failed detail requests from a small pending file and check updates to historical Congresses. Normalization includes nomination parts, treaties, continuations and explicit document categories. | All 18,139 saved meetings, 3,424 committee rows and 167,814 document URLs roundtrip unchanged. Recovered 5,254 nomination references, 15 treaty references and 19 continuation dates. Fresh source records and bounded production collectors passed exact capture-to-adapter checks. |
| House XML and fallback HTML | Every file variant, original type code, source date, witness/panel ownership and removed entry survives in saved evidence. CSVs remain compact summaries. Richer normalization retains existing IDs when the old and new source records have an unambiguous correspondence. | Replayed 5,741 events; retained 76,624 XML file occurrences and attributes. Recovered 1,843 valid URLs. Nine malformed upstream URLs remain visible as source values and explicit issues. |
| Senate committee pages | Link labels and attributes, ordered text, descriptions, embedded media, structured data, panel labels and direct witness/document ownership survive parsing. Existing live observations take precedence over older caches. Explicit attachment responses can join a landing link to its direct file. | Replayed 4,762 legacy pages, retained 12,538 ownership links and 3,444 locations, and recovered 49 document URLs. Added 296,320 non-file anchor occurrences. All 5,232 saved page payloads passed exact normalized readback; every original document and witness row remains. A final additive repair retained 1,324 original player configuration scripts on 331 digest-matched cached pages; all 331 payloads passed exact readback with unchanged normalized identities and acquisition facts. Two fresh Indian Affairs requests also preserved the scripts and actual retrieval times through normalization. |
| GPO MODS XML and transcript HTML | A gzip JSONL evidence file retains exact bytes and digests separately from the CSV. Serial numbers and preferred citations remain distinct. Constituent files, committee metadata, witness descriptions, member rosters, errata labels and all reported dates survive. Rosters do not become claims of attendance. Failed packages remain queued; parser upgrades can refresh unchanged records. | All 6,476 rendition URLs in 3,145 retained MODS files reach normalization. Retained 340 HTML files. Six real packages exercised production listing, changed/unchanged capture, pending retry and exact adapter readback. |
| Witness-list PDFs and MODS descriptions | Keep extracted text or source witness strings, digests and parsing metadata. Actual retrieval receipts remain distinct from cache imports. Failed refreshes preserve earlier data, missing files are retried, and invalid responses cannot become empty witness lists. Three visually read scans use corrections limited to those exact file digests. | Read all eight retained PDFs. Recovered five source witnesses; two add selected CSV appearances because the others already have stronger sources. Repaired affiliation text for 1,234 people across 424 packages. Live MODS/PDF checks preserved payloads and acquisition timestamps through normalization. |
| YouTube metadata | Retain complete returned channel, playlist-item and video objects, including status and stream fields. Keep playlist-added time separate from video publication time. Save each completed request batch atomically; forced refreshes preserve earlier captures. Incomplete scans remain retryable. API omissions become dated, narrowly scoped observations. | Fresh channel, five playlist items and five video records survive capture and adaptation exactly. A production collector run on a copied Joint Committee on Taxation cache also passed. Regression tests cover interrupted writes, interrupted scans and unavailable videos. |
| Caption tracks | Retain YouTube WebVTT files and Senate playlists/segments alongside derived text. Preserve timing, track choice and check receipts through inventory and normalization. Numeric speech survives cue parsing. Acquisition failures remain retryable; old entries without timing evidence can be recaptured. | Read existing text/index pairs and real Senate segments; tests exercise track selection, cue parsing, interrupted acquisition, migration from legacy entries and exact receipt retention in normalized source records. |

Normalization reuses an originating House or Senate appearance when a recovered CSV row is its unique matching copy. It keeps the richer fields and both citations. It also reuses known Senate players and exact, unambiguous GPO primary files. Similar names, ambiguous matches and constituent files do not trigger a global merge.

A combined check of 25 real meetings checked the recovered House XML, GPO addendum, Senate witness ownership, the richer Laura Eskenazi appearance, and both newly selected PDF witnesses together. The final full-input run then validated 2,080,430 normalized records and 336,168 source records, including retained history. Every reference and source selector passed. Independent comparisons found zero missing or changed input payloads across all ten supplied source families, including inventory, and zero changes to the retained GPO evidence payloads.

Caption assessments use the actual check time and scope. A failed refresh preserves the previous successful observation and reports the latest error separately. Old CSV-only negative entries remain unknown because they lack a dated check. Inventory reads the small receipt files; it does not load transcript bodies.

The complete local test suite passed: 534 tests and 28 subtests. Independent reviews covered collection retries, preservation of source fields and existing identities, and the handoff between capture and normalization. No new database, service or dependency was added. Workflow conditions now let independent collectors proceed after another source fails and save their partial progress; publishing derived tables still requires success. The GitHub-hosted workflow has not been executed with this patch.

## Additional local source recovery

A broader local search recovered 186 additional catalog packages: 114 from named XML files and 72 from XML stored under content hashes. The files came from earlier committee-review caches and research under `Work/corpora`. Each import was matched by the XML's own package identifier and retained byte-for-byte. Copies with the same identifier had identical bytes. Existing source files remained untouched.

The search also inspected 22,565 compressed XML files and 382,934 candidate raw/cache files. Three older packages fell outside the saved catalog's Congress 106–119 range and were recorded separately. The search did not establish that the remaining historical captures exist locally.

## What remains unverified

The existing GPO CSV already contains 34,559 structured package records and feeds the current adapter. Of those, 31,414 have no located original MODS capture for a raw-to-output comparison; they are not missing catalog records. Keeping the current structure and preserving previously omitted fields is sufficient for this stage. Locating or recapturing the historical XML is separate coverage work. Historical caption timing was discarded by the old collectors and requires actual recapture. The repaired collectors support those refreshes; the local checks did not perform a bulk download. Protected live Senate observations and unavailable or incompatible cache files were not replaced with older research captures. Senate source state preserves the parsed content and relevant inline player scripts described above, rather than complete HTML, external JavaScript or CSS. Another 124 cached Indian Affairs observations, including 112 nonempty recording IDs, remain in an explicitly undated recovery artifact; they were not mixed into newer live observations. Witness PDF state retains extracted text and digests rather than original PDF bytes.

## Reproduce

Run the focused regression suite with the checkout's Python environment:

```sh
.venv/bin/python -m pytest -q tests
```

**Historical.** The provider import paths in the next paragraph were removed. Current modules are listed in [Package layout](../../packages/congress_api/README.md#package-layout). Replay entry points are in the [replay protection matrix](../congress-api-contracts.md#replay-protection-matrix).

Offline replay commands live in `congress_api.house.replay`, `congress_api.senate.replay` and `congress_api.gpo.replay`; each exposes `--help` and writes a replay receipt. The existing weekly commands retain their inputs and outputs, with the GPO evidence file and pending retries stored on `pipeline-data`.

Local receipts and regenerated source outputs are under `.cache/source-fidelity/`: `house/`, `senate/`, `gpo/`, `inventory/`, `captions/` and `live/`. `full-normalization-validation.json` records the all-input check and its input digests. The subsequent additive Senate script repair is verified separately in `senate/script-capture-replay.json` and `senate/script-live/report.json`; the former records the consolidated Senate digest and unchanged existing fields and identities. `local-xml-search.json` and `local-opaque-xml-search.json` record the additional source locations. These artifacts are separate from the unchanged pinned inputs under `.cache/raw-output-audit-20260928/snapshot/`. The repaired datasets and verification receipts are local artifacts and have not been published.

## Raw archive layout (September 30)

The local R2 mirror is `.cache/congressional-tech-raw/`. It has three directories:

- `bodies/sha256/<first-2>/<sha256>.gz`: one gzip file per distinct uncompressed body. The filename identifies the uncompressed bytes; the index also records the stored gzip checksum and size.
- `receipts/<source>/<family>/<capture-date>/<run-id>.jsonl.gz`: source metadata, original local paths, and references to retained bodies. `documents/` has no additional family component. Missing observation dates use `undated/`; records spanning several observation dates use `mixed-dates/`.
- `indexes/captures.parquet`: source URLs, receipt locations, body references, fidelity, available response status and retrieval time, and unresolved historical file references.

There is no `snapshots/` directory. Receipts retain original JSON values with embedded source strings replaced by body references. `congress_api.retention.bundles.restore` reconstructs those values; it does not promise the original enclosing JSON whitespace. Exact byte captures, older decoded text, and retained files remain distinguishable. Missing files remain explicit and are never represented as successful captures.

A saved record can reference several source families. It remains together in one receipt; the index classifies each referenced body separately. Source journals also retain their collection limits, refusals and outcomes, including entries without a body. Generated tables, code backups and extraction diagnostics are excluded where identified; their originals remain in the existing caches.

`research/scripts/assemble_raw_archive.py` assembles this layout from explicit file manifests. It checks source stability, persisted body checksums, and JSON reconstruction. On APFS it uses independent copy-on-write copies for existing gzip files. It preserves the original caches and observes the configured free-space floor. It does not fetch, upload, change acquisition or replay paths, or delete originals. Migration manifests, logs and validation results live outside the archive under `.cache/r2-admin/archive-layout-20260930/`.

The reviewed inputs are `final-body-manifest.jsonl` and `final-record-manifest.jsonl` in that administration directory. Record manifests include the source family so journal headers and bodyless acquisition outcomes retain the same source context as their response records. `verification.json` reports the final receipt/index checks; older intermediate logs document the migration and its repairs.

### Filename metadata

`indexes/documents.parquet` has one canonical row per document group, including
unfetched or unresolved entries. `indexes/document-filenames.parquet` retains
every original filename/source association and its metadata from
`house_naming.Engine.extract`. The index builder writes both together:

```sh
.venv/bin/python docs/youtube-coverage/research/scripts/index_document_filenames.py \
  .cache/congressional-tech-raw --inventory-dir output/filename-clustering --workers 4
```

The command reads the capture index, its receipts, and the complete
`filenames.parquet` / `urls.parquet` inventory pair without opening document
bodies or fetching anything. It includes every literal filename variant in the
inventory, plus names found in archived metadata and captures from `documents`,
`govinfo/transcript-html`, `house/meeting-xml`, and `house/witness-xml`. Files do
not need to have been downloaded. URL query parameters and saved response
filenames are included; bare endpoints are not invented filenames.

The filename table has one row per body, filename and source URL. `body_key` is null when no
retained capture supports that exact filename/URL pair. Neither a shared basename
nor a reused URL by itself proves a file match. Repeated observations and matching
header/URL names share a row. `filename_origins` distinguishes response headers,
URL paths and local-only filenames; `source_paths` retains local locations when
no publisher filename was available. Different filenames for the same bytes
remain separate. Bodies without available names still have a row. Literal case
variants remain separate, even when the inventory grouped them. When a variant's
exact URL association is unavailable, it retains a row with a null source URL.

Both tables contain `document_id`. Each filename/source association also has a
`source_id`; the document row's `source_id` identifies its preferred source.
The document row supplies a clean filename, preferred URL/body, and flat
`filenames`, `source_urls`, and `body_keys` lists containing its aliases and
captures. Other list-valued metadata contains all distinct values from its
sources. The filename table preserves the original pairings and spellings.
`format` is computed from saved response media types, with filename extensions
as a fallback. The viewer consumes these saved decisions directly.

The document ID is deterministic for the same evidence. Adding filename/URL
aliases for the same confirmed body does not change it. New document bodies or
resolution of an unknown item can change its ID; this is a file inventory, not
a permanent identifier for a legislative work. Both tables carry the same
build identifier in their Parquet metadata so a reader can reject mixed builds.

Refresh grouping from an existing filename index without parsing filenames,
reading raw captures, or making network requests:

```sh
.venv/bin/python docs/youtube-coverage/research/scripts/index_document_filenames.py \
  .cache/congressional-tech-raw --documents-only
```

All extracted values are ordinary top-level Parquet columns, using lists of
strings to preserve multiple references, possible readings and printed leading
zeros. Missing values are null. The table includes:

- Literal fields such as `congress`, `committee_code`, `document_token`,
  `measure_number`, `version_token`, identifiers, names, subjects and dates.
- Their meanings and alternatives in `<field>_code`, `<field>_label`, and
  `<field>_candidates` columns when the engine supplies them.
- Useful convention-specific metadata such as `document_kind`, `witness_id`,
  `meeting_date`, `vote_date`, `report_number`, `amendment_degree`, and `part`.
- Complete `measure_references` such as `hr1` and `s2`, plus print and fiscal-year
  references. These preserve the pairing that separate type/number lists lose.

New semantic fields automatically become columns. Raw transport syntax and
whole overlapping payload fragments are omitted; the original filename retains
that text. There are no JSON dumps, nested records, offsets, rule IDs, validity
flags, error messages, or parser diagnostics. Use the original `filename` and
`source_url` with `house_naming` to regenerate those details when needed. The
Parquet footer identifies the format and package version. When the engine refines
a subject by separating its date or identifier, the subject column keeps the
refined text. The removed date/identifier remains in its own column, and the
literal filename preserves the full original text.

Saved response `media_type` and `http_status` values are included as flat columns.
They come from the body-owning receipt record and its response headers, with the
capture index as a fallback. They remain separate from the literal `extension`;
a `.pdf` URL can return HTML. Join `body_key` to `captures.parquet` for additional
acquisition facts and publisher data.
Filename metadata does not certify document contents or download success; the
retained response can be an error page. Names and candidate dates remain filename
readings, not established personal identities or meeting dates. Do not count
filename rows as distinct documents or zip independent type/number columns.
Rebuild the derived table after adding captures or changing the parser.

### Local filename viewer

Browse `indexes/document-filenames.parquet` without a build or another export:

```sh
.venv/bin/python docs/youtube-coverage/research/scripts/view_document_filenames.py
```

Open <http://127.0.0.1:8785>. Search any column, filter by Congress, document kind,
format, or saved-response status, and select a filename to see all populated
metadata. Empty fields are optional. Filters and selected rows are kept in the
URL; row links refer to positions in this particular Parquet export. The Format
column and filter use the saved response media type when available and the
literal filename extension otherwise. Saved HTTP statuses stay visible, so a
retained error response is not presented as a successful document download.

The root index builder strips query-shaped suffixes from preferred filenames and groups the
same endpoint's `download=1` variants. It also groups successful document captures
with the same body hash, including a download endpoint and its direct file URL.
HTML, error responses and unknown response types cannot join entries by hash.
Other query parameters (including document identifiers), different hosts and
different paths remain separate unless identical saved document bytes connect
them. A group prefers a saved successful document response with a filename
extension and retains all available formats. The viewer reads these groups from
`documents.parquet`. Select one to switch between original
source records, URLs and literal filenames in one detail panel. The Parquet
filename table retains every source association; this grouping does not assert that different
bodies, versions or formats are identical.

The viewer uses the installed PyArrow library and Python's local HTTP server. It
reads both indexes, serves 50 rows at a time, and loads full source fields only
when a row is selected. Searches and filters match original source values while
the list shows the saved canonical entry. It binds to localhost and exposes only
the viewer, its query endpoints, and the two Parquet downloads. Restart it after
regenerating the tables. Pass the filename index path or `--port` to override the
defaults; `documents.parquet` must be beside the filename index.

### Resolve a document landing page with a bounded GET

```sh
.venv/bin/python docs/youtube-coverage/research/scripts/probe_document_links.py \
  'https://www.finance.senate.gov/download/-7202023-cardin-statement'
```

The command reuses successful exact-URL captures before making requests. Use
`--live` to bypass them. `congress_api.acquisition.documents.resolve_document`
accepts the response reader as a dependency; the HTML parser has no file or
network access. The HTTP implementation uses a streamed GET, asks for the first
256 KiB, and enforces that read limit even when the server ignores the Range
header. Redirects are followed explicitly without reading their bodies. PDF,
ZIP/Office and RTF signatures let the reader stop after 1 KiB. ZIP bytes alone
do not establish a particular Office subtype. XML is identified from its
declaration; none of these prefix checks validates the complete document.

At most five responses are inspected per input URL. Explicit file links,
download prompts, embeds and HTML refresh targets can supply the next URL.
Multiple candidates, loops, truncated HTML and failed requests remain distinct
outcomes. There is no JavaScript execution or inferred URL guessing. Unexpected
compressed responses remain unresolved instead of being inflated without a
limit. These probes share the acquisition host pacing rules but do not retry or
use Zyte automatically.

Results, headers, link attributes and exact prefixes are saved under
`.cache/document-probes/` (override with `--output`). Partial responses are marked
as such and are never added to the capture index as complete downloads. The
command resolves supplied URLs; it does not start a bulk crawl or change the
weekly collection pipeline.
