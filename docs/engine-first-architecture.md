# Congressional Document Archive: Architecture

**Editor's Draft, 2026-10-24**

## Abstract

This specification defines a system that captures congressional source documents, keeps them permanently, and publishes a static public explorer over them. The system has three layers: an append-only, content-addressed raw log; a lake of append-only tables derived from the log; and immutable releases produced by one deterministic SQL job over the lake. A single pointer selects the live release. One data engine (docspec-rs) does all data movement, joins, grouping and export; the application supplies fetchers, parsers, declarative SQL and the site. This document specifies each layer, the release and publish process, the site, orchestration, the capabilities the engine must provide, security, verification and performance. Column-level schemas and test invariants are in the companion specification [[DATA-MODEL]].

## Status of This Document

This is an Editor's Draft. It describes the target system independently of any current implementation. It is accompanied by [[DATA-MODEL]], which defines schemas and invariants, and by [[IMPLEMENTATION-PLAN]], a Note that orders the work from the current system to this one. Comments should be directed to the editor.

## Table of Contents

1. [Introduction](#1-introduction)
2. [Conformance](#2-conformance)
3. [Terminology](#3-terminology)
4. [Principles](#4-principles)
5. [Scale](#5-scale)
6. [System Overview](#6-system-overview)
7. [Raw Log](#7-raw-log)
8. [Lake](#8-lake)
9. [Model](#9-model)
10. [Releases](#10-releases)
11. [Site](#11-site)
12. [Orchestration](#12-orchestration)
13. [Engine Capabilities](#13-engine-capabilities)
14. [Security](#14-security)
15. [Verification](#15-verification)
16. [Performance](#16-performance)
17. [References](#17-references)

## 1. Introduction

*This section is non-normative.*

The system captures source documents published by Congress and related publishers, stores every fetched body permanently, and publishes a fast explorer that runs in a browser over static files. Only the raw log is precious: everything else is a pure function of raw data plus versioned code, SQL and engine, and can be rebuilt at any time.

The three layers are:

1. **Raw log.** An append-only, content-addressed record of every fetch attempt, every body and every human decision. It is never rewritten.
2. **Lake.** Six append-only tables derived from the log: what was captured, what each body says, what each filename says, which page linked each file, and the committee and meeting records. Each row is computed once.
3. **Releases.** Immutable Parquet files produced by one deterministic SQL job over the lake. A single pointer selects the live release.

## 2. Conformance

Sections marked "This section is non-normative", and all diagrams and examples, are non-normative. Everything else is normative.

The key words MAY, MUST, MUST NOT and SHOULD in this document are to be interpreted as described in BCP 14 [[RFC2119]] [[RFC8174]] when, and only when, they appear in all capitals, as shown here.

This specification defines five conformance classes. Each conforms by meeting the requirements that apply to it, here and in [[DATA-MODEL]]:

- **raw writer**: fetchers, recovery imports and review tools that write the raw log (§7);
- **lake producer**: the jobs that append lake tables (§8);
- **publisher**: the job that evaluates the model, exports and publishes releases (§9, §10);
- **reader**: the site and the canary that read releases (§11);
- **engine**: docspec-rs (§13).

Rules that depend on lists (page shapes, error words, URL wrappers and so on) take those lists from versioned registries defined in [[DATA-MODEL]] §2.

## 3. Terminology

**raw log**
: The set of objects under the `bodies/`, `receipts/` and `provenance/` prefixes of the raw bucket. The only layer that cannot be rebuilt.

**body**
: The original bytes of one HTTP response or archive member, identified by the SHA-256 of those bytes and stored once under `bodies/sha256/<aa>/<sha>`.

**receipt**
: One immutable file under `receipts/`, holding one receipt line per fetch attempt or recovery import. A run writes one or more numbered receipts.

**receipt line**
: One JSON record in a receipt. It records one attempt: the requested URL, outcome, status, writer identity, the bodies it references and the links it found.

**capture row**
: One row of the lake table `captures`: one body referenced by a receipt line, or the line itself when it references no body.

**endpoint**
: The pair `(context_url, member_path)`: the URL a body is evidence for, and its path inside an archive if it is an archive member. Text comparison, grouping and occurrences key on the endpoint.

**locator**
: The member path of an archive member, else the URL. Link-shape checks apply to the locator.

**url_key**
: The normalized form of a URL that every link join uses; defined in [[DATA-MODEL]] §7.1.

**reading**
: One row of `readings`: what one parser version found in one body.

**record role**
: The classification of a body: `document`, `listing`, `source_record`, `caption`, `playlist`, `api` or `error_response`. The HTML, XML and JSON parsers write it; every other format takes it from its sniffed format.

**real file**
: A capture row that passes the real-file rule (§9.2): a complete, successful fetch of a body whose record role is `document`, that is not an API response, placeholder or error page.

**real body**
: A body with at least one real-file capture row.

**placeholder**
: A body whose capture rows span more than *k* = 100 distinct context URLs. It connects nothing.

**source file**
: One distinct `(body, effective filename, source URL)` triple, identified by `source_id`. Documents are groups of source files.

**document**
: One distinct content: a connected component of source files joined by shared real bodies, equal text fingerprints at one endpoint, publisher-grouped renditions and reviewer merges. Identified by `document_id`.

**listed document**
: A document with at least one real file or one recovery. Only listed documents appear in the explorer.

**saved file**
: The file a document's page links: its first real file by format preference (PDF first), then newest first fetch, then body hash; or its recovery for a recovery-only document.

**import run**
: A bulk run that loaded older captures, listed in the import-run registry. Its rows give a file an "in our archive since" date, never a capture date.

**document date**
: When a document is dated: from its filename, else its contents, else the meeting it belongs to. It is separate from the capture date, which is when the system first fetched a file.

**rendition**
: One of several formats of one document, such as a bill's PDF and XML.

**edition-ambiguous endpoint**
: An endpoint that holds more than one distinct real body with different or no text fingerprint. No rendition edge is drawn there.

**link key**
: The 8-byte public identifier of a file: the first 8 bytes of a real body's SHA-256, or, for a recovery's original link, the first 8 bytes of `sha256('url:' || url_key(original_url))`. Public links carry it as 16 hex characters.

**recovery**
: Content imported for a link the publisher no longer serves directly, attached to that original link as labeled evidence. It is never a real file.

**recovery import**
: A receipt line with `mode = retained_import` that records a recovery. It carries a synthetic HTTP 200.

**completion row**
: A lake row that records that an input was processed and produced nothing, so the input leaves the work list.

**work list**
: The set of inputs a lake producer has not yet processed, computed by an anti-join against the table's existing rows.

**release**
: One immutable set of Parquet files and a manifest under `viewer-publications/releases/<release_id>/`.

**pointer**
: `viewer-publications/manifest.json`, naming the live release and the last-good release.

**live release**
: The release the pointer names as current.

**last-good release**
: The release the pointer names as previous: the one that was live before the live one. It is kept so stale tabs keep working.

**input identity**
: The digest of every model input and version that a publish run reads (§10.4.1).

**canary**
: The site's own reader module run in Node against an uploaded release candidate before the pointer is flipped.

**fold**
: A `List<Struct<field, value>>` column holding display-only facts, one value per element.

## 4. Principles

1. **Raw is the only truth.** Every other layer MUST be derivable from the raw log plus versioned code, SQL and engine.
2. **Append or replace, never update.** Logs only grow. Derived outputs are recomputed and swapped atomically. No row is edited in place; catalog compaction rewrites files, not rows.
3. **Do expensive work once.** Every body is stored, hashed and parsed once per parser version. Every expensive per-item computation has a lake table keyed by its inputs. Capture still re-fetches URLs on their recheck schedule; that is the point of capture. Platform primitives (content addressing, conditional writes, Content-MD5, ETags, catalog commits) replace hand-built bookkeeping.
4. **Expensive cost grows with change, not with history.** Fetching, parsing and uploading grow with what is new. The accepted passes over history are named: work-list anti-joins scan the keys already processed, the model recomputes over every row each run, and the weekly check lists every body's metadata. None of them reads bodies.
5. **Engine first.** Data movement, joins, grouping, aggregation and export live in the engine. Application policy (ID formulas, field names, grouping rules, parsers) is passed in as SQL and specs and MUST NOT be compiled into the engine.
6. **Nothing reaches users unverified.** A release goes live only after the site's own reader code has loaded it (§10.4.6).
7. **Small bytes.** Keys and facts are stored once, as typed columns, with hashes as binary. Provenance is never copied into derived rows, and nothing derivable is stored. Browser files are the one place where shape follows the reader (§10.1).

## 5. Scale

*This section is non-normative.*

Measured on the 2026-10-19 snapshot. These figures size what an implementation must handle.

| Quantity | Measured |
|---|---|
| Receipt lines, capture rows | 2.6M lines in 2,289 receipt files; 3.9M capture rows |
| Distinct bodies | 1.04M, 0.70 TB stored (PDF 365 GB, ZIP 286 GB, untyped 37 GB, HTML 4.5 GB, XML 0.8 GB) |
| Distinct URLs | 1.16M |
| Source files | 1.68M |
| Listed documents | 0.6–0.7M (estimated): 1.24M catalog rows today, less 454k caption snippets, 98k metadata records, 10k playlists and 1k API responses |
| Normal day | 270–3,553 attempts, 258–1,595 new bodies |
| Import day | up to 708,626 receipt lines (745,456 capture rows), 547k new bodies |
| Largest body | 1.19 GB; none above 5 GB |
| Bodies referenced by one receipt line | up to 22,354 |

At this scale, recomputing the model from the lake each run is cheaper than maintaining it incrementally: a narrow relational proxy ran in 3.7 s with 1.75 GB of memory, and connected components over the 4M-node graph took 1–2 s. The per-item work that MUST NOT be repeated is fetching, parsing bodies and reading filenames.

## 6. System Overview

*This section is non-normative.*

```
fetchers, recovery imports, review tools
        │  create-only writes
        ▼
RAW LOG (one bucket; locked prefixes)
  bodies/sha256/<aa>/<sha>                       stored bytes, keyed by SHA-256 of the original
  receipts/<family>/<write-date>/<run>.jsonl.gz  one line per fetch attempt
  provenance/<kind>/<ts>.jsonl                   human and reviewed decisions
        │
        ▼  docspec-rs, Basin Catalog
LAKE (Iceberg, append-only)
  captures           one row per attempt                        O(new receipts)
  readings           one row per (body, parser, version)        O(new bodies in scope)
  filename_readings  one row per (filename, URL, catalog)       O(new pairs)
  page_links         one row per link found in a fetched page   O(new receipts)
  committee_records  one row per committee in an API response   O(new API bodies)
  meeting_records    one row per meeting in a meeting response  O(new meeting bodies)
        │
        ▼  docspec-rs: one SQL plan, deterministic export
RELEASE (immutable)
  viewer-publications/releases/<release_id>/<file>.parquet
  viewer-publications/releases/<release_id>/manifest.json
  viewer-publications/manifest.json   ← If-Match pointer, flipped after the canary
        │
        ▼
SITE (static) → pointer → release → list (whole) / detail, links, occurrences (ranges)
```

All data lives in one Cloudflare R2 bucket. The lake tables are Iceberg tables in the bucket's Basin Catalog (the managed Iceberg REST catalog).

## 7. Raw Log

### 7.1 Bodies

Key: `bodies/sha256/<aa>/<sha>`, where `sha` is the SHA-256 of the original response bytes and `aa` its first two hex characters.

**Stored bytes.** Media types that compress (HTML, XML, JSON, text) are stored gzip-compressed with `Content-Encoding: gzip` and the original `Content-Type`. Already compressed types (PDF, images, archives) are stored as-is. Either way, an HTTP client that honors `Content-Encoding` receives the original bytes; the `sniff` parser decompresses gzip-stored bodies before reading their first bytes.

**Two digests.** The original's SHA-256 is the identity. The stored bytes' MD5 is the integrity check: R2 verifies it on upload and returns it as the ETag. No other digest is stored.

**Write.** A writer MUST store each body with one create-only PUT (`If-None-Match: *`) carrying `Content-MD5`. Writers MUST NOT use multipart upload: multipart ETags are not MD5s, and no body approaches the 5 GB single-PUT limit.

**412 handling.** A 412 response means the body already exists. The writer MUST record the attempt with outcome `unchanged` and move on, with no HEAD and no comparison. Over half of body-bearing attempts hit an existing body, so this path costs nothing.

**Nothing is cut off.** The fetcher MUST spool each body to a temporary file so that any size up to the single-PUT limit is stored whole. The 201 bodies that older runs cut off at exactly 64 MiB (recorded as HTTP 200 with outcome `size_limit` or `request_failed`) stay in raw as evidence; they are never document files, and capture retries their URLs.

**Crash between a body and its receipt.** If a run stores a body and dies before writing its receipt, the body exists without a creating line; a retry gets a 412 and records `unchanged`. The weekly check (§7.4) finds such bodies and re-hashes each once, recording the result under `provenance/verification/`.

**Older bodies.** Every body written before this specification sits at `…/<sha>.gz`. Older gzip PDFs have a one-time uncompressed copy at `…/<sha>.pdf`. Existing bodies keep their stored form (§11.5).

### 7.2 Receipts

A run writes one or more immutable numbered files at `receipts/<family>/<write-date>/<run>-<seq>.jsonl.gz`, keyed by the UTC write date. New writers MUST use date-shaped prefixes only. Older receipts also sit under `undated/` and `mixed-dates/` (49 files, 2.2M rows); only the backfill reads them.

Each line records one attempt (fields in [[DATA-MODEL]] §5.2):

- requested URL, final URL, time, HTTP status and outcome;
- one entry per body it references (an archive's members are separate entries, each with its path inside the archive), with the body's SHA-256, the server's media type, the format sniffed from the first bytes, and, on the line that stored the body, the stored MD5 and size;
- an allowlisted set of response headers; cookies and authorization MUST NOT be recorded;
- writer identity: job, code commit, lockfile digest and run ID;
- the links found in the body, with their labels and attributes.

A line is about 1 KB. Receipts are the authoritative history of what was captured and when. A run MUST write each receipt file create-only and after the bodies its lines reference, so every receipt line points at a body that exists.

**Recovery imports** write receipts too. Their lines carry `mode: retained_import`, a synthetic HTTP 200, the recovery category and the original link the content recovers.

### 7.3 Provenance

`provenance/<kind>/<ts>.jsonl` holds every decision a person or a reviewed process makes about sources, as append-only timestamped records: accepted URL variants, recovery decisions, document reviews and verification results. A correction MUST be a new record that supersedes an old one by ID; old records are never edited.

### 7.4 Protection and Verification

**Lock.** An indefinite R2 bucket lock covers `bodies/`, `receipts/` and `provenance/`. Writers use create-only writes; the lock, not the token, is what stops deletion and overwrite (§14).

**Weekly check.** One LIST of `bodies/`, joined to `captures` on key, size and ETag for the line that stored each body, confirms that every receipt-referenced body exists and every stored body has the size and MD5 its creating line recorded. That is about 1,000 list requests and no body bytes. The job also downloads 25 random bodies and checks their SHA-256 end to end, which exercises the read and decode path. There is no daily re-hash and no per-body HEAD.

**Full re-hash** is an explicit job. It runs once for bodies written before receipts carried an MD5 and records their ETags as a verification baseline under `provenance/verification/`. After that it runs only before a migration.

**Durability.** Raw is kept in one R2 bucket with no second copy. The lock guards against deletion and overwrite by any credential; R2's own durability guards against hardware loss. A provider-side loss is the accepted risk.

## 8. Lake

### 8.1 Common Rules

All lake tables are Iceberg tables in the bucket's Basin Catalog. Columns use Iceberg's own types ([[DATA-MODEL]] §4). Every commit MUST carry its requirements (table UUID and current snapshot), so concurrent writers fail rather than overwrite each other.

**Conflict retry.** Basin's own maintenance commits to the same tables, so an append can lose a race. On a conflict the writer MUST reload the table, recompute its work list against the new snapshot, write only what is still missing, and retry a bounded number of times. It MUST NOT re-send the losing files, which could duplicate rows when two runs ingest the same receipts. Files from a losing attempt become orphans (§8.8).

**Completion rows.** A producer whose work list is "inputs with no rows yet" (`page_links`, `committee_records`, `meeting_records`) MUST write one completion row for an input that produced nothing, in the same commit as its outputs. Readers skip completion rows. `readings` and `filename_readings` always write one row per input, with a status, so they need none.

**Sort order.** Nothing depends on the physical sort order of a lake table, because compaction may not keep it.

**Work lists.** Every producer finds its work by an anti-join of its inputs against the rows it already holds. A daily run appends once; a backfill appends once per batch, so it always resumes.

### 8.2 `captures`

One row per body a receipt line references, plus one line-only row for each line that references none (1.04M of today's 2.6M lines). Rows are unique on `(receipt_key, receipt_line, capture_index)`. The line's own fields (requested URL, time, HTTP status, outcome, mode) are on every row, so no attempt loses its status. Hashes are binary. There are no derivable columns.

A body's endpoint is `(context_url, member_path)`: an archive member is recorded at its container's URL with its path inside the archive.

Recovery imports keep their identity: `mode`, `publisher_requested`, the recovery category and the original link are columns.

**Ingest.** For each receipt family, list only date-shaped prefixes, starting from the newest date already ingested; anti-join against ingested receipt keys; append the missing receipts in one commit. Listing cost grows with new receipts, not with all of them. The backfill reads the non-date segments once. The weekly check lists everything and appends anything a late receipt left behind.

**Rebuild check.** Rebuilding from all receipts MUST reproduce the same set of rows.

### 8.3 `readings`

One row per `(body_sha256, parser, parser_version)`, partitioned by `(parser, parser_version)`. Each media family has its own parser and version, so a new HTML parser never re-reads a PDF.

Columns are a narrow typed core plus one fold. The core holds what the model's rules read: format, record role, title, heading, visible-text size, link counts, a content date, error signals and text fingerprint. Large text goes in its own table.

**Scope**, declared in the model SQL:

- HTML, XML and JSON: full readings. The HTML reading records the error-page and listing-page signals the real-file rule uses (§9.2), and any parser records a date it reads from the content.
- Every other format (PDF, ZIP, Office files, images, web archives, archive members) takes its record role from its sniffed format: a caption or playlist if it is one, otherwise a document.
- PDF: no full reading for now. Full-text extraction of every PDF (about 403 GB, 261,055 bodies) is deferred to its own table, `pdf_text` ([[DATA-MODEL]] §6.7). Embedded PDF titles are not read; names stay filename-based.
- ZIP containers and captions: none. ZIP members are captured as their own attempts.
- **Every body has a sniffed format.** The fetcher records it for new bodies. A `sniff` parser runs once over every older body with one ranged read of its first bytes (about 1.04M ranged GETs). The server's media type MUST NOT be used instead.
- **Text fingerprints, for candidates only.** A `fingerprint` parser handles the bodies at endpoints that produced two or more distinct complete real files and records a normalized text fingerprint: for a ZIP, the digest of its sorted member hashes, taken from `captures` without reading the ZIP; for a PDF, the digest of its extracted text. Today that is 148 endpoints, 297 bodies and about 1.4 GB. It evaluates the model's real-file rule over the current lake, before the publish run pins its snapshots (§10.4.1). There is no full-corpus text pass.

**Versions.** The work list is an anti-join on `(sha, parser, parser_version)`. New parser versions are backfilled in background batches. A version is complete when its work list is empty at the pinned snapshot. The model MUST read the newest complete version of each parser, and while a newer version backfills, the daily run MUST apply the version the model reads to new bodies too, so it stays complete.

### 8.4 `filename_readings`

One row per `(filename, source_url, catalog_version)`, holding what `house-naming` extracts from a filename, as typed facets and keys plus a fold. Filename readings depend on the filename and the source URL, not the body, so they cannot live in `readings`.

The key uses the full source URL, because house-naming qualifies some readings by exact mirror URL, and the filename, because 32,574 source files have a filename that is not their URL's last segment. `catalog_version` covers the house-naming version, every vocabulary passed in, the typed-field derivations and the effective-filename rule, so a change to any of them is a new version.

**Work list.** The effective filename and source URL of every source file ([[DATA-MODEL]] §7.3), with no row for the current catalog version. The producer applies the effective-filename rule itself, as a lake-level rule. A new catalog version is one background job over about 1.39M pairs.

The model uses the reading of each document's saved file. Per-copy readings stay in the lake.

### 8.5 `page_links`

One row per link found in a fetched page: the page, its fetch time, the linked URL, the link's label, its position in the page and the attributes the page gives (document type, dates). Rows are unique on `(receipt_key, receipt_line, link_index)`. Document pages use it to show where each copy was linked from and under what label.

**Ingest.** From the same receipts as `captures`, with its own work list and its own commit, since Iceberg has no multi-table transaction. If it lags `captures`, pages show less link context; nothing fails. About 3–5M rows.

### 8.6 `committee_records`

One row per committee in a Congress.gov committee API response: congress, system code, chamber, name and parent committee. The JSON parser reads each committee API response once; the model joins on `(congress, system_code)` to show committee names instead of codes. The committee fetcher MUST fetch through the raw writer like every other fetch, so names derive from raw. A few thousand rows.

### 8.7 `meeting_records`

One row per meeting in a meeting response: chamber, event ID, congress, title, date, type and committees. Sources are the Congress.gov meeting JSON, its XML fallback and the House and Senate meeting inventories, all fetched through the raw writer. Hearing pages take their title, date, type and committee from it. Tens of thousands of rows.

### 8.8 Maintenance

Basin Catalog maintains the tables: compaction (target 128 MB) and snapshot expiration (older than 30 days, keep the last 5), enabled per table. Expiration also deletes the data files that only expired snapshots referenced. At about 315 KB of appends a day, compaction volume is a few GB a month.

**Orphans.** Basin does not remove files that no snapshot ever referenced, such as the data file of a lost commit race. The weekly check reports their bytes; cleanup waits until that number matters.

**Fallback.** The lake depends on compaction keeping the number of manifests in the current snapshot bounded; [[IMPLEMENTATION-PLAN]] confirms it before building on it. If it does not hold, the lake tables move to dated Parquet files with an `If-Match` manifest per table, which gives the same atomicity without time travel.

## 9. Model

### 9.1 Outputs

The domain model is versioned SQL in the application repository. One engine job registers the six lake tables and the provenance records, evaluates the plan, and writes every output as a release file. There are no intermediate tables.

| Output | Content |
|---|---|
| `url_state` | Latest outcome and retry schedule per requested URL, counted over attempts (receipt lines), not capture rows; `size_limit` and `request_failed` outcomes are retried |
| `filenames` | One row per source file; `source_id` is the SHA-256 of `(logical body key, filename, source URL)` |
| `documents` | Source files grouped by connected components; `document_id` is the SHA-256 of the sorted body set, or of the sorted source IDs when there is no body |
| `members` | `(document_id, source_id)` |
| `recoveries`, `reviews` | Resolved from provenance and captures |

**ID formulas** keep today's exact inputs and serialization, including the logical body key string `bodies/sha256/<aa>/<sha>.gz`, whatever the physical key; [[DATA-MODEL]] §7.3–7.4 gives them byte for byte. Links do not depend on `document_id` (§10.1), so an ID that changes when a version joins a group costs nothing.

### 9.2 Real Files

A document is one distinct content. Its files are the real files with that content. A capture row is a real file only if all of these hold:

1. it was a real fetch (`mode = fetch`), not a recovery import;
2. the fetch was complete: outcome `stored` or `unchanged`, never `size_limit` or `request_failed`, whatever the HTTP status;
3. the HTTP status was 2xx;
4. it has a body that is not empty and not a placeholder;
5. its record role is `document`. Any content format counts: PDF, ZIP, document XML, web pages, Word, web archives, images, text and others. The roles that do not count are listing page, caption, playlist, API response, metadata record (XML that describes a document, such as MODS, PREMIS, meeting and witness records) and error page. Roles MUST come from the sniffed format and the reading, never from the server's `Content-Type`;
6. it is not an API response: JSON fetched from an endpoint on a written list (api.congress.gov, api.govinfo.gov, the YouTube Data API, the Wayback CDX API). Other JSON is a document;
7. for HTML, two checks decide whether it is a web page, applied to the locator:
   - **link shape first.** If the locator points at a file (`.pdf`, `.zip`, `.doc`, `.docx`, `.xml`, `/download/`, `download=1`, `file_id=` and similar), an HTML response is never the document. The exact list is regular expressions in the SQL;
   - **then generic error signs,** for page-like locators: a tiny body (visible text under 2,048 bytes), a generic error word in the title or heading (access denied, forbidden, not found, retry later, service unavailable, error), or a placeholder body. There are no site-specific templates;
   - **and no listing pages.** A page whose visible text is mostly links to other files, such as a hearing index or a press-release list, is a listing page, not a document. It stays in the lake and still supplies link context.

Archive members are judged and named by their own path, not by the container's URL; otherwise about 34,000 web pages inside ZIPs would be rejected because the container ends in `.zip`.

Everything that fails the rule stays in raw and `captures` as evidence. It never enters a document's body set, so it never changes the document's ID, saved file or links. Caption snippets, metadata records, playlists, API responses and links that never yielded a real file stay in the lake, where they still drive `url_state`.

The page-shape, error-sign, listing-page, placeholder and rendition rules are measured as classifiers on a hand-labeled sample before they are fixed (§15; [[IMPLEMENTATION-PLAN]] §5).

### 9.3 Grouping

The edge set is SQL, written down before anything is compared with the old catalog. Source files connect through four kinds of edge; connections chain.

1. **Same body.** Source files that each have at least one real-file capture row and that share a real body. Web pages are included: the same real page saved at several addresses is one document. Every real body is therefore in exactly one document, so a file link always resolves to one place.
2. **Same text.** Source files at the same endpoint whose real files have equal text fingerprints (§8.3). When one URL served several complete files: same text means one document whose bytes were re-packaged (the page shows the newest bytes, and older bytes still resolve through links); different text means separate documents, since a new edition is a new document; no text means separate documents.
3. **Same rendition.** Real files that are one document in different formats, joined by (a) the publisher grouping them (links on the same parent page under the same nearest `<li>` or `<document>` ancestor), or else (b) files in one directory with the same filename stem and document extensions, excluding generic stems such as `index` or `download`. A group joins only if its files all have different formats, one file per format; otherwise it draws no edge, so a witness's testimony, disclosure form and biography, all PDFs listed together, stay separate documents. A rendition edge MUST NOT be drawn at an edition-ambiguous endpoint, so an old draft is never grouped with, or shown as, the current edition.
4. **Review.** A reviewer's `duplicate_of` between two documents' link keys.

Placeholders connect nothing: any body whose capture rows span more than *k* = 100 distinct context URLs. The most widespread, a 57-byte caption file at 87,161 URLs, would otherwise glue 174,323 source files together. *k* = 100 selects 18 bodies (22 at 50, 12 at 200).

Files connect through one node per body, fingerprint or rendition group, so a group of n files costs n edges, not n². Grouping runs in memory over 32-bit IDs and MUST refuse above a configured node count; the parent array is 16 MB at 4M nodes, and assigning dense IDs is a hash aggregation of a few hundred MB, which sizes the memory pool. The model reports the largest components by edge kind; before the real-file rule, the largest of today's 1.26M components had 456 source files.

**Listing.** The explorer lists real documents only: a document needs at least one real file or one recovery. A recovery that has no single listed document to attach to (§9.6) gets a document of its own, built from a bodiless source file for its original link.

### 9.4 Saved File and Dates

**Saved file, PDF first.** A document's page links its first real file in one total order: format preference (PDF first), then newest first fetch with undated files last, then body hash, never physical file order. Other formats are listed as alternates, one per format, and a link to any rendition opens the same entry. A recovery-only document's saved file is its recovery, labeled as one.

**Two dates, each saying what we know.**

- The **document date** is when the document is dated: the date in its filename (a hearing date or a single clear date), else a date read from its contents, else the date of the meeting it belongs to. It is never a guess among several dates. The page says which source it came from.
- The **capture date** is when the system first fetched the file. The page says "Captured <date>" for a real fetch; "In our archive since <date> (original capture date not recorded)" for files known only from an import run; and "Capture date not recorded" when there is none. Import runs are identified by the import-run registry, not by a date.
- `list` sorts editions with the same filename by document date, then capture date. Files with neither sort last, and files known only from an import run sort with the undated ones.

### 9.5 Meetings, Committees and Record Keys

- Each source file gets a meeting reference (chamber, event ID) from its URL, from the meeting page that linked it, or from a House meeting XML record's document list; a document carries its members' set, and `list` keys meetings by chamber and event ID. House and Congress.gov meeting IDs are one ID space, the same event ID the committee explorer uses, so a page can list every document for a hearing under the hearing's title, date, type and committee from `meeting_records`. The meeting reference is derived in SQL, like `url_key`; nothing new is stored for it.
- Official record keys (the GovInfo package, bills as `{congress}-{type}-{number}`, member Bioguide IDs) let a page link out to the GPO record, the bill and the member. They and the filename date are written once as typed columns by the filename-reading producer; house-naming's literal strings stay unchanged in its fold.
- **Committee names, not codes.** House-naming's committee code maps to the Congress.gov system code (House codes as `hs` plus the lowercased code, so `AG03` is `hsag03`), and the name comes from `committee_records` for the document's congress, or the most recent congress that has the code. Senate and joint codes map the same way only where sample tests confirm the form. Facets and pages show the name; unmapped codes are reported with counts.

### 9.6 Recoveries and Reviews

**Recoveries are evidence for the original link,** never files the recovering URL served. They MUST stay out of `url_state`, text comparison, link keys and capture dates; an import's timestamp is the recovered copy's own. A recovery attaches to the listed document that holds its original link when exactly one does; when none does, or several do because the link came back as different editions, the recovery keeps a page of its own. Either way it is labeled by kind with its evidence, and none poses as the original file. A written mapping from the receipt's recovery category gives the kind ([[DATA-MODEL]] §7.7); an unmapped category MUST fail the build.

**Reviews** target a link key, so they follow a file through merges and splits. `duplicate_of` merges two documents. `hide` keeps the document in the release so its links resolve, but removes it from search and facet counts; its page shows a "removed by review" note with the reason and date. `title_override` and `kind_override` replace the displayed value; the original stays in the fold. Duplicate edges apply before grouping; overrides and `hide` apply to the resulting document.

### 9.7 URL Normalization

Every link join (page links to member URLs, recoveries to source files, endpoint matching) MUST use `url_key`, defined in [[DATA-MODEL]] §7.1. It unwraps redirect and archive wrappers to the inner URL, drops the scheme, lowercases the host, drops `www.`, the default port, the fragment and a trailing slash, strips tracker parameters on any host and page-state parameters on known hosts only, sorts the remaining query parameters and keeps them, and keeps the path's case. Identity (`source_id`, `requested_url`, `url_state`) keeps the exact URL. The wrapper patterns and the strip-list are SQL, each entry with a real sample URL as a test.

## 10. Releases

### 10.1 Release Files

The release files are derived from the model outputs in the same job. The site reads four of them; the list row number links them. Exact columns are in [[DATA-MODEL]] §8.

| File | Order | Contents | Read pattern | Writer settings |
|---|---|---|---|---|
| `list.parquet` (about 2.2 MB) | `(filename, document_date nulls last, first_captured nulls last, document_id)` | Display name, facet fields (every value a file has), hidden-by-review flag, document date, first-captured date, date kind, saved kind, the document's meetings; no ID | Downloaded whole, decoded column by column in a Web Worker | `filename` delta-encoded without a dictionary; facets keep dictionaries; 65,536-row groups; no page index |
| `detail.parquet` (30–50 MB) | Same row order as `list` | A typed core of what the site acts on (link key, saved file's body and suffix, occurrence start and length, recoveries, alternates, meetings, GovInfo package, bill keys, Bioguide IDs) plus one fold for the sparse display facts | One page per leaf column, located by the offset index | Offset index on every leaf; 16 KB pages for incompressible key columns, 64 KB for the rest; 1,024-row write batches |
| `links.parquet` (7–9 MB) | `link_key` | 8-byte link key and list row | Point lookup through the column index's page statistics | Offset and column index on `link_key` (about 25 KB together); 16 KB pages; one row group |
| `occurrences.parquet` (20–30 MB) | `(list_row, ordinal)` | Where each copy was seen: URL, path inside an archive, filename, outcome, capture dates, and the page that linked it with the link's label | The range named in `detail` | Offset index on every column; 64 KB pages of at most 512–1,024 rows |
| `url_state.parquet` (about 10 MB) | `requested_url` | Latest outcome and retry schedule per URL; no body hash | Read whole by the capture job, not the site | Defaults |

Sizes are estimates at about 0.65M documents, scaled from measurements on today's 1.24M catalog rows.

- **Documents only.** There are no per-copy pages. A document page shows its saved file, its other formats, its capture dates, its readings, its recoveries, and where each copy was seen and which page linked it.
- **Editions sit together.** `list` sorts by filename, then document date, then capture date (§9.4), so editions with the same filename appear side by side with their dates.
- **Links point at a file.** A document's ID changes whenever a version joins its group; a file's fingerprint never changes. A public link therefore carries a link key (16 hex characters). `links.parquet` maps every real body of every listed document to that document's row, so old links keep resolving when the group or its saved file changes. Error pages and recovery bodies are never keys. Each recovery's original link also gets a key derived from its `url_key`, resolved by the attachment rule (§9.6), so a recovery-only page keeps its link after the original finally downloads. The export MUST refuse if two keys from different inputs are byte-equal.
- **No ID in `list`.** Measured at today's 1.24M rows: 4.05 MB without an ID, 15.8 MB with an 8-byte ID, 45.9 MB with hex IDs.
- **Detail reads.** The reader fetches `detail`'s offset index once per session. After that a detail view is one round trip of about 15 concurrent page reads, roughly 120 KB. The typed core holds everything the site acts on, so the reader never parses packed strings; the fold holds the hundred-odd display-only fields that would otherwise cost a page each. `document_id` lives in the fold, since `link_key` is the public ID.
- **Binary keys** everywhere except `list`, including the saved file's body hash (the reader adds the suffix and hex-encodes). Hex hashes were 160 of 187 MB in a measured flat detail file.
- **Shards.** `detail` and `occurrences` MAY be split into fixed row-range files, which the manifest lists with their row ranges. There is one shard today; the export adds shards when an offset index outgrows a quick first fetch, at roughly 10 times today's rows.
- **Ceiling.** At about 10 times today's catalog rows, `list` reaches 40 MB and downloading it whole stops being reasonable. Then `list` is sharded by facet, or search moves to DuckDB-WASM or a server.

### 10.2 Shared Writer Settings

All release files use Parquet 2.0 data pages and ZSTD; fixed row counts per row group, flushed on row count only; chunk statistics; footers under 512 KB, so one request reads metadata; and no Bloom filters. Unfiltered facet counts go in the release manifest.

### 10.3 Determinism

Identical inputs MUST produce byte-identical files, so reruns are idempotent and the "nothing changed" check is exact. The engine enforces it:

- every sort key MUST be unique, or the export refuses;
- partition order is fixed;
- the export re-batches its input to the pinned write batch and flushes row groups on fixed row counts, whatever the upstream batch sizes or spills;
- writer properties and the `created_by` string are pinned;
- no timestamps or run-specific values go into content.

Tests compare bytes across thread counts, input orders, batch sizes and a forced spill. Determinism is not a dedupe mechanism: one new document shifts every later row number, so on any day with a change every file changes, about 90 MB of uploads.

### 10.4 Publish

#### 10.4.1 Input Identity

A publish run first brings every lake table up to date, each producer on its own work list, with `fingerprint` last. Then it MUST pin the current snapshots once, compute the input identity from them, and run the model against the same snapshots. The input identity is: a digest of the sorted set of receipt keys ingested into `captures` and into `page_links`; row counts per partition of `readings` (per parser version), `filename_readings` (per catalog version), `committee_records` and `meeting_records`; the provenance digest; and the SQL, engine, parser, catalog and registry versions. It describes content, not snapshot IDs, because a compaction changes snapshot IDs without changing content, and a receipt-key set (unlike a newest-date mark) also catches late receipts.

#### 10.4.2 Early Skip

If the input identity equals the live release's, publish stops before the model runs. A review decision or a SQL change therefore publishes without waiting for a capture.

#### 10.4.3 Release ID

The release ID is the SHA-256 of the file list (name, SHA-256, size, rows) and the schema version, computed after export and before upload. If it equals the live release's, publish records the new input identity and stops. An empty `list` MUST NOT be published.

#### 10.4.4 Upload

Files are uploaded to `viewer-publications/releases/<release_id>/` with a create-only PUT and `Content-MD5`. A 412 on a rerun MUST be checked against the expected MD5 with one HEAD of that object's ETag; this is the only HEAD of an immutable file the system makes.

`releases/<release_id>/manifest.json` holds only content: each file (name, SHA-256, MD5, size, rows, row range, shard), the schema version, the release ID and the facet counts. It is deterministic, so a release that re-emerges writes identical bytes.

`releases/<release_id>/inputs/<input_digest>.json` records the input identity, the pinned snapshot IDs and the run. A release produced from several input sets has several input records.

#### 10.4.5 Canary

The site's own reader module runs in Node against the uploaded candidate over HTTPS, so Range reads and caching headers are real. It decodes `list` within a heap budget for a mid-range phone, runs a search and a facet count, reads the first, last and a random detail, resolves a link, reads an occurrence range, opens one saved copy, and checks that `url_state` decodes. It takes under a minute and needs no headless browser.

#### 10.4.6 Flip

The pointer holds `release_id`, `previous_release_id` and `schema_version`. The flip writes the candidate as `release_id` and the outgoing live release as `previous_release_id`, with `If-Match` on the pointer's current ETag. A failed canary or a lost race leaves the previous release live. Release files and manifests are cached as immutable; the pointer is `no-store`.

#### 10.4.7 Concurrency and Retention

Publish runs one at a time, through the CI's concurrency setting. Publish MUST NOT delete anything: two runs can produce the same release ID, so a failing run must not delete a prefix another run just made live.

At least two releases exist at all times: the live release and the last-good release. The weekly job re-reads the pointer just before it deletes, takes both release IDs from it, then removes prefixes under `viewer-publications/releases/` that are neither live nor last good and are more than a day old. Failed candidates go the same way. Up to a week of daily releases (about 0.6 GB) can sit there in between. Releases share no files, so nothing needs reference counting.

## 11. Site

### 11.1 Reads

The site reads pointer → release manifest → `list`, `detail`, `links` and `occurrences`. Search and facet filtering run in a Web Worker over `list`, decoded column by column into arrays and dictionary codes, because objects would cost hundreds of MB of heap on a phone. Details and lookups use HTTP Range reads through hyparquet's offset-index page reads (`useOffsetIndex`, 1.31.2). Long occurrence ranges are read a page at a time: the largest document today has 33,479 occurrences.

### 11.2 Devices and Speed

The site targets desktop and mid-range phones. The contract test and the canary enforce a heap budget. There is no per-view byte budget. Speed targets (startup, search and detail times, and the heap budget) are measured on real phones and desktops first, then fixed as targets the canary and contract test check. The first measurement uses a release with about twice the target row count, so its targets are conservative.

### 11.3 Stale Tabs

Only the live and last-good releases are sure to exist, so a tab left open across two publishes can lose its files. On a 404 for a release file, the reader MUST re-read the pointer and reload.

### 11.4 One Reader and Its Contract

The reader is a plain module with no DOM dependency, so the canary runs the same code the site ships. The manifest carries a `schema_version`; the reader MUST accept the current and the previous version, so format changes ship reader-first, then publisher.

### 11.5 Saved Copies

- Bodies written to §7.1 open directly.
- Older gzip PDFs open their one-time uncompressed copy at `bodies/sha256/<aa>/<sha>.pdf`.
- Other older gzip bodies are fetched and unpacked by the site with the browser's `DecompressionStream`, then opened with the media type from `detail`.
- Older gzip bodies over 100 MB (579 of them, up to 1.19 GB) are offered as a labeled compressed download instead.
- A document whose content is a recovery labels it by kind and links the recovered file.

### 11.6 Origin

`congressional-data.spicygov.ai` serves the bucket directly with a read-only, any-origin CORS policy (GET/HEAD, Range), immutable cache headers on release files, a content security policy and the `?filename=` download rule. There is no custom-domain path allowlist: `r2.dev` serves every key anyway.

## 12. Orchestration

```
capture:     live url_state → fetchers → bodies → receipts            (daily; network-bound)
publish:     captures, page_links → readings, filename_readings,
             committee_records, meeting_records → fingerprint
             → pin snapshots → input identity → early skip
             → model + export → canary → flip → status                 (after capture, or on demand)
maintenance: raw check and sample → release retention → orphan report  (weekly)
backfill:    readings or filename_readings for a new version           (on demand)
```

- **Idempotent steps.** Each step is keyed by its input and is a no-op when that has not changed. Each step commits durably, so a failed run resumes by running again. There are no journals.
- **Capture reads the public release.** It builds its queue from the live release's `url_state`, so it needs no lake or release credentials. If a canary has failed, capture works from a slightly older schedule, which is safe because body writes are create-only.
- **Separate credentials.** Capture, publish and maintenance run as separate jobs with separate credentials.
- **Pinned engine.** The engine binary is pinned by revision and digest and MUST be checked before any storage access.
- **Resources.** Resource limits (threads, memory pool, scratch) are explicit per runner class. The memory pool MUST NOT exceed the machine.
- **Status.** Every publish run writes `viewer-publications/status.json`: input identity, rows per output, durations, bytes and the live release.
- **Local runs.** The same commands run locally or in CI. Correctness MUST NOT depend on a CI feature.

## 13. Engine Capabilities

The engine (docspec-rs) MUST provide:

1. **Multi-input SQL plans** over Iceberg tables in Basin Catalog and Parquet files, in one DataFusion context.
2. **Append** through the REST catalog, always sending commit requirements, with the conflict retry of §8.1.
3. **Deterministic multi-file export:** SHA-256 and MD5 computed while writing; per-file writer settings, including offset and column indexes, page sizes, page row limits and per-column encodings; fixed row counts per row group; unique sort keys; row-range shards; and the rules of §10.3.
4. **Connected components** in memory over 32-bit IDs, refusing above a configured node count.
5. **Streaming I/O.** No re-read of a just-written object and no HEAD of immutable files, except the one HEAD that verifies a 412 on a release rerun (§10.4.4). File and row-group sizes come from table properties.
6. **Bounded resources** set by configuration: compute threads, memory pool and scratch space. Sorts and aggregates spill or fail clearly within the pool. Hash-join builds do not spill, so plans keep wide folded columns off the build side: join on keys first, then attach the wide column.
7. **A thin interface:** a library plus a CLI that runs a declarative job spec (inputs, SQL, outputs, export settings) and returns a machine-readable result.

The engine MUST NOT contain: application policy (ID formulas, field names, the grouping rule); parsers for bodies or filenames; table maintenance, which Basin Catalog does; bookkeeping that duplicates Iceberg; resume machinery beyond per-step commits; or test-only production paths.

Iceberg is used only to read and append. If replace or branching is ever needed, it is added upstream to iceberg-rust rather than worked around.

## 14. Security

- **Raw:** create-only writers plus the bucket lock on raw prefixes.
- **Credentials.** R2 tokens scope object permissions to buckets, never to prefixes, so any writing token can also delete unlocked keys. Capture, publish and maintenance use separate tokens, so each can be revoked on its own; only maintenance deletes release prefixes.
- **One bucket.** Raw isolation rests on the lock plus create-only writers.
- **Public data.** Everything stored is public records and is readable publicly.
- **Receipts** carry allowlisted headers only (§7.2).

## 15. Verification

1. **Raw invariants:** the weekly LIST joined to `captures` (key, size, MD5 of the creating line), the weekly 25-body sample, and the one-time baseline for older bodies (§7.4).
2. **Lake rebuild equivalence:** `captures` rebuilt from all receipts equals the appended table (§8.2).
3. **Determinism:** byte-identical exports across thread counts, input orders, batch sizes and a forced spill (§10.3).
4. **Contract:** CI builds a release from a fixed sample of real receipts and loads it through the real site in a headless browser, within the heap budget.
5. **Canary:** the reader module in Node against the uploaded candidate before every flip (§10.4.5). Both the canary and the contract test check that a 404 on a release file makes the reader re-read the pointer and reload.
6. **Production parity:** no test-only branches in production code, enforced by a ratchet test.
7. **Data-model invariants:** the 22 invariants of [[DATA-MODEL]] §10, as tests over the lake, the model outputs and each release.
8. **Rule accuracy:** a hand-labeled sample of a few hundred files measures how often the page-shape, error-sign, listing-page, placeholder and rendition rules wrongly include or exclude a file.

## 16. Performance

### 16.1 Cost Bounds

*This section is non-normative.*

| Step | Cost | Expected |
|---|---|---|
| Capture | O(new attempts), network | Bounded by politeness to sources |
| Captures ingest | O(new receipts) to read; the work list scans the keys already ingested | Seconds |
| Readings | O(new bodies in scope × parse cost) | Minutes daily; backfills in background |
| Filename readings | O(new pairs) | Under a second daily; 7–18 minutes per catalog version |
| Model + export | O(N log N) sorting plus scans and joins over every row; linear grouping | Seconds for the narrow plan; `url_key` and meeting references are recomputed each run |
| Publish | O(release size) | About 90 MB on a day with changes |
| Detail view | One page per leaf | About 120 KB in one round trip, after a one-time offset-index fetch per session |
| Weekly check | O(history) object metadata | About 1,000 list requests, no body bytes |

A normal day moves about 1,500 object operations and 2 GB, well inside R2's free tier at today's scale and at 10 times it.

### 16.2 Validate Before Building

*This section is non-normative.*

Before the lake and model are built on, [[IMPLEMENTATION-PLAN]] measures, in the engine on the smallest production runner class:

1. full model-and-export time and peak memory, including filename readings, the folded `detail` and `occurrences`, with the size of every hash-join build;
2. connected components on the real graph, with the grouping rule;
3. join behavior at the memory pool limit;
4. export determinism, including batch sizes and a forced spill;
5. Basin Catalog: an append that races a compaction retries correctly, two ingest runs on the same receipts leave one copy of each row, and the manifest count stays bounded under compaction.

## 17. References

### 17.1 Normative References

**[RFC2119]**
: S. Bradner. *Key words for use in RFCs to Indicate Requirement Levels.* BCP 14, RFC 2119, March 1997. https://www.rfc-editor.org/rfc/rfc2119

**[RFC8174]**
: B. Leiba. *Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words.* BCP 14, RFC 8174, May 2017. https://www.rfc-editor.org/rfc/rfc8174

**[PARQUET]**
: *Apache Parquet Format.* https://parquet.apache.org/docs/file-format/

**[ICEBERG]**
: *Apache Iceberg Table Spec.* https://iceberg.apache.org/spec/

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.

### 17.2 Informative References

**[IMPLEMENTATION-PLAN]**
: *Congressional Document Archive: Implementation Plan.* Note, 2026-10-24. `docs/plans/simplification-plan-20261024.md`.
