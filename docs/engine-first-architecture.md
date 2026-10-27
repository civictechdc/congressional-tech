# Congressional Document Archive: Architecture

**Editor's Draft, 2026-10-24**, of the target system, independent of any current implementation.

## Abstract

- **Decides** the behavior of a system that captures congressional source documents and publishes a static public explorer over them: raw writing (§7), the lake (§8), the model's intent (§9), publish (§10), the site (§11), orchestration (§12), the engine (§13), security (§14) and verification (§15).
- **Goals:** keep every fetched body permanently, so everything else can be rebuilt from it; grow expensive work with change, not history: the lake only appends, and only the model is recomputed each publish; show users only verified releases (§4).
- **Raw:** each body stored once under its SHA-256 by a create-only PUT, with append-only receipts and provenance, under a bucket lock (§7); lake tables are append-only, each row computed once per input and version (§8).
- **One job publishes:** one deterministic SQL job over the lake writes an immutable release, and the pointer flips to it only after the site's own reader has loaded it (§10).
- **Engine first:** docspec-rs does all data movement, joins, grouping and export, and holds no application policy; the application supplies fetchers, parsers, SQL, registries and the site (§13).
- **Detail:** [[DATA-MODEL]] holds every schema, derivation, order, registry and invariant; [[IMPLEMENTATION-PLAN]] holds the order of work, the measurements still to run and the open uncertainties.

## 1. Introduction

*This section is non-normative.*

Sources are Congress and related publishers; the explorer is fast and runs in a browser over static files. Only the raw log is precious: it records every fetch attempt, every body and every human decision, and is rewritten only by the one-time receipt cleanup (§7.2). The lake and the releases can be rebuilt from it at any time (§6).

## 2. Conformance

Sections marked "This section is non-normative", and all diagrams and examples, are non-normative. Everything else is normative.

The key words MAY, MUST, MUST NOT and SHOULD in this document are to be interpreted as described in BCP 14 [[RFC2119]] [[RFC8174]] when, and only when, they appear in all capitals, as shown here.

Five conformance classes each conform by meeting the requirements that apply to them, here and in [[DATA-MODEL]]:

- **raw writer**: fetchers, recovery imports and review tools that write the raw log (§7);
- **lake producer**: the jobs that append lake tables (§8);
- **publisher**: the job that evaluates the model and publishes releases (§9, §10);
- **reader**: the site and the canary (§11);
- **engine**: docspec-rs (§13).

## 3. Terminology

[[DATA-MODEL]] §3 adds the primitives its rules use, such as source URL, attempt and fingerprint candidate.

**raw log**
: The objects under the `bodies/`, `receipts/` and `provenance/` prefixes of the raw bucket; the only layer that cannot be rebuilt.

**body**
: The original bytes of one HTTP response or archive member, identified by their SHA-256 and stored once (§7.1).

**receipt**, **receipt line**
: An immutable file under `receipts/`, and one JSON record in it describing one fetch or recovery import (§7.2).

**capture row**
: One row of the lake table `captures`: one body a receipt line references, or the line itself when it references none.

**endpoint**
: `(context_url, member_path)`: the URL a body is evidence for and, for an archive member, its path inside the archive. A member's position in the archive is evidence, not identity, so a repacked archive keeps its endpoints.

**locator**
: An archive member's path, else the URL.

**url_key**
: The normalized URL every link join uses ([[DATA-MODEL]] §7.2).

**reading**
: What one parser version found in one body, including a page's links: one row of `readings`.

**registry**, **model profile**
: A versioned list a rule depends on; and the pinned set of versions one publish reads ([[DATA-MODEL]] §7.1).

**record role**
: A capture row's classification, such as `document`, `listing`, `wrapper` or `caption` ([[DATA-MODEL]] §7.3).

**real file**, **real body**, **placeholder**
: A capture row that passes the real-file rule; a body with at least one real file; a body seen at so many pages that it connects nothing ([[DATA-MODEL]] §7.3).

**source file**
: One distinct `(body, effective filename, source URL)` triple, identified by `source_id`.

**document**, **listed document**
: One distinct content, a connected component of source files identified by `document_id`; and a document with at least one real file or recovery, the only kind the explorer shows ([[DATA-MODEL]] §7.5).

**saved file**, **alternate**, **rendition**
: The file a document's page links; the files of its other formats; one of several formats of one document, such as a bill's PDF and XML ([[DATA-MODEL]] §7.5).

**edition-ambiguous endpoint**
: An endpoint that has served more than one distinct real body with different or no text ([[DATA-MODEL]] §7.5).

**import run**
: A bulk run that loaded older captures, listed in the import-run registry.

**witness appearance**, **witness key**
: One witness a source lists for one occasion (a meeting, a Senate hearing page or a printed hearing); and its 8-byte key, from that occasion and the recorded name, which a later witness table keys on ([[DATA-MODEL]] §6.7, §7.11). A printed hearing that exactly one meeting names is that meeting's occasion.

**document date**, **capture date**
: When a document is dated, and when the system first fetched one of its files.

**link key**
: The 8-byte public identifier of a file, carried in links as 16 hex characters ([[DATA-MODEL]] §8.2).

**recovery**, **recovery import**
: Content imported for a link the publisher no longer serves directly, attached to that link as labeled evidence; and the receipt line that records it.

**work list**
: A lake producer's unprocessed inputs, found by an anti-join against its rows; every input leaves a row, even one that produced nothing.

**release**, **pointer**, **live release**, **last-good release**
: One immutable set of Parquet files and a manifest under `viewer-publications/releases/<release_id>/`; `viewer-publications/manifest.json`; the release it names as current; and the one it names as previous.

**input identity**
: The digest of every model input a publish run reads ([[DATA-MODEL]] §8.3).

**canary**
: The site's own reader module, run in Node against an uploaded release candidate before the pointer flips.

**maintenance job**
: The weekly job that checks raw, applies release retention and drops superseded lake tables (§7.4, §8.6, §10.3.7).

**fold**
: A list of field-value pairs holding display-only facts ([[DATA-MODEL]] §4).

## 4. Principles

1. **Raw is the only truth.** Every other layer MUST be derivable from the raw log, and from the pinned spicy-regs reference generations whose raw records spicy-regs keeps, plus versioned code, SQL, registries and engine.
2. **Append or replace, never update.** Logs only grow. Derived outputs are recomputed and swapped atomically; catalog compaction rewrites files, not rows.
3. **Do expensive work once.** Every body is stored once and parsed once per parser version; every filename is read once per catalog version. Platform primitives (content addressing, conditional writes, Content-MD5, ETags, catalog commits) replace hand-built bookkeeping.
4. **Expensive work grows with change, not with history.** Fetching new URLs, parsing and storing grow with what is new. The repeated work that remains is named in §16 and never re-reads stored bodies.
5. **Engine first.** Data movement, joins, grouping, aggregation and export live in the engine. Application policy is passed in as SQL, data and specs and MUST NOT be compiled into the engine (§13).
6. **Nothing reaches users unverified.** A release goes live only after the site's own reader has loaded it (§10.3.5).
7. **Small bytes.** Keys and facts are stored once, as typed columns, hashes as binary. Provenance is never copied into derived rows, and nothing derivable is stored. Browser files are the one place where shape follows the reader, and they carry only what a reader acts on; forensic detail stays in the lake, and a model run at a release's pinned inputs reproduces any grouping (§10.1).
8. **Components behind contracts.** Each component (§6) depends only on the contracts of the components it uses. Policy is injected as registries and the model profile; external systems (the object store, local disk, fetch transports, the catalog) are injected as adapters. Any implementation that passes a component's contract tests may stand behind it, and tests run the production code against local adapters (§15).
9. **Rules follow the data.** Every content rule cites the measurement that set it, and a rule is changed by measuring again, not by argument.

## 5. Scale

*This section is non-normative.*

These figures, measured on the 2026-10-19 snapshot, size what an implementation must handle:

| Quantity | Measured |
|---|---|
| Receipt lines, capture rows | 2.6M lines in 2,289 receipt files; 3.9M capture rows |
| Distinct bodies | 1.04M, 0.70 TB stored (PDF 365 GB, ZIP 286 GB, untyped 37 GB, HTML 4.5 GB, XML 0.8 GB) |
| Distinct URLs | 1.16M |
| Source files | 1.68M |
| Listed documents | *est.* 0.5–0.7M |
| Normal day | a few thousand capture rows (3,553 from 2,946 receipt lines on 2026-10-16); 258–1,595 new bodies |
| Import day | up to 708,626 receipt lines (745,456 capture rows), 547k new bodies |
| Largest body | 1.19 GB; none above 5 GB |
| Bodies referenced by one receipt line | up to 22,354 |

At this scale, recomputing the model from the lake each run is cheaper than maintaining it incrementally: a narrow relational proxy ran in 3.7 s with 1.75 GB of memory, and connected components over the 4M-node graph took 1–2 s.

## 6. System Overview

*This section is non-normative.*

All data lives in one Cloudflare R2 bucket; the lake tables are Iceberg tables in its Basin Catalog (the managed Iceberg REST catalog).

```
fetchers, recovery imports, review tools
        │  create-only writes
        ▼
RAW LOG (one bucket; locked prefixes)
  bodies/sha256/<aa>/<sha>                             stored bytes, keyed by SHA-256 of the original
  receipts/<family>/<write-date>/<run>-<seq>.jsonl.gz  one line per fetch
  provenance/<kind>/<ts>.jsonl                         human and reviewed decisions
        │
        ▼  docspec-rs, Basin Catalog
LAKE (Iceberg, append-only)
  captures           one row per referenced body or bodiless line O(new receipts)
  readings           one row per (body, parser, version)          O(new bodies in scope)
  filename_readings  one row per (filename, URL, catalog)         O(new pairs)
  meeting_records    one row per meeting in a meeting response    O(new meeting bodies)
  appearance_records one row per witness at a meeting or hearing   O(new meeting and MODS bodies)
        │
        ▼  docspec-rs: one job of named SQL steps, deterministic export
        ◀  pinned spicy-regs generations: committees, members, terms, rosters, bills
RELEASE (immutable)
  viewer-publications/releases/<release_id>/<file>.parquet
  viewer-publications/releases/<release_id>/manifest.json
  viewer-publications/manifest.json   ← conditional pointer, flipped after the canary
        │
        ▼
SITE (static) → pointer → release → list (whole) / detail, links, sources, recoveries (ranges)
```

**Components.** Each component has a contract in this specification and [[DATA-MODEL]], and a contract suite written from it; a lake producer's suite is the [[DATA-MODEL]] §10 invariants for its table. Which implementation stands behind a component is recorded outside the specifications.

| Component | Class | Contract | Injected adapters |
|---|---|---|---|
| Fetcher | raw writer | §7.1; DM §5.2 | direct transport, fetching provider |
| Body store | raw writer | §7.1; DM §5.1 | R2, local disk |
| Receipt writer | raw writer | §7.2; DM §5.2 | body store |
| Archive expander | raw writer | §7.2 | — |
| Recovery importer | raw writer | §7.2–7.3; DM §5.2–5.3 | body store, receipt writer |
| Review recorder | raw writer | §7.3; DM §5.3, §7.9 | body store |
| Capture scheduler | raw writer | §12; DM §7.7 | fetcher, release reader |
| Raw verifier | raw writer | §7.4 | object store |
| Captures ingest | lake producer | §8.2; DM §6.1 | engine |
| Parsers (sniff, html, xml, json, fingerprint) | lake producer | §8.3; DM §6.2 | engine, object store |
| Filename reader | lake producer | §8.4; DM §6.3 | engine |
| Meeting parsers | lake producer | §8.5; DM §6.5, §6.7 | engine |
| Model | publisher | §9; DM §7 | engine, registries, model profile |
| Publish job | publisher | §10; DM §8 | engine, object store, canary |
| Reader | reader | §11 | HTTP range client |
| Site pages | reader | §11.5–11.6 | reader |
| Canary and contract test | reader | §10.3.5, §15 | reader |
| Engine | engine | §13 | catalog, object store |

## 7. Raw Log

Raw writers only create objects, and fetchers stay inside the capture scope; the bucket lock stops deletion and overwrite (§7.4).

### 7.1 Bodies

Each fetched body is stored once, at `bodies/sha256/<aa>/<sha>` ([[DATA-MODEL]] §5.1). `sha` is the SHA-256 of the response entity after its transfer `Content-Encoding` is removed (the bytes a user would save, so a change of compression is not a new body), and `aa` its first two hex characters.

**Fetching.** Fetchers MUST refuse private, loopback and link-local hosts, credentials in a URL's authority, and URLs outside the capture-scope registry ([[DATA-MODEL]] §7.1), checked as an allowlist on every hop of every transport, and MUST follow at most six redirects. They pace and back off per host as the host-pacing registry says. They honor `Retry-After` within the run; the receipt records it, so later runs honor its deadline too, within the family's recheck interval ([[DATA-MODEL]] §7.7). A fallback through a fetching provider records the direct try in `prior_attempts` and the provider's status apart from the publisher's; every attempt records its own status and completeness.

**Stored bytes** are compressed as [[DATA-MODEL]] §5.1 says, so an HTTP client that honors `Content-Encoding` receives the original bytes. R2 verifies the stored bytes' MD5 on upload and returns it as the ETag, the integrity check; the original's SHA-256 is the identity.

**Write.** For each body it fetches, the writer:

1. uploads nothing if the body is already in the run's own set;
2. else checks with one HEAD whether the older copy `…/<sha>.gz` exists, and if so records the attempt as `unchanged` with suffix `.gz`;
3. else MUST store the body with one create-only PUT (`If-None-Match: *`) carrying `Content-MD5`. A 412 means the body exists: the writer MUST record the attempt as `unchanged` with suffix `''`, with no HEAD, download or comparison.

Every capture entry records the suffix its body is stored under. Writers MUST NOT use multipart upload: multipart ETags are not MD5s, and no body approaches the 5 GB single-PUT limit. Every body-store adapter keeps these semantics.

**Nothing is cut off.** The fetcher MUST spool each body to a temporary file, so any size up to the single-PUT limit is stored whole. An attempt is complete only as [[DATA-MODEL]] §5.2 defines it; an incomplete body is kept as evidence, never a real file, and its URL is retried.

**Crash between a body and its receipt.** The body is kept and the raw check finds it (§7.4), but its origin is not recorded unless a later fetch of the same URL gets the same content. This loss of attribution is accepted.

**Older bodies** keep their `.gz` form. Older gzip PDFs gain a one-time `.pdf` copy ([[DATA-MODEL]] §5.1), so a saved PDF is a plain link the browser's own viewer opens and PDFs up to 1.19 GB never pass through the page; other `.gz` bodies are small enough to unpack in the browser (§11.5). A 412 on a copy MUST be checked against the expected MD5 with one HEAD, since older capture code can write such copies without recording them.

### 7.2 Receipts

A run MUST write each receipt file create-only and after the bodies its lines reference, so every line points at a body that exists; receipts are the authoritative history of what was captured and when.

Files are numbered, `receipts/<family>/<write-date>/<run>-<seq>.jsonl.gz`, keyed by the UTC write date. New writers MUST use date-shaped prefixes only; older receipts also sit under `undated/` and `mixed-dates/` (49 files, 1,257,667 lines), which only the backfill reads. Each line records one fetch as [[DATA-MODEL]] §5.2 defines it, without links, which a page's reading holds (§8.3). Run IDs are never reused, so a 412 on a receipt or provenance write fails the run.

Receipts are public and permanent, so they carry no credentials, cookies or local paths ([[DATA-MODEL]] §5.2). An API key travels in a request header where the API allows it; where a host takes a key only in the query, the fetcher adds it from configuration at fetch time and records the URL without it. The one-time cleanup of older receipts ([[DATA-MODEL]] §5.2) is the only rewrite of raw history.

**Archives.** ZIP and `rtfd` bodies are expanded into member entries after a complete fetch, streamed from the spooled file within the archive-limit registry's limits. Office packages (Open XML, ODF), recognized by their content, stay whole; an archive inside an archive is not expanded; and a refused expansion is recorded on the container's entry.

**Recovery imports** write receipts too, with `mode: retained_import` and the original link the content recovers ([[DATA-MODEL]] §5.2).

### 7.3 Provenance

`provenance/<kind>/<ts>.jsonl` holds every decision a person or a reviewed process makes about sources, as append-only timestamped records, corrected only by superseding ones: accepted URL variants, recovery decisions, document reviews and verification results ([[DATA-MODEL]] §5.3).

### 7.4 Protection and Verification

**Lock.** An indefinite R2 bucket lock, set per prefix, covers `bodies/`, `receipts/` and `provenance/`. Creates stay allowed.

**Full re-hash** is an explicit job that downloads bodies and records each one's size, ETag and verified SHA-256 under `provenance/verification/`, skipping keys whose record has `sha256_verified` true. No older line records an MD5, and receipts record a stored size for 672,063 of the 1,036,256 older bodies; the other 364,193, nearly all Senate captions, have one only in the old capture index. So until the re-hash runs once, after the PDF copies, the first raw check records a listing baseline: each older body's size and ETag, the size checked against its recorded stored size, from the receipts else the old index. The baseline is then raw's own record of that size. Afterwards the re-hash runs only before a migration.

**Raw check.** Each week the maintenance job makes one LIST of `bodies/` and joins it to the recorded keys of `captures` and the verification records. It confirms that every recorded key exists and that every stored body has the size and ETag its creating line or verification record gives. A body with neither is re-hashed once, and 25 random bodies are downloaded and checked end to end; nothing else reads body bytes, and there is no per-body HEAD. The listing proves that each body is present and was not replaced; the sample is the only content check, and R2's durability is the accepted guard against decay.

**Durability.** Raw is kept in one R2 bucket with no second copy. R2's own durability guards against hardware loss. A provider-side loss is the accepted risk.

## 8. Lake

### 8.1 Common Rules

Every lake commit MUST assert the table UUID and the snapshot its work list was read at, so a concurrent commit makes it fail rather than be rebased onto the new head. All lake tables are Iceberg [[ICEBERG]] tables in the bucket's Basin Catalog, with the types, properties and writer settings of [[DATA-MODEL]] §4 and §6.

**Conflict retry.** A producer that loses a commit race MUST reload the table, recompute its work list against the new snapshot, and commit only the rows still missing, reusing the files already written when the work list is unchanged; Basin's own maintenance commits to the same tables, so races happen. It retries at most three times. It MUST NOT commit rows the new work list no longer needs, which would duplicate rows when two runs ingest the same receipts. Otherwise a losing attempt's files become orphans (§8.6).

**Work lists.** Every producer finds its work by an anti-join of its inputs against its rows, so an input that produced nothing still needs a row ([[DATA-MODEL]] §6). A daily run appends once; a backfill appends once per batch, so it always resumes.

**Sort order.** Nothing depends on a table's physical sort order, which compaction may not keep.

### 8.2 `captures`

One row per body a receipt line references, plus one per line that references none, so no fetch loses its status ([[DATA-MODEL]] §6.1).

**Ingest.** Rebuilding from all receipts MUST reproduce the same rows. For each receipt family, ingest lists only date-shaped prefixes from the newest date already ingested, anti-joins against ingested receipt keys, and appends the missing receipts in one commit, so listing cost grows with new receipts. The backfill reads the non-date segments once; the raw check lists everything and appends what a late receipt left behind.

### 8.3 `readings`

One row per `(body, parser, parser_version)`; each media family has its own parser and version, so a new HTML parser never re-reads a PDF ([[DATA-MODEL]] §6.2). Parsers record facts; the model classifies them.

- **Every body has a sniffed format**, and every PDF a record of whether it is intact. The fetcher records both for new bodies; a `sniff` parser covers the rest.
- **HTML, XML and JSON** are read in full once per version, with each body's links recorded as written. The model resolves the links against every address the page was fetched at, so link context covers all history while a page fetched many times stores its links once.
- **PDF, ZIP and captions** get no full reading. Full-text extraction of every PDF (about 403 GB) is deferred to `pdf_text`; ZIP members are captured as their own entries.
- **Text fingerprints come from the page readings** ([[DATA-MODEL]] §6.2), and a ZIP's from its member hashes in `captures`; no other format needs one today, so there is no fingerprint parser and no full-corpus text pass.
- **One bad input cannot stop publishing:** a parse that crashes or hangs is retried once, then recorded as an error ([[DATA-MODEL]] §6).

**Versions** are pinned, and a new one is backfilled in background batches before the profile moves to it ([[DATA-MODEL]] §7.1).

### 8.4 `filename_readings`

One row per `(filename, source_url, catalog_version)`: what the filename parser extracts, as typed facets and keys plus a fold ([[DATA-MODEL]] §6.3). These depend on the filename and URL, not the body, so they cannot live in `readings`, and their work list depends on raw and provenance only. A new catalog version is one background job.

### 8.5 Meeting, Witness and Reference Records

Every meeting record MUST come through the raw writer like any other fetch; older Congress.gov records sit inline in receipt lines and are read there. `meeting_records` and `appearance_records` ([[DATA-MODEL]] §6.5, §6.7) give pages a hearing's title, date, status, sittings and place, its committees and their roles, the bills, nominations and treaties it covers, its printed transcript (by GPO jacket number), its recording links, and its witnesses with what each submitted: from House witness lists, Congress.gov, Senate committee hearing pages (whose layout puts each witness's testimony in that witness's card) and the GovInfo MODS records already in raw. Every link is one a publisher states; witnesses are keyed per occasion and not yet matched across occasions.

Committees, members, terms, current rosters, bills, CBO estimates, floor votes and nominations are reference inputs from spicy-regs, which keeps their raw records ([[DATA-MODEL]] §6.4). They are not lake tables: publish pins each family's current immutable generation (§10.3.1) and the model reads it directly. The split runs both ways: the archive owns meetings, witnesses and saved copies, and spicy-regs reads its release files, pinned by release ID, instead of capturing meetings itself (spicy-stack ss-vhi2). Roster history and nominations before the 119th Congress wait on spicy-regs.

### 8.6 Maintenance

Basin Catalog's catalog-level maintenance, run under a bucket-wide service credential, compacts files not yet compacted (target 128 MB) and expires snapshots older than 30 days, keeping the last 5. Expiration deletes the data files only expired snapshots referenced.

**Orphans.** Basin does not remove files no snapshot ever referenced, such as a lost commit's data file. The raw check reports their bytes; cleanup waits until that number matters.

**Schema changes rebuild.** A new schema is a new table version ([[DATA-MODEL]] §6), built in background batches; the maintenance job drops the old one with purge once [[DATA-MODEL]] §6 allows.

## 9. Model

*This section is non-normative. It explains the model's intent; [[DATA-MODEL]] §7 defines every rule.*

### 9.1 One Job

The domain model is versioned SQL in the application repository. One engine job registers the lake tables, provenance records and registries at the versions the model profile pins, runs the model as named steps, and writes only the release files. A step that later steps read more than once, such as the components and the documents, is materialized once (§13), because DataFusion inlines common table expressions and would recompute them.

### 9.2 What Counts as a File

A file is a real document when its main content is the document itself (testimony, a report, a transcript, a bill, a hearing record), not a list of links, a landing, download or error page, or metadata about a document; the rule reads this from the sniffed format and the readings, by what a page says rather than by site templates or length. Every other body stays as evidence ([[DATA-MODEL]] §7.3): it never enters a document, but it still drives `url_state`; listing pages supply link context, and a wrapper's file is queued for capture.

### 9.3 Grouping

Source files connect when they share a real body, when one endpoint served re-packaged bytes with equal main text, when the publisher lists them together as formats of one document, and when a reviewer merges them. A new edition is a new document: an edition that ever shared an address with a different edition never joins a rendition group, so mirrors cannot merge editions transitively.

Files connect through one node per body, fingerprint or rendition group, so a group of n files costs n edges, not n² (§13).

### 9.4 Saved File, Dates and Records

A document's page links its preferred format, an exact copy before a provider's rendering; other formats are alternates, and a link to any rendition opens the same entry. The document date is never a guess among several dates, and the capture date is a real fetch's, never an import run's ([[DATA-MODEL]] §7.5; §11.6).

Meeting IDs from docs.house.gov, Congress.gov and the committee explorer share one space, so a page can list every document for a hearing. Official record keys (GovInfo package, bills, member Bioguide IDs) let a page link out, and committee codes map to Congress.gov system codes.

### 9.5 Recoveries and Reviews

A recovery is evidence for its original link. On its own it never makes a real file, a body key or a capture date, and it stays out of `url_state` and text comparison; a real fetch of the same bytes still counts as that fetch. It attaches to the one listed document that holds its original link, or else keeps a page of its own, labeled by kind with its evidence.

A review targets a link key, so it follows a file through merges and splits.

### 9.6 URL Normalization

Joins between links, recoveries and source files use `url_key`, which unwraps redirect and archive wrappers and drops differences that never select a different file. Identity keeps the exact URL.

## 10. Releases

### 10.1 Release Files

The model's job writes the release files as Parquet [[PARQUET]]; [[DATA-MODEL]] §8.1 lists each with its purpose and columns. They link by list row number and by the keys of hearings, bills, members, witnesses and committees.

- **Documents only.** There are no per-copy pages.
- **Links point at a file.** A document's ID changes whenever a version joins its group, but a file's digest never does, so a public link carries a link key, and `links` maps every real body of every listed document to its document's row. Old links keep resolving when a group or its saved file changes, and a recovery-only page keeps its link after the original finally downloads. A pasted publisher link finds its documents through `urls`, keyed by a fixed normalization of the address ([[DATA-MODEL]] §8.2).
- **No ID in `list`,** which would make it several times larger; the list row number links the files.
- **Growth.** The export shards `detail` and `sources` by row range when an offset index outgrows a quick first fetch, at roughly 10 times today's rows. At that size `list` reaches 40–50 MB; then it is sharded by facet, or search moves to DuckDB-WASM or a server.

### 10.2 Determinism

Identical inputs MUST produce byte-identical files, so reruns are idempotent and the "nothing changed" check is exact. The engine enforces it:

- every sort key MUST be unique, or the export refuses;
- partition order is fixed;
- the export re-batches its input to the pinned write batch and flushes row groups on fixed row counts, whatever the upstream batches or spills;
- writer properties and `created_by` are pinned;
- no timestamps or run-specific values enter content.

Determinism is not a dedupe mechanism: one new document shifts every later row number, so on any day with a change every file changes.

### 10.3 Publish

#### 10.3.1 Pinned Inputs and Input Identity

After the lake steps of §12, a publish run MUST pin, once, the current snapshots, the provenance set (every provenance key with its ETag) and the current spicy-regs generation of each reference family ([[DATA-MODEL]] §6.4), apply the completeness gate at them ([[DATA-MODEL]] §7.1), compute the input identity from them ([[DATA-MODEL]] §8.3), and run the model against exactly those inputs.

#### 10.3.2 Early Skip

If the input identity equals that of any input record of the live release, publish stops before the model runs. A review, registry or SQL change therefore publishes without waiting for a capture.

#### 10.3.3 Release ID

The release ID ([[DATA-MODEL]] §8.3) is computed after export and before upload. If it equals the live release's, publish records the new input identity and stops. An empty `list` MUST NOT be published.

#### 10.3.4 Upload

Files are uploaded to `viewer-publications/releases/<release_id>/` with a create-only PUT and `Content-MD5`. A 412 on a rerun is success, as for a body (§7.1): the release ID hashes every file's digest (§10.3.3). The release's `manifest.json` holds only content, so a release that re-emerges writes identical bytes; `inputs/<input_digest>.json` records each input identity that produced it, and `inputs/receipts/<sha256>.json.gz` its receipt keys ([[DATA-MODEL]] §8.1). Before the canary, publish adds the candidate's spicy-regs generations to `viewer-publications/pins/spicy-generations.json`, the list spicy-regs' retention reads beside DocSpec's so it keeps them.

#### 10.3.5 Canary

Before the flip, the site's own reader module runs in Node against the uploaded candidate over HTTPS, so Range reads and caching headers are real. It decodes `list` within a heap budget for a mid-range phone, runs a search and a facet count, reads the first, last and a random detail, resolves a link, reads a source range and a recovery range, opens one saved copy, and checks that `url_state` decodes. It takes under a minute and needs no headless browser.

#### 10.3.6 Flip

The flip writes the candidate as the pointer's `release_id` and the outgoing live release as its `previous_release_id`, with `If-Match` on the pointer's current ETag, or `If-None-Match: *` for the first release. A failed canary or a lost race leaves the previous release live. Release files and manifests are cached as immutable; the pointer is `no-store`.

#### 10.3.7 Concurrency and Retention

Publish, backfills and the maintenance job run in one CI concurrency group, so they never overlap, and publish MUST NOT delete anything. Without the group, a publish that re-creates an older release reuses that release's prefix, and retention could delete the prefix between the canary and the flip.

From the second flip on, at least the live and last-good releases exist. The maintenance job re-reads the pointer just before it deletes, takes both release IDs from it, and removes release prefixes that are neither live nor last good nor pinned by spicy-regs' published pin list, and are more than a day old, failed candidates included. Up to a week of daily releases (about 0.7 GB) can wait in between. Releases share no files, so nothing needs reference counting. It then rewrites the pin list to the generations the kept releases' input records name. With those generations, its recorded receipt keys and the table versions its profile names, which the lake keeps ([[DATA-MODEL]] §6), a kept release can always be rebuilt; spicy-regs otherwise keeps only each family's last three generations.

## 11. Site

### 11.1 Reads

The site reads pointer → release manifest → `list`, then the other release files as needed. Search and facet filtering run in a Web Worker over `list`, decoded column by column into arrays and dictionary codes, because objects would cost hundreds of MB of heap on a phone. Details and ranges are HTTP Range reads of single pages through the Parquet offset index. A row group's offset indexes and the dictionary pages of its dictionary-encoded columns are fetched once per session and kept in the reader's byte cache, so after that a detail view is one round trip of concurrent page reads; link lookups also use the column index.

### 11.2 Devices and Speed

The site targets desktop and mid-range phones. Speed targets (startup, search and detail times, and the heap budget) are measured on real phones and desktops, then fixed as targets the canary and contract test check. There is no per-view byte budget.

### 11.3 Stale Tabs

On a 404 for a release file, the reader MUST re-read the pointer once and reload; if the pointer still names the same release, the file is reported as not found. Only the live and last-good releases are sure to exist, so a tab left open across two publishes can lose its files.

### 11.4 One Reader and Its Contract

The reader MUST accept the current and the previous `schema_version` of the release manifest, so format changes ship reader-first, then publisher. It is a plain module with no DOM dependency, so the canary runs the code the site ships.

### 11.5 Saved Copies

A saved file opens at its physical key: `saved_body` plus `saved_suffix`.

- Bodies written to §7.1 open directly; older gzip PDFs open their `.pdf` copy once it is recorded, and until then unpack like other `.gz` bodies.
- Other `.gz` bodies are fetched and unpacked with the browser's `DecompressionStream`, then opened with the media type from `detail`; those whose original size in `detail` exceeds 100 MB (313, up to 1.19 GB) are offered as a labeled compressed download.
- A recovery is labeled by kind and links the recovered file.
- A link key that no longer resolves opens a not-found notice; a pasted address is looked up in `urls`, and several matches are shown as versions.

### 11.6 Dates and Hearings

The reader shows dates and hearings as follows:

- **Capture date:** the reader MUST label it by `date_kind` ([[DATA-MODEL]] §8.1): `captured` as "Captured <date>", `import_day` as "In our archive since <date> (original capture date not recorded)", `unknown` as "Capture date not recorded".
- **Document date:** the reader MUST show it with its source and, for a document a committee removed from its hearing page, "Removed from the hearing page by the committee on <date>".
- **Hearings, bills, members, witnesses and versions.** The hearing, committee, chamber, bill, member and witness filters MUST match a document when the key is any element of its `meeting_keys`, `committee_keys`, `chambers`, `measure_keys`, `bioguide_ids` or `witness_keys`, with committee names taken from `committees.parquet`; documents sharing a `version_keys` entry are shown as each other's versions, by capture date. Hearing, member, committee, bill and transcript pages join their files by the keys of [[DATA-MODEL]] §9, and a vote, member or bill links out to spicy-regs for member positions, money and lobbying. A hearing with no meeting record is shown by its key; the reader loads `meetings.parquet` at most once per session.

### 11.7 Origin

`congressional-data.spicygov.ai` serves the bucket directly with a read-only, any-origin CORS policy (GET/HEAD, Range), immutable cache headers on release files, a content security policy and the `?filename=` download rule. There is no path allowlist: `r2.dev` serves every key anyway.

## 12. Orchestration

Four jobs run on the schedules below; all but capture share one concurrency group (§10.3.7).

```
capture:     live url_state → fetchers → bodies → receipts             (daily; network-bound)
publish:     captures → readings (sniff → html, xml, json),
             filename_readings, meeting_records, appearance_records
             → pin inputs → completeness gate → input identity → early skip
             → model + export → canary → flip → status                  (after capture, or on demand)
maintenance: raw check and sample → release retention → table drops → orphan report   (weekly)
backfill:    one producer's work list for a new version or table, in batches   (on demand)
```

- **Order.** The lake steps run first, each on its own work list: `sniff` before the format parsers, which need formats. The concurrency group (§10.3.7) keeps anything from landing between the lake steps and the pin.
- **Budgets.** Each daily lake step has a work-list budget, set per runner class with its resources. A step whose work list exceeds it, such as a registry change that adds thousands of fingerprint candidates, is left to a backfill: publish refuses at once, rather than after the model runs, and starts that step's backfill, which runs next in the concurrency group.
- **Idempotent steps.** Each step is keyed by its input, is a no-op when that has not changed, and commits durably, so a failed run resumes by running again, with no journal.
- **Capture reads the public release.** It builds its queue from the live release's `url_state` and applies its `capture_scope.json`, so it needs no lake or release credentials, and it follows what its fetchers discover in the same run, such as the documents an API response lists. After a failed canary, capture works from a slightly older schedule, which is safe because body writes are create-only.
- **Status.** Every publish run writes `viewer-publications/status.json`: input identity, rows per output, durations, bytes and the live release.
- **Local runs.** The same commands run locally or in CI, and correctness MUST NOT depend on a CI feature, with one exception: whoever runs publish, a backfill or maintenance outside CI MUST NOT run it while another of them runs (§10.3.7).

## 13. Engine Capabilities

The engine (docspec-rs) MUST provide these capabilities; what its paths may not contain follows the list:

1. **Multi-input SQL jobs** in one DataFusion context, over Iceberg tables in Basin Catalog, Parquet files, and the gzip-compressed JSON lines of receipts.
   - Receipts are read with an explicit schema, every field nullable, that nulls a conflicting value and keeps the raw line, so no line fails the read and none is lost silently.
   - Partition and column filters reach Iceberg scan planning.
   - A named step can be materialized once, its batches reserved in the memory pool or written to scratch Parquet when the pool refuses.
2. **Table operations** through the REST catalog: append, each commit asserting its table UUID and base snapshot, with the conflict retry of §8.1; create; and drop with purge.
3. **Deterministic multi-file export** to §10.2, with the per-file writer settings of [[DATA-MODEL]] §8.1, SHA-256 and MD5 computed while writing, and row-range shards once §10.1's growth rule calls for them; the bytes depend on no runner limit (spicy-stack ss-iwqu).
4. **Connected components** over a relation of the same job, returning a deterministic component label and no ID, in memory over interned dense integer IDs, refusing above a configured node count and reserving its true heap (spicy-stack ss-6jg6; today's string-keyed tables need *est.* 1.65 GiB at 1.7M rows).
5. **Streaming I/O:** no re-read of a just-written object and no HEAD of an immutable file, except as §7.1 allows. File and row-group sizes come from writer settings ([[DATA-MODEL]] §6, §8.1).
6. **Bounded resources** set by configuration per runner class: compute threads, a memory pool no larger than the machine, and scratch space. Sorts and aggregates spill or fail clearly within the pool. Hash-join builds do not spill, and join selection builds the smaller input by the row counts scans report, so plans keep wide columns off both join inputs: join on keys first, reduce, then attach the wide column.
7. **A thin interface:** a library plus a CLI that runs a declarative job spec (inputs, SQL steps, outputs, export settings) and returns a machine-readable result.
8. **Generic URL and JSON functions** DataFusion lacks, as SQL functions: reference resolution by the WHATWG URL parser [[URL]] and percent-encoding normalization [[RFC3986]] §6.2.2 (spicy-stack ss-7qz3), and `json_array`, the compact JSON of [[DATA-MODEL]] §3 that every ID formula hashes (ss-e53d).

The engine paths this system uses MUST NOT contain application policy (ID formulas, field names, grouping rules, registry values), body or filename parsers, table maintenance (Basin Catalog does it), bookkeeping that duplicates Iceberg, or resume machinery beyond per-step commits; §15's ratchets apply to them too. Engine code that serves other consumers is outside this specification.

Iceberg is used only to read, append, create and drop. If replace or branching is ever needed, it is added upstream to iceberg-rust rather than worked around.

## 14. Security

Raw isolation in one bucket rests on create-only writers plus the bucket lock (§7.4).

- **Credentials.** R2 tokens scope object permissions to buckets, never to prefixes, so any writing token can delete unlocked keys. Capture, publish and maintenance use separate tokens, each revocable on its own; only maintenance deletes release prefixes and drops lake tables.
- **Pinned engine.** The engine binary is pinned by revision and by a digest per runner OS recorded in the application repository, and MUST be checked against that digest before any storage access.
- **Public data.** Everything stored is public records, readable publicly; receipts carry allowlisted headers only (§7.2).

## 15. Verification

1. **Data-model invariants:** the invariants of [[DATA-MODEL]] §10, as tests over the raw log, the lake, the model's relations and each release.
2. **Rule accuracy:** a hand-labeled sample of a few hundred files measures how often the file-shape, record-role, placeholder and rendition rules wrongly include, exclude or join a file.
3. **Registry samples:** every registry entry's sample passes its test.
4. **Determinism:** byte-identical exports across thread counts, input orders, batch sizes and a forced spill (§10.2).
5. **Contract:** CI builds a release from a fixed sample of real receipts and loads it through the real site in a headless browser, within the heap budget.
6. **Canary** (§10.3.5) on every candidate; it and the contract test both check the 404 reload of §11.3.
7. **Ratchets:** no test-only branches or input substitutions in production code, application or engine; no engine fast paths keyed on dataset names; no application identifiers (committee codes, family names, registry values) in the engine crate.

## 16. Performance

*This section is non-normative.*

| Step | Cost | Expected |
|---|---|---|
| Capture | O(new attempts), network | Bounded by politeness to sources |
| Captures ingest | O(new receipts) to read; the work list scans the keys already ingested | Seconds |
| Readings | O(new bodies in scope × parse cost) | Minutes daily; backfills in background |
| Filename readings | O(new pairs) | Under a second daily; 7–18 minutes per catalog version |
| Model + export | O(N log N) sorting plus scans and joins over every row; linear grouping | Seconds for the narrow plan |
| Publish | O(release size) | About 95 MB of uploads on a day with changes |
| Detail view | One page per leaf | One round trip after the once-per-session fetch of §11.1 |
| Raw check | O(history) object metadata | About 1,300 list requests, no body bytes |

A normal day moves about 4,000–8,000 object operations and 2 GB, inside R2's free tier at today's scale.

The repeated work principle 4 accepts: capture re-fetches and re-hashes URLs on their recheck schedule; work-list anti-joins scan the keys already processed; the model recomputes every relation each run, link resolution, `url_key` and meeting references included; a release upload is the whole release on any day with a change; and the raw check lists every body's metadata.

Link matching grows with links times the source files at each matched address: about 696k pairs today, the most real files at one address being 47, the members of one GovInfo ZIP (a top-level URL holds at most 3). The model reports the largest.

## 17. References

### 17.1 Normative References

**[RFC2119]**
: S. Bradner. *Key words for use in RFCs to Indicate Requirement Levels.* BCP 14, RFC 2119, March 1997. https://www.rfc-editor.org/rfc/rfc2119

**[RFC8174]**
: B. Leiba. *Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words.* BCP 14, RFC 8174, May 2017. https://www.rfc-editor.org/rfc/rfc8174

**[URL]**
: WHATWG. *URL Living Standard.* https://url.spec.whatwg.org/

**[RFC3986]**
: T. Berners-Lee, R. Fielding, L. Masinter. *Uniform Resource Identifier (URI): Generic Syntax.* STD 66, RFC 3986, January 2005. https://www.rfc-editor.org/rfc/rfc3986

**[PARQUET]**
: *Apache Parquet Format.* https://parquet.apache.org/docs/file-format/

**[ICEBERG]**
: *Apache Iceberg Table Spec.* https://iceberg.apache.org/spec/

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.

### 17.2 Informative References

**[IMPLEMENTATION-PLAN]**
: *Congressional Document Archive: Implementation Plan.* Note, 2026-10-24. `docs/plans/simplification-plan-20261024.md`.
