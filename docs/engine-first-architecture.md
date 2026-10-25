# Congressional Document Archive: Architecture

**Editor's Draft, 2026-10-24**

## Abstract

This specification defines a system that captures congressional source documents, keeps them permanently, and publishes a static public explorer over them. The system has three layers: an append-only, content-addressed raw log; a lake of append-only tables derived from the log; and immutable releases produced by one deterministic SQL job over the lake. A single pointer selects the live release. One data engine (docspec-rs) does all data movement, joins, grouping and export; the application supplies fetchers, parsers, declarative SQL, registries and the site. This document specifies each layer's behavior, the publish process, the site, orchestration, the capabilities the engine must provide, security, verification and performance. Every schema, derivation, order and registry is defined once, in the companion specification [[DATA-MODEL]].

## Status of This Document

This is an Editor's Draft. It describes the target system independently of any current implementation. It is accompanied by [[DATA-MODEL]], which defines schemas, derivations and invariants, and by [[IMPLEMENTATION-PLAN]], a Note that orders the work from the current system to this one. Comments should be directed to the editor.

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

The system captures source documents published by Congress and related publishers, stores every fetched body permanently, and publishes a fast explorer that runs in a browser over static files. Only the raw log is precious: everything else is a pure function of raw data plus versioned code, SQL, registries and engine, and can be rebuilt at any time.

The three layers are:

1. **Raw log.** An append-only, content-addressed record of every fetch attempt, every body and every human decision. It is never rewritten.
2. **Lake.** Five append-only tables derived from the log: what was captured, what each body says (including the links on each page), what each filename says, and the committee and meeting records. Each row is computed once.
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

## 3. Terminology

**raw log**
: The objects under the `bodies/`, `receipts/` and `provenance/` prefixes of the raw bucket. The only layer that cannot be rebuilt.

**body**
: The original bytes of one HTTP response or archive member, identified by the SHA-256 of those bytes and stored once (§7.1).

**receipt**, **receipt line**
: An immutable file under `receipts/`, and one JSON record in it describing one fetch attempt or recovery import (§7.2).

**capture row**
: One row of the lake table `captures`: one body a receipt line references, or the line itself when it references none.

**endpoint**
: The pair `(context_url, member_path)`: the URL a body is evidence for, and its path inside an archive if it is an archive member.

**locator**
: The member path of an archive member, else the URL.

**url_key**
: The normalized URL every link join uses ([[DATA-MODEL]] §7.2).

**reading**
: One row of `readings`: what one parser version found in one body, including the links on a page.

**registry**
: A versioned list a rule depends on, such as the page shapes, error words or import runs ([[DATA-MODEL]] §7.1).

**model profile**
: The set of versions one publish reads: model SQL, engine, parsers, catalog, registries and writer settings ([[DATA-MODEL]] §7.1).

**record role**
: The classification of a body, such as `document`, `listing` or `caption` ([[DATA-MODEL]] §7.3).

**real file**, **real body**
: A capture row that passes the real-file rule, and a body with at least one ([[DATA-MODEL]] §7.3).

**placeholder**
: A body seen at so many pages that it connects nothing ([[DATA-MODEL]] §7.3).

**source file**
: One distinct `(body, effective filename, source URL)` triple, identified by `source_id`.

**document**
: One distinct content: a connected component of source files, identified by `document_id` ([[DATA-MODEL]] §7.5).

**listed document**
: A document with at least one real file or one recovery. Only listed documents appear in the explorer.

**saved file**, **alternate**
: The file a document's page links, and the files of its other formats ([[DATA-MODEL]] §7.5).

**rendition**
: One of several formats of one document, such as a bill's PDF and XML.

**edition-ambiguous endpoint**
: An endpoint that has served more than one distinct real body with different or no text ([[DATA-MODEL]] §7.5).

**import run**
: A bulk run that loaded older captures, listed in the import-run registry.

**document date**, **capture date**
: When a document is dated, and when the system first fetched one of its files ([[DATA-MODEL]] §7.5).

**link key**
: The 8-byte public identifier of a file, carried in links as 16 hex characters ([[DATA-MODEL]] §8.2).

**recovery**, **recovery import**
: Content imported for a link the publisher no longer serves directly, attached to that link as labeled evidence and never a real file; and the receipt line that records it.

**work list**
: The inputs a lake producer has not yet processed, found by an anti-join against the table's rows.

**completion row**
: A lake row recording that an input was processed and produced nothing.

**release**
: One immutable set of Parquet files and a manifest under `viewer-publications/releases/<release_id>/`.

**pointer**, **live release**, **last-good release**
: `viewer-publications/manifest.json`; the release it names as current; and the release it names as previous.

**input identity**
: The digest of every model input a publish run reads ([[DATA-MODEL]] §8.3).

**canary**
: The site's own reader module run in Node against an uploaded release candidate before the pointer is flipped.

**fold**
: A list of field-value pairs holding display-only facts ([[DATA-MODEL]] §4).

## 4. Principles

1. **Raw is the only truth.** Every other layer MUST be derivable from the raw log plus versioned code, SQL, registries and engine.
2. **Append or replace, never update.** Logs only grow. Derived outputs are recomputed and swapped atomically. No row is edited in place; catalog compaction rewrites files, not rows.
3. **Do expensive work once.** Every body is stored once and parsed once per parser version; every filename is read once per catalog version. Platform primitives (content addressing, conditional writes, Content-MD5, ETags, catalog commits) replace hand-built bookkeeping.
4. **Expensive cost grows with change, not with history.** Fetching, parsing and uploading grow with what is new. The accepted repeated work is named: capture re-fetches and re-hashes URLs on their recheck schedule; work-list anti-joins scan the keys already processed; the model recomputes every relation each run, `url_key` and meeting references included; the `fingerprint` producer evaluates the real-file rule once more before the pin; and the weekly check lists every body's metadata. None of them re-reads stored bodies.
5. **Engine first.** Data movement, joins, grouping, aggregation and export live in the engine. Application policy (ID formulas, field names, grouping rules, registries, parsers) is passed in as SQL, data and specs and MUST NOT be compiled into the engine.
6. **Nothing reaches users unverified.** A release goes live only after the site's own reader code has loaded it (§10.3.5).
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
| Listed documents | *est.* 0.5–0.7M ([[DATA-MODEL]] §7.5) |
| Normal day | a few thousand capture rows (3,553 from 2,946 receipt lines on 2026-10-16); 258–1,595 new bodies |
| Import day | up to 708,626 receipt lines (745,456 capture rows), 547k new bodies |
| Largest body | 1.19 GB; none above 5 GB |
| Bodies referenced by one receipt line | up to 22,354 |

At this scale, recomputing the model from the lake each run is cheaper than maintaining it incrementally: a narrow relational proxy ran in 3.7 s with 1.75 GB of memory, and connected components over the 4M-node graph took 1–2 s. Fetching, parsing bodies and reading filenames are the per-item work that is not repeated.

## 6. System Overview

*This section is non-normative.*

```
fetchers, recovery imports, review tools
        │  create-only writes
        ▼
RAW LOG (one bucket; locked prefixes)
  bodies/sha256/<aa>/<sha>                             stored bytes, keyed by SHA-256 of the original
  receipts/<family>/<write-date>/<run>-<seq>.jsonl.gz  one line per fetch attempt
  provenance/<kind>/<ts>.jsonl                         human and reviewed decisions
        │
        ▼  docspec-rs, Basin Catalog
LAKE (Iceberg, append-only)
  captures           one row per body a receipt line references   O(new receipts)
  readings           one row per (body, parser, version)          O(new bodies in scope)
  filename_readings  one row per (filename, URL, catalog)         O(new pairs)
  committee_records  one row per committee in an API response     O(new API bodies)
  meeting_records    one row per meeting in a meeting response    O(new meeting bodies)
        │
        ▼  docspec-rs: one SQL plan, deterministic export
RELEASE (immutable)
  viewer-publications/releases/<release_id>/<file>.parquet
  viewer-publications/releases/<release_id>/manifest.json
  viewer-publications/manifest.json   ← If-Match pointer, flipped after the canary
        │
        ▼
SITE (static) → pointer → release → list (whole) / detail, links, occurrences, recoveries (ranges)
```

All data lives in one Cloudflare R2 bucket. The lake tables are Iceberg tables in the bucket's Basin Catalog (the managed Iceberg REST catalog).

## 7. Raw Log

### 7.1 Bodies

Key: `bodies/sha256/<aa>/<sha>`, where `sha` is the SHA-256 of the original response bytes and `aa` its first two hex characters. Object details are in [[DATA-MODEL]] §5.1.

**Stored bytes.** Media types that compress (HTML, XML, JSON, text) are stored gzip-compressed with `Content-Encoding: gzip` and the original `Content-Type`. Already compressed types (PDF, images, archives) are stored as-is. Either way, an HTTP client that honors `Content-Encoding` receives the original bytes.

**Two digests.** The original's SHA-256 is the identity. The stored bytes' MD5 is the integrity check: R2 verifies it on upload and returns it as the ETag. No other digest is stored.

**Write.** For a body not already in the run's own set, the writer first checks whether the older copy `…/<sha>.gz` exists; if it does, the writer records the attempt as `unchanged` with suffix `.gz` and uploads nothing. Otherwise it MUST store the body with one create-only PUT (`If-None-Match: *`) carrying `Content-MD5`. Writers MUST NOT use multipart upload: multipart ETags are not MD5s, and no body approaches the 5 GB single-PUT limit. Every capture entry records the suffix its body is stored under.

**412 handling.** A 412 response means the body already exists. The writer MUST record the attempt as `unchanged` and move on, with no HEAD and no comparison. Over half of body-bearing attempts hit an existing body.

**Nothing is cut off.** The fetcher MUST spool each body to a temporary file so that any size up to the single-PUT limit is stored whole. The 201 bodies that older runs cut off at exactly 64 MiB stay in raw as evidence; they are never real files, and capture retries their URLs.

**Crash between a body and its receipt.** If a run stores a body and stops before writing its receipt, the body is kept and the weekly check finds it and re-hashes it once, but where it came from is not recorded. A later fetch of the same URL records it again if the content is unchanged. This loss of attribution is accepted.

**Older bodies.** Every body written before this specification sits at `…/<sha>.gz`. Older gzip PDFs gain a one-time uncompressed copy at `…/<sha>.pdf`, and the job that writes each copy records a verification record for both the source and the copy (§7.3). Existing bodies keep their stored form.

### 7.2 Receipts

A run writes one or more immutable numbered files at `receipts/<family>/<write-date>/<run>-<seq>.jsonl.gz`, keyed by the UTC write date. New writers MUST use date-shaped prefixes only. Older receipts also sit under `undated/` and `mixed-dates/` (49 files, 2.2M rows); only the backfill reads them.

Each line records one attempt ([[DATA-MODEL]] §5.2):

- requested URL, final URL, time, HTTP status and outcome;
- one entry per body it references (an archive's members are separate entries in one line, each with its path inside the archive), with the body's SHA-256, the server's media type, the sniffed format, the stored suffix, and, on the line that stored the body, the stored MD5 and size;
- an allowlisted set of response headers; cookies and authorization MUST NOT be recorded;
- writer identity: job, code commit, lockfile digest and run ID.

Links are not recorded: they are derivable from the body, and the page's reading holds them (§8.3). Receipts are the authoritative history of what was captured and when. A run MUST write each receipt file create-only and after the bodies its lines reference, so every receipt line points at a body that exists.

**Recovery imports** write receipts too. Their lines carry `mode: retained_import`, a synthetic HTTP 200, the recovery category and the original link the content recovers.

### 7.3 Provenance

`provenance/<kind>/<ts>.jsonl` holds every decision a person or a reviewed process makes about sources, as append-only timestamped records: accepted URL variants, recovery decisions, document reviews and verification results ([[DATA-MODEL]] §5.3). A correction MUST be a new record that supersedes an old one by ID; old records are never edited.

### 7.4 Protection and Verification

**Lock.** An indefinite R2 bucket lock covers `bodies/`, `receipts/` and `provenance/`; it is what stops deletion and overwrite (§14).

**Weekly check.** One LIST of `bodies/` (about 1,300 list requests once the `.pdf` copies exist), joined to the recorded keys of `captures` and the verification records, confirms that every recorded key exists and that every stored body has the size and MD5 recorded for it. It reads no body bytes, except that it downloads 25 random bodies and checks their SHA-256 end to end, and re-hashes once any body with no creating line. There is no daily re-hash and no per-body HEAD.

**Full re-hash** is an explicit job. It runs once for bodies written before receipts carried an MD5, skips keys that already have a verification record, and records the rest under `provenance/verification/`. After that it runs only before a migration.

**Durability.** Raw is kept in one R2 bucket with no second copy. The lock guards against deletion and overwrite by any credential; R2's own durability guards against hardware loss. A provider-side loss is the accepted risk.

## 8. Lake

### 8.1 Common Rules

All lake tables are Iceberg tables in the bucket's Basin Catalog, with the types, properties and writer settings of [[DATA-MODEL]] §4 and §6. Every commit MUST carry its requirements (table UUID and current snapshot), so concurrent writers fail rather than overwrite each other.

**Conflict retry.** Basin's own maintenance commits to the same tables, so an append can lose a race. On a conflict the producer MUST reload the table, recompute its work list against the new snapshot, and commit only the rows still missing, reusing rows it has already computed. It retries at most three times. It MUST NOT commit rows the new work list no longer needs, which would duplicate rows when two runs ingest the same receipts. Files from a losing attempt become orphans (§8.7).

**Completion rows.** A producer whose work list is "inputs with no rows yet" MUST write a completion row for an input that produced nothing, in the same commit as its outputs ([[DATA-MODEL]] §6).

**Work lists.** Every producer finds its work by an anti-join of its inputs against the rows it already holds. A daily run appends once; a backfill appends once per batch, so it always resumes.

**Sort order.** Nothing depends on the physical sort order of a lake table, because compaction may not keep it.

### 8.2 `captures`

One row per body a receipt line references, plus one line-only row for each line that references none, so no attempt loses its status ([[DATA-MODEL]] §6.1). Recovery imports keep their identity as columns.

**Ingest.** For each receipt family, list only date-shaped prefixes, starting from the newest date already ingested; anti-join against ingested receipt keys; append the missing receipts in one commit. Listing cost grows with new receipts, not with all of them. The backfill reads the non-date segments once. The weekly check lists everything and appends anything a late receipt left behind.

**Rebuild check.** Rebuilding from all receipts MUST reproduce the same set of rows.

### 8.3 `readings`

One row per `(body, parser, parser_version)` ([[DATA-MODEL]] §6.2). Each media family has its own parser and version, so a new HTML parser never re-reads a PDF. Parsers record facts (format, titles, text sizes, link counts, a content date, a fingerprint, and the links on a page); the model classifies those facts with registries, so changing a registry never re-parses a body.

- **Every body has a sniffed format.** The fetcher records it for new bodies, with the sniff code's version. A `sniff` parser reads every body without a sniff at the pinned version, with one ranged read of its first bytes. The server's media type MUST NOT be used instead.
- **HTML, XML and JSON** are read in full, once per version. The HTML and XML parsers emit each page's links in the same pass, so link context covers all history, not just new captures, and a page fetched many times stores its links once.
- **PDF, ZIP containers and captions** get no full reading for now. Full-text extraction of every PDF (about 403 GB) is deferred to its own table, `pdf_text`. ZIP members are captured as their own entries.
- **Text fingerprints, for candidates only.** The `fingerprint` parser reads the bodies at endpoints that served two or more distinct real files (about 300 bodies). Its work list comes from the real-file rule over the current lake, so it runs last among the lake steps (§12). There is no full-corpus text pass.

**Versions.** The model reads only the versions the model profile pins. A new parser version is backfilled in background batches while the profile still pins the old one; the profile moves when the new version's work list is empty ([[DATA-MODEL]] §7.1).

### 8.4 `filename_readings`

One row per `(filename, source_url, catalog_version)`, holding what `house-naming` extracts from a filename, as typed facets and keys plus a fold ([[DATA-MODEL]] §6.3). Filename readings depend on the filename and the source URL, not the body, so they cannot live in `readings`. The producer computes each source file's effective filename itself, so its work list depends on raw and provenance only. A new catalog version is one background job over about 1.39M pairs.

### 8.5 `committee_records`

One row per committee in a Congress.gov committee API response, so pages can show committee names instead of codes ([[DATA-MODEL]] §6.4). The committee fetcher MUST fetch through the raw writer like every other fetch, so names derive from raw.

### 8.6 `meeting_records`

One row per meeting in a meeting response, from the Congress.gov meeting JSON, its XML fallback and the House and Senate meeting inventories, all fetched through the raw writer ([[DATA-MODEL]] §6.5). Hearing pages take their title, date, type and committee from it.

### 8.7 Maintenance

Basin Catalog maintains the tables: compaction (target 128 MB) and snapshot expiration (older than 30 days, keep the last 5), enabled per table. Expiration deletes the data files that only expired snapshots referenced, which the table properties permit ([[DATA-MODEL]] §6). At about 315 KB of appends a day, compaction volume is a few GB a month.

**Orphans.** Basin does not remove files that no snapshot ever referenced, such as the data file of a lost commit race. The weekly check reports their bytes; cleanup waits until that number matters.

**Fallback.** The lake depends on compaction keeping the number of manifests in the current snapshot bounded. If it does not, the lake tables move to dated Parquet files with an `If-Match` manifest per table, which gives the same atomicity without time travel.

## 9. Model

*This section is non-normative. It explains the model's intent; [[DATA-MODEL]] §7 defines every rule.*

### 9.1 One Plan

The domain model is versioned SQL in the application repository. One engine job registers the lake tables, the provenance records and the registries at the versions the model profile pins, evaluates one plan, and writes the release files. There are no intermediate tables. The ID formulas keep today's exact inputs and serialization, so `source_id` and `document_id` match the current system byte for byte. Public links do not depend on `document_id` (§10.1), so an ID that changes when a version joins a group costs nothing.

### 9.2 What Counts as a File

A document is one distinct content, and its files are the real files with that content. A real file is a complete, successful, real fetch of a non-empty body whose record role is `document`. Any content format counts: PDF, ZIP, document XML, web pages, Word, web archives, images and text. Captions, playlists, API responses, metadata records, error pages and listing pages (hearing indexes, press-release lists) do not. For HTML, a link that points at a file means the HTML response is not the file, and generic error signs mark error pages; there are no site-specific templates. Roles come from the sniffed format and the readings, never from the server's `Content-Type`. Archive members are judged by their own path.

Everything that is not a real file stays in raw and the lake as evidence. It never enters a document, so it never changes a document's ID, saved file or links; it still drives `url_state`, and listing pages still supply link context.

### 9.3 Grouping

Source files connect when they share a real body (the same page saved at several addresses is one document), when one endpoint served re-packaged bytes with equal text, when the publisher lists them together as formats of one document, and when a reviewer merges them. Connections chain. A new edition is a new document: a body that ever shared an address with a different edition is never paired with other formats, so mirrors cannot merge editions transitively. Several files of one format listed together stay separate documents. Placeholders connect nothing.

Files connect through one node per body, fingerprint or rendition group, so a group of n files costs n edges, not n². Grouping runs in memory over 32-bit IDs and refuses above a configured node count; the parent array is 16 MB at 4M nodes, and assigning dense IDs is a hash aggregation of a few hundred MB, which sizes the memory pool.

### 9.4 Saved File and Dates

A document's page links its PDF when it has one, then its newest file; other formats are alternates, and a link to any rendition opens the same entry. A recovery-only document's saved file is its recovery, labeled as one.

Two dates each say what is known. The document date comes from the filename, else the contents, else the meeting the document belongs to, and is never a guess among several dates; the page says which source it came from. The capture date is when the system first fetched a file: "Captured <date>" for a real fetch, "In our archive since <date> (original capture date not recorded)" for files known only from an import run, and "Capture date not recorded" when there is none. Editions with the same filename sit together in date order.

### 9.5 Meetings, Committees and Record Keys

Each source file gets a meeting reference (chamber, event ID) from its URL, from a meeting page that linked it, or from a House meeting XML record's document list. House and Congress.gov meeting IDs are one ID space, the same event ID the committee explorer uses, so a page can list every document for a hearing under the hearing's title, date, type and committee. Official record keys (the GovInfo package, bills, member Bioguide IDs) let a page link out to the GPO record, the bill and the member. House-naming committee codes map to Congress.gov system codes, so facets and pages show committee names.

### 9.6 Recoveries and Reviews

A recovery is evidence for its original link, never a file the recovering URL served, so it stays out of `url_state`, text comparison, link keys and capture dates. It attaches to the one listed document that holds its original link; when none does, or the link came back as different editions, it keeps a page of its own. Either way it is labeled by kind with its evidence.

A review targets a link key, so it follows a file through merges and splits. `duplicate_of` merges two documents; `hide` keeps a document's links resolving but removes it from search and facets and shows a "removed by review" note; overrides replace a displayed title or kind.

### 9.7 URL Normalization

Joins between links, recoveries and source files use `url_key`, which unwraps redirect and archive wrappers and drops differences that never select a different file (scheme, `www.`, trackers, known page state). Identity keeps the exact URL.

## 10. Releases

### 10.1 Release Files

The release files are written by the model's job. The site reads six of them, linked by the list row number; columns, orders, writer settings and sizes are in [[DATA-MODEL]] §8.1.

| File | Purpose | How it is read |
|---|---|---|
| `list.parquet` | Search, facets and sorting | Downloaded whole, decoded column by column in a Web Worker |
| `detail.parquet` | Everything a document page acts on | One page per leaf column, located by the offset index |
| `links.parquet` | Public link key to list row | Point lookup through the column index's page statistics |
| `occurrences.parquet` | Where each copy was seen, and which page linked it | The range named in `detail` |
| `recoveries.parquet` | A document's recoveries | The range named in `detail` |
| `meetings.parquet` | Hearing titles, dates, types and committees | Read whole when a hearing is shown |
| `url_state.parquet` | Capture's schedule and queue | Read whole by the capture job, not the site |

- **Documents only.** There are no per-copy pages. A document page shows its saved file, its alternates, its dates, its readings, its recoveries, and where each copy was seen and which page linked it.
- **Links point at a file.** A document's ID changes whenever a version joins its group; a file's fingerprint never changes. A public link therefore carries a link key, and `links` maps every real body of every listed document to its document's row, so old links keep resolving when the group or its saved file changes. A recovery's original link gets a key of its own, so a recovery-only page keeps its link after the original finally downloads.
- **No ID in `list`.** The list carries no document ID, which would make it several times larger; the list row number links the files.
- **Detail reads.** The reader fetches `detail`'s offset index once per session; after that a detail view is one round trip of about 19 concurrent page reads. The typed core holds everything the site acts on, so the reader never parses packed strings; the fold holds the hundred-odd display-only fields that would otherwise cost a page each.
- **Binary keys** everywhere except `list`; the reader adds a body's suffix and hex-encodes it.
- **Shards.** The export adds row-range shards to `detail` and `occurrences` when an offset index outgrows a quick first fetch, at roughly 10 times today's rows.
- **Ceiling.** At about 10 times today's catalog rows, `list` reaches 40 MB and downloading it whole stops being reasonable. Then `list` is sharded by facet, or search moves to DuckDB-WASM or a server.

### 10.2 Determinism

Identical inputs MUST produce byte-identical files, so reruns are idempotent and the "nothing changed" check is exact. The engine enforces it:

- every sort key MUST be unique, or the export refuses;
- partition order is fixed;
- the export re-batches its input to the pinned write batch and flushes row groups on fixed row counts, whatever the upstream batch sizes or spills;
- writer properties and the `created_by` string are pinned;
- no timestamps or run-specific values go into content.

Tests compare bytes across thread counts, input orders, batch sizes and a forced spill. Determinism is not a dedupe mechanism: one new document shifts every later row number, so on any day with a change every file changes.

### 10.3 Publish

#### 10.3.1 Pinned Snapshots and Input Identity

After the lake steps of §12, a publish run MUST pin the current snapshots once, refuse if any version the model profile pins is incomplete at them, compute the input identity from them ([[DATA-MODEL]] §8.3), and run the model against the same snapshots.

#### 10.3.2 Early Skip

If the input identity equals that of any input record of the live release, publish stops before the model runs. A review decision, a registry change or a SQL change therefore publishes without waiting for a capture.

#### 10.3.3 Release ID

The release ID is the SHA-256 of the file list (name, SHA-256, size, rows) and the schema version, computed after export and before upload. If it equals the live release's, publish records the new input identity and stops. An empty `list` MUST NOT be published.

#### 10.3.4 Upload

Files are uploaded to `viewer-publications/releases/<release_id>/` with a create-only PUT and `Content-MD5`. A 412 on a rerun MUST be checked against the expected MD5 with one HEAD of that object's ETag.

`releases/<release_id>/manifest.json` holds only content, so a release that re-emerges writes identical bytes. `releases/<release_id>/inputs/<input_digest>.json` records each input identity that produced the release, with the pinned snapshot IDs and the run.

#### 10.3.5 Canary

The site's own reader module runs in Node against the uploaded candidate over HTTPS, so Range reads and caching headers are real. It decodes `list` within a heap budget for a mid-range phone, runs a search and a facet count, reads the first, last and a random detail, resolves a link, reads an occurrence range and a recovery range, opens one saved copy, and checks that `url_state` decodes. It takes under a minute and needs no headless browser.

#### 10.3.6 Flip

The flip writes the candidate as the pointer's `release_id` and the outgoing live release as its `previous_release_id`, with `If-Match` on the pointer's current ETag. A failed canary or a lost race leaves the previous release live. Release files and manifests are cached as immutable; the pointer is `no-store`.

#### 10.3.7 Concurrency and Retention

Publish and the weekly maintenance job run in one CI concurrency group, so they never overlap; that group is what keeps retention from deleting a release a publish run is about to make live (§12). Publish MUST NOT delete anything.

From the second flip on, at least two releases exist: the live release and the last-good release. The weekly job re-reads the pointer just before it deletes, takes both release IDs from it, then removes prefixes under `viewer-publications/releases/` that are neither live nor last good and are more than a day old. Failed candidates go the same way. Up to a week of daily releases (about 0.7 GB) can sit there in between. Releases share no files, so nothing needs reference counting.

## 11. Site

### 11.1 Reads

The site reads pointer → release manifest → `list`, then `detail`, `links`, `occurrences`, `recoveries` and `meetings` as needed. Search and facet filtering run in a Web Worker over `list`, decoded column by column into arrays and dictionary codes, because objects would cost hundreds of MB of heap on a phone. Details and ranges use HTTP Range reads through hyparquet's offset-index page reads (`useOffsetIndex`); link lookups also use its column index (`usePageIndex`). Long occurrence ranges are read a page at a time.

### 11.2 Devices and Speed

The site targets desktop and mid-range phones. The contract test and the canary enforce a heap budget. There is no per-view byte budget. Speed targets (startup, search and detail times, and the heap budget) are measured on real phones and desktops, then fixed as targets the canary and contract test check.

### 11.3 Stale Tabs

Only the live and last-good releases are sure to exist, so a tab left open across two publishes can lose its files. On a 404 for a release file, the reader MUST re-read the pointer and reload.

### 11.4 One Reader and Its Contract

The reader is a plain module with no DOM dependency, so the canary runs the same code the site ships. The release manifest carries a `schema_version`; the reader MUST accept the current and the previous version, so format changes ship reader-first, then publisher.

### 11.5 Saved Copies

- A saved file opens at its physical key: `saved_body` plus `saved_suffix` ([[DATA-MODEL]] §7.5).
- Bodies written to §7.1 open directly, and older gzip PDFs open their uncompressed `.pdf` copy once it is recorded.
- Other `.gz` bodies are fetched and unpacked by the site with the browser's `DecompressionStream`, then opened with the media type from `detail`. Those over 100 MB (579 of them, up to 1.19 GB) are offered as a labeled compressed download instead.
- A document whose content is a recovery labels it by kind and links the recovered file.
- A link key that no longer resolves opens a not-found notice.

### 11.6 Origin

`congressional-data.spicygov.ai` serves the bucket directly with a read-only, any-origin CORS policy (GET/HEAD, Range), immutable cache headers on release files, a content security policy and the `?filename=` download rule. There is no custom-domain path allowlist: `r2.dev` serves every key anyway.

## 12. Orchestration

```
capture:     live url_state → fetchers → bodies → receipts             (daily; network-bound)
publish:     captures → readings, filename_readings, committee_records,
             meeting_records → fingerprint
             → pin snapshots → input identity → early skip
             → model + export → canary → flip → status                  (after capture, or on demand)
maintenance: raw check and sample → release retention → orphan report   (weekly)
backfill:    readings or filename_readings for a new version            (on demand)
```

- **Order.** The lake steps run first, each on its own work list, with `fingerprint` last because its work list comes from the real-file rule. Then publish pins, checks and models (§10.3).
- **Idempotent steps.** Each step is keyed by its input and is a no-op when that has not changed. Each step commits durably, so a failed run resumes by running again. There are no journals.
- **Capture reads the public release.** It builds its queue from the live release's `url_state`, so it needs no lake or release credentials. If a canary has failed, capture works from a slightly older schedule, which is safe because body writes are create-only.
- **Separate credentials.** Capture, publish and maintenance run as separate jobs with separate credentials.
- **Pinned engine.** The engine binary is pinned by revision and digest and MUST be checked before any storage access.
- **Resources.** Resource limits (threads, memory pool, scratch) are explicit per runner class. The memory pool MUST NOT exceed the machine.
- **Status.** Every publish run writes `viewer-publications/status.json`: input identity, rows per output, durations, bytes and the live release.
- **Local runs.** The same commands run locally or in CI. Correctness MUST NOT depend on a CI feature, with one exception: publish and maintenance rely on their shared concurrency group (§10.3.7), so whoever runs either outside CI MUST NOT run it while the other runs.

## 13. Engine Capabilities

The engine (docspec-rs) MUST provide:

1. **Multi-input SQL plans** over Iceberg tables in Basin Catalog and Parquet files, in one DataFusion context.
2. **Append** through the REST catalog, always sending commit requirements, with the conflict retry of §8.1.
3. **Deterministic multi-file export:** SHA-256 and MD5 computed while writing; per-file writer settings, including offset and column indexes, page sizes, page row limits and per-column encodings; fixed row counts per row group; unique sort keys; row-range shards; and the rules of §10.2.
4. **Connected components** in memory over 32-bit IDs, refusing above a configured node count.
5. **Streaming I/O.** No re-read of a just-written object and no HEAD of immutable files, except as §7.1 and §10.3.4 allow. File and row-group sizes come from table properties and writer settings ([[DATA-MODEL]] §6, §8.1).
6. **Bounded resources** set by configuration: compute threads, memory pool and scratch space. Sorts and aggregates spill or fail clearly within the pool. Hash-join builds do not spill, so plans keep wide columns off the build side: join on keys first, reduce, then attach the wide column.
7. **A thin interface:** a library plus a CLI that runs a declarative job spec (inputs, SQL, outputs, export settings) and returns a machine-readable result.

The engine MUST NOT contain: application policy (ID formulas, field names, grouping rules, registry values); parsers for bodies or filenames; table maintenance, which Basin Catalog does; bookkeeping that duplicates Iceberg; resume machinery beyond per-step commits; or test-only production paths.

Iceberg is used only to read and append. If replace or branching is ever needed, it is added upstream to iceberg-rust rather than worked around.

## 14. Security

- **Raw:** create-only writers plus the bucket lock on raw prefixes.
- **Credentials.** R2 tokens scope object permissions to buckets, never to prefixes, so any writing token can also delete unlocked keys. Capture, publish and maintenance use separate tokens, so each can be revoked on its own; only maintenance deletes release prefixes.
- **One bucket.** Raw isolation rests on the lock plus create-only writers.
- **Public data.** Everything stored is public records and is readable publicly.
- **Receipts** carry allowlisted headers only (§7.2).

## 15. Verification

1. **Data-model invariants:** the invariants of [[DATA-MODEL]] §10, as tests over the raw log, the lake, the model's relations and each release.
2. **Rule accuracy:** a hand-labeled sample of a few hundred files measures how often the page-shape, error-sign, listing-page, placeholder and rendition rules wrongly include, exclude or join a file.
3. **Registry samples:** every registry entry's sample passes its test.
4. **Determinism:** byte-identical exports across thread counts, input orders, batch sizes and a forced spill (§10.2).
5. **Contract:** CI builds a release from a fixed sample of real receipts and loads it through the real site in a headless browser, within the heap budget.
6. **Canary:** the reader module in Node against the uploaded candidate before every flip (§10.3.5). Both the canary and the contract test check that a 404 on a release file makes the reader re-read the pointer and reload.
7. **Ratchets:** no test-only branches in production code, and no application identifiers (committee codes, family names, registry values) in the engine crate.

## 16. Performance

### 16.1 Cost Bounds

*This section is non-normative.*

| Step | Cost | Expected |
|---|---|---|
| Capture | O(new attempts), network | Bounded by politeness to sources |
| Captures ingest | O(new receipts) to read; the work list scans the keys already ingested | Seconds |
| Readings | O(new bodies in scope × parse cost) | Minutes daily; backfills in background |
| Filename readings | O(new pairs) | Under a second daily; 7–18 minutes per catalog version |
| Model + export | O(N log N) sorting plus scans and joins over every row; linear grouping | Seconds for the narrow plan |
| Publish | O(release size) | About 105 MB of uploads on a day with changes |
| Detail view | One page per leaf | About 19 page reads, 70–90 KB, in one round trip after a one-time offset-index fetch |
| Weekly check | O(history) object metadata | About 1,300 list requests, no body bytes |

A normal day moves about 1,500 object operations and 2 GB, well inside R2's free tier at today's scale and at 10 times it.

### 16.2 Validate Before Building

*This section is non-normative.*

[[IMPLEMENTATION-PLAN]] §5 measures Basin Catalog commits, the full model and export, grouping on the real graph, and determinism, in the engine on the smallest production runner class, before the lake and model are built on.

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
