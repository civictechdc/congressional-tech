# Package inventory: today's code against the engine-first target

**Date:** 2026-10-25. **Read-only.** congressional-tech worktree `/Users/mikewolfd/Work/wt/ct-ticket-audit` at `d9730967`; docspec-rs `/Users/mikewolfd/Work/spicy-stack/docspec-rs` at `d9c6719`. Nothing was edited, committed, built, tested or fetched.

**Target.** A = `docs/engine-first-architecture.md`, D = `docs/engine-first-data-model.md`, P = `docs/plans/simplification-plan-20261024.md`, all at `d9730967`.

**Method.** Static reading, `grep`, `wc -l`, `git log`, and AST import graphs built with the project venv (`/Users/mikewolfd/Work/wt/ct-viewer-publish/.venv/bin/python -I`). Every count is measured `wc -l` unless marked *est.* Test lines are attributed by what each test file imports, so a test that touches several groups is counted once, under "shared" or "mixed".

**Classes.** **Keep**: survives largely as is. **Repurpose**: lift it to build a target component, with named changes. **Replace**: deleted at the switch (or earlier, where the plan says "now"). **Dormant**: no live caller today; its purpose and a proposed use are given. **Unclear**: what would settle it is named.

**Where the detail lives.** Section 4 holds one section per package. Sections 4.2 to 4.5 were written by four parallel read-only passes under the same rules. The parent re-read the high-impact claims that the summary, top-ten and delete-table sections relay (for example `cli/raw_sync.py:469`, `corpus_recovery/transfer.py:26-46`, `matching/house.py:33-34`, `transport/http.py:92-122`, docspec-rs `storage.rs:132-140`); the rest is theirs. Their scripts and raw outputs sit beside this file:

| Folder | Contents |
|---|---|
| `parent/` | `section-retention.md` (4.1), `inv_ret_imports.py`, `inv_ret_groups.py`, `ret_import_graph.json`, `ret_groups.json` |
| `fork-acq/` | congress_api acquisition, parsers, transport, models, matching, cli, replay, transcripts, adapters; satellite packages (4.2); `inv_acq_imports.py`, `import_graph.json` |
| `fork-site/` | site, viewer_publication, publication and measurement scripts, workflows (4.3); `inv_site_counts.sh` |
| `fork-other/` | house-naming, docspec_client, corpus_recovery, news_lake, source-fetch, scripts, root tests (4.4) |
| `fork-docspec/` | docspec-rs (4.5); `inv_ds_count.py`, `inv_ds_group_counts.md` |
| `fork-lessons-mistakes/`, `fork-lessons-knowledge/` | the detail behind section 6 |

## Contents

1. Summary table
2. Top repurpose opportunities
3. The plan's delete table and keep list, checked
4. Packages: 4.1 congress_api/retention · 4.2 congress_api acquisition and parsers, and the satellite packages · 4.3 site, viewer publication, scripts and workflows · 4.4 house-naming, docspec_client, corpus_recovery, news_lake, source-fetch, scripts, tests · 4.5 docspec-rs
5. Cross-cutting: rule conflicts · capabilities that exist nowhere · engine-first duplicates · dormant code · unclear
6. Lessons: mistakes not to repeat · hard-won knowledge · over-engineering not to port

## 1. Summary table

Source and test lines per group. "Shared" test lines are also imported by other groups.

### 1.1 congressional-tech: congress_api/retention (detail 4.1)

| Group | Class | Target component (spec §) | src | tests |
|---|---|---|---:|---:|
| Raw writer and capture checks (`r2`, `body_files`, `body_keys`, `archive_members`, `bundles`, `capture_inspection`, `capture_url_admission`, `image_tools`, `pdf_tools`, `write_recovery`, `raw_progress`) + `LocalStore` | **Keep / Repurpose** | raw writer (A §7.1–7.2, D §5.1–5.2); `sniff` reading (D §6.2) | 1,698 + 114 | 5,817 |
| Receipt and body builder (`raw_archive.py:94-237`, `raw_storage.py:237-278`) | **Repurpose** | receipt lines, `captures[]` (A §7.2, D §5.2) | ≈ 186 | in RX tests |
| PDF copy job (`pdf_backfill.py`, `raw_storage.py:280-362`) | **Repurpose**, then delete after B13 | `.pdf` copies + verification records (P B13, D §5.3) | 326 | 210 (mixed) |
| Exclusion gate (`raw_storage.py:75-236` + hooks) | **Replace now** (P B4) | none | 162 + ≈ 30 | — |
| Raw index and native raw selection (16 modules) | **Replace** | `captures` (D §6.1), `url_state` (D §7.7) | ≈ 4,670 | 2,663 |
| Incremental catalog (16 `catalog_*`, 5 `source_*`, `raw_catalog`, `native_features`) | **Replace** | model SQL (A §9, D §7) | 10,336 | 9,018 shared |
| Rebuild catalog and `index/*` (less `LocalStore`) | **Replace**, rules lifted | model SQL (D §7.3–7.10); `filename_readings` producer (D §6.3) | 6,726 | 11,006 shared (with shims) |
| Review tools (`document_review_*`, `document_reviews`) | **Replace** binding, **Repurpose** form list | provenance `reviews` (D §5.3, §7.9) | 916 | 644 |
| Weekly and committee-explorer retention | **Keep** (parked, P §7) | none | 2,154 | 5,436 |
| Shims and facades (`catalog/`, `raw/`, `review/` facades are **Dormant**) | **Replace** | none | 225 | in RB |
| Viewer custody helpers | **Replace** | release manifest digests (D §8.1) | 126 | 662 |

### 1.2 congressional-tech: congress_api outside retention, and satellites (detail 4.2)

| Group | Class | Target component (spec §) | src | tests |
|---|---|---|---:|---:|
| Capture core (`acquisition/raw_sync`, `streamed_recovery`, `retained_import`, `recovery_queue`) | **Repurpose** loop, budgets, range download; **Replace** replay, raw-index queue, capture-time readings, `recovery_queue`, `retained_import` | fetcher (A §7.1–7.2, §12); P B14 | 1,262 | 956 excl. (3,927 shared) |
| Congress.gov fetchers (`acquisition/committees`, `meetings`) | **Repurpose** | B16 fetchers (A §8.5–8.6) | 265 | 830 shared |
| Inventory fetchers (`house`, `house_fallback`, `house_sites`, `senate`, `gpo`, `gaps`, `refresh`) | **Keep** (explorer), but must fetch through the raw writer | `meeting_records` inventories (A §8.6) | 1,805 | ≈ 7,693 shared |
| `acquisition/documents.py` + `transport/document_probe.py` | **Dormant** | labeling aid for S (P §5.3); B14 pre-check | 112 | 147 |
| Parsers: link and sniff core (`document_links`, `archive_links`, `page_content`, `file_wrapper`) | **Repurpose** | `html`/`xml`/`sniff` readings (D §6.2); registry seeds (D §7.1) | 607 | 781+ |
| Parsers: meeting (`house_documents`, `house_evidence`, `house_xml`, `house`, `xml`, `congress`) | **Repurpose** | XML links with `group_path`; `meeting_records`; `meeting_ref` (D §6.2, §6.5, §7.5) | 464 | shared |
| Parsers: Senate | **Keep** (explorer); **Replace** archive use | generic HTML reading (D §6.2) | 1,411 | shared |
| Parsers: committee sites, GPO, explorer helpers | **Keep** (out of scope); seeds for capture scope | — | 2,028 | shared |
| `parsers/source_family.py` | **Repurpose** | receipt `family` (D §5.2); recheck key (D §7.1) | 179 | shared |
| Transport fetch (`rust_fetch`, `source_capture`, `zyte`, `http`, `congress`, `senate`) | **Repurpose** | fetcher (A §7.1) | 798 | shared |
| Models core (`congress.py`, `DocumentLink` repurposed) | **Keep / Repurpose** | JSON producers (D §6.4–6.5); link struct (D §6.2) | 994 | 410 excl. |
| Matching: `committees`, `house`, `meetings` | **Repurpose** | `meeting_ref`, `committee_key` (D §7.5) | 232 | shared |
| cli capture (`raw_sync`, `raw_progress`, `common`) | **Repurpose**; catalog modes **Replace** (≈ 155) | capture job (A §12) | 675 | shared |
| `cli/document_index.py`; `replay/*` | **Replace** (neither is in P's table) | model SQL; readings backfills (A §8.3) | 71; 346 | 2 files; 980 shared |
| Explorer code: adapters, matching (rest), transcripts, transport media, models (other), cli explorer, inventory and weekly entries | **Keep** (out of scope) | — | 7,569 | shared |
| `packages/committee_meeting`, `youtube_api`; `apps/committee_youtube` | **Keep** (out of scope; explorer is a docspec-rs consumer) | — | 1,441; 1,498; 5,878 | 329; 280; 1,165 |
| `packages/congress_shared` | **Keep** | R2 client, custody helpers | 919 | 199 |
| `apps/inflation_gsheets` | **Keep** (unrelated product) | — | 663 | 0 |

### 1.3 congressional-tech: site, viewer publication, scripts, workflows (detail 4.3)

| Group | Class | Target component (spec §) | src | tests |
|---|---|---|---:|---:|
| Site reader core (`cache.ts`, `startup.ts`, `cooperative.ts`, `client.ts`, `session.ts`, `bootstrap.ts`, `worker.ts`, `publication.ts`) | **Repurpose** | reader shell (A §11.1, §11.3–11.4) | 581 | 405 |
| Site v6 + ExportPin reader branch | **Replace** | new release reader (A §11.1, D §8.1) | 1,293 | 940 |
| Site filename views and labels | **Repurpose** (about half) | document page (A §11.5–11.6) | 1,782 | 346 |
| Site committee explorer | **Keep** (parked) | — | 7,970 | 1,373 |
| `verify-live-publication.mjs` | **Repurpose** (P says Replace) | canary HTTP layer; contract-test harness (A §10.3.5, §15.5) | 400 | 143 |
| Site static pages | **Keep** | static site | ≈ 960 | 82 |
| viewer_publication journal, resume and attempt route | **Replace** | publish job (A §10.3) | 2,682 | 2,180 |
| Preflight and release identity | **Replace** (small lifts) | input identity, code identity (D §8.3, P B7) | 609 | 657 |
| `client.py:264-391` (create-only upload, If-Match flip) | **Repurpose** | A §10.3.4, §10.3.6 | 128 | shared |
| v6 preparer (17 modules) + `filename_viewer.py` | **Replace** | model SQL + engine export | 3,294 + 871 | 2,682 |
| `filename_exports.py` (ExportPin) | **Repurpose for F0**, then delete | F0 converter (P §5.4) | 1,254 | 383 |
| Edge tooling | **Repurpose** minus the WAF | origin rules (A §11.7) | 722 | 211 |
| `compact_readings.py`, `compact_reviews.py` | **Dormant** | fixture helper for PK tests | 366 | 332 |
| Review publication (`filename_reviews.py`, staging script, JSON) | **Replace**; data needs a decision | provenance `reviews` | 188 (+907 JSON) | 183 |
| Engine runtime pinning (`publish_docspec_runtime.py`, setup/check scripts) | **Keep** | pinned engine (A §12) | 474 | 391 |
| `backfill_uncompressed_pdfs.py` | **Repurpose** (B13 CLI), then delete | P B13 | 96 | in `test_pdf_backfill.py` |
| `pipeline_status.py` | **Replace** | `status.json` (A §12) | 352 | 298 |
| Measurement scripts: deleted subjects / still useful | **Replace** / **Repurpose** | speed targets (A §11.2, P A11) | 2,725 / 427 | 531 / 192 |
| `.github/scripts/verify-capture-run.py` | **Replace** (checks reusable) | R-check, weekly check (A §7.4) | 323 | 497 |
| Workflows | capture / publish / keep / delete (4.3 §7) | A §12 | 1,383 yml | 2,505 |

### 1.4 congressional-tech: other packages, scripts and root tests (detail 4.4)

| Group | Class | Target component (spec §) | src | tests |
|---|---|---|---:|---:|
| house-naming runtime | **Keep** (core of the producer) | `filename_readings` (D §6.3) | 3,993 py + 34,977 JSON | 13,325 |
| house-naming `archive/tools`, `bill_codes.py` | **Dormant** | catalog-version review; `measure_keys` vocabulary | 1,502; 49 | 0 |
| docspec_client custody path | **Keep** (news_lake and the explorer still use it) | none in the archive | 2,267 | 187 |
| docspec_client `verify_runtime`, `resolve_docspec_binary`, qualified-runtime pin | **Repurpose** | pinned engine (A §12) | (in custody path) | — |
| docspec_client archive-only builders; pure-Python BLAKE3; shims | **Replace** (shims only after news_lake moves) | — | ≈ 530; 107; 124 | 321 |
| corpus_recovery keep set (`guards`, `acknowledge`, `html`, `govinfo`, `admission`*, `inventory`*) | **Keep** with changes | recovery imports (A §7.2) | 875 | 235 |
| corpus_recovery `assemble`, `transfer` | **Repurpose** | recovery receipt writer (D §5.2) | 272 | 421 |
| corpus_recovery `mappings`, `publication`, `preservation`, `diagnostics` | **Replace** | provenance `recoveries` (D §5.3) | 547 | 971 |
| scripts/corpus_recovery: keep / repurpose / publication dispatch | **Keep / Repurpose / Replace** | recovery imports; P B7 | 311 / 549 / 483 | 373 / 485 / 615 |
| scripts/webharvest | **Keep** (+ registry samples) | recovery acquisition; `url_key` samples (D §7.2) | 1,616 | 757 |
| news_lake | **Keep** (parked, P §7) | not in the archive | 9,394 | 7,799 |
| source-fetch (Rust) | **Keep** with changes | fetcher transport (A §7.1) | 357 | 42 |
| `scripts/dev.py` + `test-suites.toml` | **Keep** | project runner (P §3) | 258 | — |
| `scripts/incremental_boundary_proof.py` | **Dormant → Replace** | — | 261 | 55 |
| `tests/e2e` | **Replace** | — (A §15 needs new tests) | — | 8,403 |

\* survive only after their raw-index branches are cut.

### 1.5 docspec-rs (detail 4.5)

| Group | Class | Target component (spec §) | src | tests |
|---|---|---|---:|---:|
| Export writer core (`export/pipeline.rs`, `child.rs`, `parent.rs`, `facets.rs`, `HashingFile`) | **Repurpose** | C3 deterministic export (A §10.1–10.2, §13.3) | 1,942 | shared 3,142 |
| Storage write path (`storage.rs:359-659`, `append`, `batch.rs`) | **Repurpose** | C2 appends (A §8.1) | 1,749 | 1,150 shared |
| Reads: `query.rs` provider, `pinned.rs`; `RemoteCatalog`; `budget.rs` | **Repurpose**; **Keep** | C1, C6 (A §13.1, §13.6) | 1,310; 368; 231 | 1,331; 40; 210 |
| ConnectedComponents kernel | **Repurpose** | C4 (A §13.4) | *est.* 414 | shared |
| CC lifecycle wrapper and `document_id` in the engine; `sha256.rs` | **Replace** | model SQL (D §7.5) | *est.* 1,565; 85 | shared; 29 |
| Remote objects: scope boundary, create-only writes, delete actor | **Keep** (P §8); upload path **Repurpose** | A §14; release upload (A §10.3.4) | 1,019 | 2,809 |
| CLI chassis (`main.rs`, `error.rs`, `progress.rs`) | **Repurpose** | C7 job-spec CLI (A §13.7) | 1,834 | 425 |
| Determinism guard (`sql_validation.rs:169-220`); output checks (`export/validation.rs`) | **Repurpose** | A §10.2; C3 checks | *est.* 52; in shell | — |
| Export child-slice reader; `examples/` R2 probes | **Dormant** | C3 page-read oracle; M1 harness seed | 474; 1,594 | — |
| Table properties, remote write caps, deferred commits, dataset-name predicates | **Replace** (C0) | D §6 properties; A §13, §15.7 | *est.* 160 | — |
| Engine core and lifecycle store, aggregation UDAFs | **Keep** (for parked news_lake and the explorer only) | none in target | ≈ 24,000 + 1,556 | ≈ 30,000 + 556 |
| Backfill, schema evolution, corrections, evidence updates, retirement, restore, succession, provider suites, `test_hooks`, `cli_args.rs`, Dagster adapter | **Replace** | none | ≈ 16,700 | ≈ 23,600 |
| Retention inventory, owners, removal | **Unclear** (news_lake's lifecycle compaction uses part) | — | 7,080 | 7,342 |

**Size of the switch (est., source only, no tests):** congressional-tech loses about 40,000 lines of Python and TypeScript across the Replace rows above (retention ≈ 23,000; site and viewer publication ≈ 14,100; corpus_recovery coupling ≈ 1,280; docspec_client ≈ 640; congress_api CLI, replay and queue ≈ 760; the proof script 261). docspec-rs can lose about 40,000 Rust lines including tests (P's items corrected to ≈ 19,727 plus ≈ 20,855 in families P does not list), but only about half of that while news_lake stays on the lifecycle store. Test lines are larger still; they overlap across rows, so they are not summed.


## 2. Top repurpose opportunities

Ranked by target work saved. Savings are *est.* lines of new code avoided, plus the real-data cases the existing code already handles. Detail and file:line for each is in the package section named.

| # | Existing code | Target component | What it already does | What must change | Saves (*est.*) |
|---|---|---|---|---|---|
| 1 | **house-naming** runtime (`Engine.extract`, `values.py:18-165`); version digest `retention/index/metadata.py:488-497` | `filename_readings` producer (D §6.3) | Returns every facet and key D §6.3 needs: kinds, families, committee codes, congress, date tokens, meeting date, measure type/number/references, bioguide tokens, GPO collection | Collapse scalars to one value; compose `filename_date`, `measure_keys`, `bioguide_ids`, `gpo_package_id`; write `status`/`error_type` from `NamingError.code` instead of swallowing it (`index/schemas.py:491-492`); keep the `invalid-source-url` retry (`:485-490`); `catalog_version` from the folder digest | The whole parser: 3,993 lines + 34,977 lines of vocabulary + 13,325 test lines; new code 150–250 (4.4) |
| 2 | docspec-rs **export writer core** (`export/pipeline.rs:445-702`, `child.rs`, `facets.rs`, `parent.rs`, `HashingFile` `export.rs:658-697`) | C3 deterministic multi-file export (A §10.1–10.2, D §8.1) | Streaming Parquet writer, footer bound, child tables, facets, fold, one settings builder, hashing while writing | Flush on row count only; re-batch to a pinned batch; per-column encodings and page limits; offset index on every leaf; unique sort-key refusal; several outputs per plan; SHA-256 + MD5; pinned `created_by`; shards; D §4 fold shape | 1,500–2,000 Rust (4.5) |
| 3 | **Fetcher and spooling chain**: `acquisition/raw_sync.py:45-107,517-570`, `transport/rust_fetch.py:68-257`, `transport/source_capture.py:42-180`, `packages/source-fetch`, `acquisition/streamed_recovery.py:31-118` | raw writer's fetcher (A §7.1–7.2); cut-off re-fetch (P B14) | Spools to disk, memory and spool budgets, per-hop scope check on redirects, Zyte fallback with `prior_attempts`, `Retry-After`, resumable hash-checked Range download | Lift the 64 MiB cap and rework the 3× reservation; drop replay, capture-time parsing and the raw-index queue; 412 = `unchanged` with no re-read; header allowlist; credential stripping; new receipt fields; fix the broken `streamed-recovery` CLI call (`cli/raw_sync.py:469`) | 1,100–1,650 (4.2, 4.4) |
| 4 | docspec-rs **reads**: `query.rs` provider, `storage/pinned.rs`, `RemoteCatalog`, `budget.rs` | C1 multi-input SQL, C6 resources (A §13.1, §13.6) | DataFusion provider over Iceberg with pruning; exact pins; REST catalog with retries; one `SessionContext` with a spill pool, scratch and thread limits | Scan at a pinned snapshot ID after Basin moves the head; multi-partition scans or a maintained provider (decide in M2) | 800–1,000 Rust (4.5) |
| 5 | **Site reader and verification harness**: `cache.ts`, `startup.ts` `withVerifiedJson`, `client.ts`, `worker.ts`, `session.ts`, `cooperative.ts`; `viewer_benchmark_server.py`, `benchmark_viewer_browser.mjs`; `verify-live-publication.mjs` `bounded()` and `browserRuntimeProbe`; `publish_viewer_r2.public_probe` | reader shell (A §11), canary (A §10.3.5), contract test (A §15.5), speed targets (P A11) | Worker routing, cancellation, worker rebuild, byte-bounded caches, shared in-flight loads, cooperative yields, verified whole-file reads, a local Range/CORS server, Chromium timing, CORS/206/`PAR1` probes | New routes; release-ID identity; 404 → re-read pointer; a bytes variant of `withVerifiedJson`; a heap metric; drop v6 checks | ≈ 800 (4.3) |
| 6 | **Raw body and receipt writer core**: `r2.R2Store.put_file` (`:407-444`), `AsyncBodies.put` (`:151-165`), `body_files.retain_body_file` (`:105-159`), `bundles.separate` (`:28-117`), `raw_archive.prepare_capture` (`:103-204`), `archive_members.py` | raw writer (A §7.1–7.2, D §5.2) | Create-only single PUT with Content-MD5 and ETag check, streamed from disk; one-pass hash; `captures[]` with `pointer`; ZIP and `rtfd` member expansion with Office kept whole, duplicate names apart, unsafe names flagged | Bare `<sha>` key with `Content-Encoding` for compressible types; older-copy HEAD; 412 = `unchanged` (no download); `member_path`, `sniffed_format`, `stored_suffix`, `stored_md5`; no `links` in lines; decide expansion limits | 600–900 (4.1) |
| 7 | docspec-rs **storage write path** (`storage.rs:359-659`, `append` `:858-929`, `batch.rs`) | C2 lake appends (A §8.1) | Rolling bounded writer, partition fan-out, commit requirements via iceberg-rust, unknown-commit reconciliation | Remove the remote caps; D §6 sizes; the work-list conflict loop in the job runner | 600–800 Rust (4.5) |
| 8 | **Congress.gov and House meeting XML**: `acquisition/meetings.py`, `committees.py`, `models/congress.py`, `parsers/congress.meeting_from_xml`, `parsers/house_evidence.py:50-116`, `house_documents.py:95-138`, `matching/house.py:24-36` | B16 fetchers; `committee_records`, `meeting_records` (D §6.4–6.5); `meeting_ref`, `committee_key` (D §7.5) | Pagination guards, incremental relisting, JSON→XML fallback with identity check, typed envelopes, House rendition grouping, meeting directory regex, `hl` committee rule | Fetch through the raw writer; no JSONL state; strip the API key; completion rows; strip the 4-letter `meeting-id` prefix | 600–900 (4.2) |
| 9 | **HTML/XML link extraction**: `document_links.tree_document_links` (`:121-161`), `page_content.page_trees` (`:8-42`), `archive_links.related_links` XML branch (`:225-246`), `house_evidence.document_group` (`:50-70`), `models/documents.DocumentLink` | `html`/`xml` readings with `links`, `base_href`, `group_path` (D §6.2) | One lxml pass over link elements, `<base href>`, meta refresh, Next.js and JSON-LD data, indexed XPaths that already have the `group_path` shape | Keep every link as written in document order; no resolution or dedupe; generic `group_path` (add `witness-document`); `remove_date`; XML text from the group description | 300–500 + the edge cases (4.2) |
| 10 | **Sniffing**: `document_links.response_kind` + `binary_pdf_header` (`:164-204`), `capture_inspection.inspect_body` (`:71-150`), `document_evidence.document_body_fields` (`:221-248`), `archive_members.is_office_zip`, `file_wrapper.py`, caption signatures | `sniff` reading (D §6.2, A §8.3) | Binary-preamble PDFs, `rtfd`, BOMs, XML only from a full parse, HTML-in-XML, docx vs ZIP, WEBVTT, `#EXTM3U` | Drop every media-type fallback; map to D's values; record a version | 150–250 + cases (4.1, 4.2) |

Next in line:

11. **PDF copy job** `pdf_backfill.py` + `put_pdf_file` → P B13 (4.1 §2.6): streaming decompress, SHA-256 and `%PDF-` checks, create-only `.pdf` PUT with Content-MD5, dry run, 210 test lines. Change the candidate set, the 512 MiB cap, the HEAD pre-check and add verification records. *Saves 150–250.*
12. **ConnectedComponents kernel** (`topology.rs:31-280`) → C4: union-find with a budgeted streaming scan. *150–250 Rust.*
13. **CLI chassis** (`main.rs`, `error.rs`, `deny_unknown_fields`, JSON stdout) → C7. *≈ 300 Rust.*
14. **Engine pin check** `docspec_client.verify_runtime` + `resolve_docspec_binary` → A §12, with mandatory pins, no PATH fallback and a Linux digest. *80–120.*
15. **Recovered-copy time** `prepare_corpus_recovery_source_records.py:130-158` → D §5.2 `retrieved_at` for imports, with an explicit basis. *100–150.*
16. **Create-only upload and If-Match flip** `viewer_publication/client.py:266-391` → A §10.3.4, §10.3.6 (add Content-MD5 and the 412 HEAD). *≈ 100.*
17. **ID formulas and compact JSON** `index/bipartite.py:165,197`, `index/schemas.py:377-378` → P E3 golden vectors. Small, but it fixes byte parity.
18. **Version digests** `parser_fingerprint`, `evidence_fingerprint`, `recovery_fingerprint` (4.1 §3.5) → D §7.1 parser, sniff and catalog versions.
19. **F0 converter pieces** `filename_exports.py:285-620` (fold, facets, occurrence flattening) → P §5.4. *≈ 300 of a throwaway tool.*
20. **Registry seeds** with real samples: file shapes (`document_links.py:9-11`), capture scope (`archive_links.py:18-63`, `committee_discovery.py:16-44`), archive wrappers (`archive_links.py:20-23`, `webharvest_committee_map.split_replay`), error words (`document_evidence.py:241-246`, `corpus_recovery/html.py:13-16`), recheck keys (`source_family.family`). These fill 5 of D §7.1's 13 registries.

## 3. The plan's delete table and keep list, checked

### 3.1 P §6.6 delete table, row by row

| Plan row | Plan estimate | Measured (src + tests) | Correction |
|---|---|---|---|
| Python incremental catalog: 22 modules, the `catalog/` facade, `incremental_boundary_proof.py` | 9,509 + 6,744 | 22 modules (16 `catalog_*`, 5 `source_*`, `raw_catalog`) **9,066** + facade **48** + proof **261** = **9,375** src. Tests: **9,018** congress_api lines in files that import the incremental catalog and only other replaced groups, + 55 for the proof | Source is within 1.5%. **Add `native_features.py` (1,270)**: the DocSpec adapters and the Python CC fallback serve only this layer. Tests are about 34% higher than estimated, and overlap rows 2 and 3. The proof script is a dormant spike, not live catalog code (4.4). |
| Python rebuild path: `catalog_staging`, `catalog_publication`, `catalog_cache`, `catalog_validation`, `index/*`, oracle files | at cut | **6,840** src in the rebuild group, less `LocalStore` (114, keep) = **6,726**; shims 225; tests ≈ **11,006** congress_api lines (rebuild and shim imports only) | Keep `LocalStore` (`catalog_cache.py:23-136`): it is a raw store, and P B3's refusal matrix names it. Lift the rules listed in 4.1 §3 first. |
| Raw index: `partition_routing`, `raw_state_routes`, `raw_changes`, the Python merge, the `raw.json` schema backfills, the retention planner (147) | at cut | Raw-index group **5,102** src; the retention planner is `native_capacity.py:430-576`, **147** lines (confirmed). After lifting the receipt builder (≈ 186) and folding the PDF migration (83) into B13: ≈ **4,670** at the switch, plus the exclusion gate (162) that B4 deletes earlier. Tests: **2,334** congress_api lines import only this group | "The Python merge" is in two places: `raw_storage._merge_states` (in this group) and `docspec_client/specs.py:476-692` (217, 4.4). Also dying with it, unnamed: `.github/scripts/verify-capture-run.py` 323 + 497 (4.3), `acquisition/recovery_queue.py` 139 + 58 and `retained_import.py` 47 + 119 (4.2). |
| Viewer publication: journal, resume and attempt route | 2,786 + 2,005 | **2,682 + 2,180** core | Close. Unnamed but dying with it: 609 + 657 (preflight, release identity, resume and CLI shims), 567 tests in `.github/tests`, 97 lines of `pipeline_status.py`, the 233-line workflow. Move the prefix firewall (`client.py:124-135`) into B3 first (4.3). |
| Viewer publication: v6 preparer and v6 reader branch | 1,695 + 1,112 | Preparer **3,294 + 2,682**; `filename_viewer.py` **871**; reader branch **1,293 + 940** | About 2.5 times too low: **5,458 + 3,622** (4.3). |
| `docspec_client`'s HTTP custody path, fallbacks, pure-Python BLAKE3, "if nothing else uses it" | at cut | Custody path 2,267 + 187 | **Cannot go at the switch:** news_lake (parked, P §7) and the committee explorer use it. What can go: archive-only builders ≈ 530 + 321; the BLAKE3 fallback (107) only by adding the `blake3` dependency; shims (124) only after news_lake changes imports (4.4). |
| Shims and legacy formats | 2,064 + 1,058 | Retention shims **225** (including three facades with zero importers, 112) + the import-time monkeypatch `raw_storage.py:50-72` (23); legacy schemas and converters (`raw_schemas.py:51-88`, `raw_values.py:24-64`, `catalog_cache.legacy_capture_digest`, `catalog_rows._legacy_table`) live inside modules already counted in rows 1–3; viewer shims are counted in rows 4–5; docspec_client shims are blocked by news_lake | This row mostly **double-counts** rows 1–6. Measure only what remains after them; in retention nothing does. |
| Measurement scripts for deleted subjects | 1,862 + 723 | Delete **2,725 + 531**; keep 427 + 192 | Source low by about 860; the 723 test lines include scripts P A11 should reuse (4.3). |
| F0 converter and the one-off PDF copy job (after B13) | at cut | PDF job: `pdf_backfill.py` 243 + `migrate_pdf_bodies_to_uncompressed` 83 + CLI 96 + shim 16; test 210. F0 does not exist yet; its source is `filename_exports.py` 1,254 + 383 | Count `filename_exports.py` (the unwired ExportPin route) here (4.3). |
| Custom-domain path allowlist and its tooling | at cut | Tooling 722 + 211; WAF part only *est.* 150 + 60 | **Do not delete whole:** the same files carry the CORS, cache, CSP and `?filename=` rules A §11.7 keeps (4.3). |
| docspec-rs | 14,383 certain, up to 2,101 more | Reproduces exactly | P's own items miss 3,189 + 1,200 + up to 389 + 566 of tests and handlers: **≈ 19,727**. Families P does not list: **≈ 20,855** (backfill 13,245; schema evolution 1,572; corrections 1,548; evidence updates 2,613; CC wrapper ≈ 1,565; …). Conditional: retention inventory 7,080 + 7,342, UDAFs 2,112. news_lake still calls lifecycle routes, and history cannot go before `compact_lifecycle` stops calling it (4.5). |

### 3.2 What the delete table misses

| Missing item | src + tests | Where |
|---|---|---|
| `native_features.py` | 1,270 + shared | 4.1 |
| Review tools bound to catalog group digests (P §2 says they survive) | 916 + 644 | 4.1 §5 |
| Viewer custody helpers (`viewer_inventory.py`, `control_documents.py`) | 126 + 662 | 4.1 |
| Capture-time readings: `capture_metadata.py` (in the raw-index group) and `raw_sync.py:288-293,422-439` | 310 + shared | 4.1, 4.2 |
| `cli/raw_sync.py` catalog and adoption modes; `cli/document_index.py`; `replay/*`; `recovery_queue.py`; `retained_import.py` | ≈ 155; 71; 346 + 980 shared; 139 + 58; 47 + 119 | 4.2 |
| corpus_recovery's raw-index, catalog and viewer coupling | ≈ 1,280 + 1,586 | 4.4 |
| `tests/e2e` (tests deleted layers, or nothing: 15 of 31 files import no production code) | 8,403 tests | 4.4 |
| ExportPin route; dormant compaction; review publication path; `verify-capture-run.py`; docs to rewrite | 1,382 + 383; 366 + 332; 188 (+907 JSON) + 183; 323 + 497; 592 md | 4.3 |
| 27 mixed test files that import surviving and replaced retention groups, which must be split, not deleted | 5,948 tests | 4.1 |

### 3.3 P §8 keep list: corrections

- **`physical_body_object_key` cannot stay unchanged.** It guesses `.pdf` from a format (`body_keys.py:50-66`); D §7.5's `suffix()` reads the recorded suffix, and new bodies use `''`. `derive_body_key` and the shard check do stay unchanged (4.1 §2.2).
- **Recovery `checked_put` and recovery admission cannot stay unchanged.** `checked_put` reads every write back and the body loop GETs before each PUT, against A §7.1; admission checks `indexes/raw.json`, which the switch deletes (4.4, 6.4 S7).
- **"MD5-verified uploads"**: true today for `R2Store.put_file`, `AsyncBodies.put` and `put` (Content-MD5 plus ETag compare). Keep.
- **`--verify-publication`'s Chromium checks** live in `verify-live-publication.mjs`, which P §6.1 lists under "replaces at the switch". Repurpose that file (4.3 §2.5).
- **Engine:** only the ConnectedComponents kernel serves the target; `Strict<T>` lives in the retention inventory and goes with it; `BackendCapability` is lifecycle-only (4.5).
- **"Review tools survive" (P §2)**: they are bound to catalog group digests and must be rewritten against link keys (4.1 §5).


## 4. Packages

One section per package or package family. Section 4.1 is the parent's own pass; 4.2 to 4.5 come from the parallel read-only passes (headings demoted, text unchanged). Inside each package section, a bare "§n" refers to that section's own numbered subsections; "A", "D" and "P" refer to the specs.

### 4.1 congress_api/retention

Scope: `packages/congress_api/src/congress_api/retention/` (98 Python files, 27,799 lines; the groups below sum to the same total) and every test that imports it. Paths are relative to that folder unless prefixed. Counts come from `parent/inv_ret_groups.py` (output `parent/ret_groups.json`); importers come from `parent/inv_ret_imports.py` (output `parent/ret_import_graph.json`). Both use the project venv with `-I` and only parse files.

**How tests are attributed.** A test file belongs to a group when every retention module it imports is in that group. Tests that import several groups are reported under "shared". The robust number for deletion is the split below, because the replaced groups go together at the switch:

| Retention-importing test lines (all test trees) | Lines | Files |
|---|---:|---:|
| Import only replaced groups (RX, IC, RB, SH, VW) | 26,810 | 127 |
| ↳ of which in `packages/congress_api/tests` | 22,358 | 106 |
| ↳ in `packages/viewer_publication/tests` (also counted by the site section) | 2,212 | 12 |
| ↳ in `packages/corpus_recovery/tests` (also counted by the other-packages section) | 1,269 | 5 |
| ↳ in `.github/tests` | 971 | 4 |
| Import only surviving groups (RW, PDF, WK, REV, EDGE) | 12,207 | 65 |
| Mixed: must be split at the switch | 5,948 | 27 |

Within the 22,358 congress_api lines: 9,018 touch the incremental catalog, 2,334 only the raw index, 11,006 the rebuild path and its shims.

#### 1. Summary

| Group | Class | Target component (spec §) | src | tests (exclusive) |
|---|---|---|---:|---:|
| **RW** raw writer and capture checks: `r2.py`, `body_files.py`, `body_keys.py`, `archive_members.py`, `bundles.py`, `capture_inspection.py`, `capture_url_admission.py`, `image_tools.py`, `pdf_tools.py`, `write_recovery.py`, `raw_progress.py` | **Keep / Repurpose** | raw writer (A §7.1–7.2, D §5.1–5.2); `sniff` reading (D §6.2) | 1,698 | 5,817 |
| ↳ `LocalStore` (`catalog_cache.py:23-136`) | **Keep** (move next to `r2.py`) | local raw store; P B3 refusal matrix names it | 114 | in RB tests |
| **Receipt and body builder**: `raw_archive.py:94-237` (`prepare_capture`, `metadata_body_keys`, `body_payload`, `existing_body_info`), `raw_storage.py:237-278` (`store_public_body`) | **Repurpose** | receipt lines and `captures[]` entries (A §7.2, D §5.2) | ≈ 186 | in RX tests |
| **PDF copy job**: `pdf_backfill.py`, `raw_storage.py:280-362` (`migrate_pdf_bodies_to_uncompressed`) | **Repurpose** (fold into one, P B13) | `.pdf` copies and verification records (A §7.1, D §5.1, §5.3) | 243 + 83 | 210 (`test_pdf_backfill.py`, mixed) |
| **Exclusion gate**: `raw_storage.py:75-236` plus `quarantine_body_key` (`body_keys.py:69-75`) and the `excluded_body_hashes` hooks in `r2.py`, `body_files.py`, `catalog_cache.py` | **Replace now** (P B4) | none: raw stays complete (P §3) | 162 + ≈ 30 hooks | in RW/RX tests |
| **RX** raw index and native raw selection: `raw_archive.py` (rest), `raw_storage.py` (rest), `raw_schemas.py`, `raw_values.py`, `raw_state_map.py`, `raw_state_routes.py`, `raw_capture_pages.py`, `raw_changes.py`, `raw_readings.py`, `raw_reading_inventory.py`, `raw_readings_adoption.py`, `raw_adoption.py`, `raw_adoption_inputs.py`, `partition_routing.py`, `native_capacity.py`, `capture_metadata.py` | **Replace** | `captures` (D §6.1), `url_state` (D §7.7), readings producers (A §8.3) | 5,102 (≈ 4,670 after the lifts above) | 2,663 |
| **IC** incremental catalog: 16 `catalog_*` modules (adoption, availability, batches, dependencies, dependency_preparation, dependency_storage, inputs, memberships, partitions, qualification, raw_updates, rows, scope, selection, types, updates), 5 `source_*` modules (update_proof, capture_inputs, inputs, observations, replay), `raw_catalog.py`, `native_features.py` | **Replace** | one model SQL plan (A §9, D §7) | 10,336 | 472 (9,018 shared) |
| **RB** rebuild catalog and document index: `catalog_staging`, `catalog_publication`, `catalog_cache` (less `LocalStore`), `catalog_validation`, `index/*` (9 files, 4,134), `document_evidence`, `document_recovery`, `saved_responses`, `source_aliases`, `immutable_metadata`, `derived_files`, `index_selector` | **Replace**, with rule lifts (§3) | model SQL (D §7.3–7.10); `filename_readings` producer (D §6.3) | 6,840 | 975 (most shared with SH) |
| **REV** review tools: `document_review_{bundle,catalog,portable,receipts,viewer}.py`, `document_reviews.py`, `review/__init__.py` | **Replace** the binding; **Repurpose** the form vocabulary | provenance `reviews` on link keys (D §5.3, §7.9) | 916 | 644 |
| **WK** weekly and committee-explorer retention: `__init__.py`, `weekly_tables`, `tables`, `meetings`, `committees`, `gpo`, `house`, `senate`, `captions`, `transcripts`, `rejected_pages`, `jsonl` | **Keep** (parked, P §7; out of the archive's scope) | none; `meetings.py`/`committees.py` stop being the archive's source after B16 | 2,154 | 5,436 |
| **SH** shims and facades: `docspec.py`, `docspec_host.py`, `document_index.py`, `catalog/__init__.py`, `raw/__init__.py` | **Replace**; `catalog/`, `raw/` and `review/` facades are **Dormant** | none | 225 | 4,088 (tests that import the `document_index` shim; they test RB) |
| **VW** viewer custody helpers: `viewer_inventory.py`, `control_documents.py` | **Replace** | none (release manifest digests, D §8.1) | 126 | 662 |
| `r2_edge_rules.py` | see the site section (Repurpose minus the WAF) | origin rules (A §11.7) | 159 | 107 |

All 75 `PYTEST_CURRENT_TEST` branches in the repository sit in replaced retention modules (`grep -rn` over `retention/`: 75 hits in 24 files, none in RW, PDF, WK or REV). That confirms P B11's "the other sites go with the old layers".

#### 2. Keep and Repurpose: raw writer path (A §7)

##### 2.1 `r2.py` (597): create-only, MD5-verified object writes

- `R2Store.put_file` (`r2.py:407-444`) already does A §7.1 step 3 for a file on disk: one `put_object` streamed from the file, `IfNoneMatch='*'`, `ContentMD5` computed from the file, a 412 returns `False`, and the ETag is compared with the MD5 after the PUT. It never uses multipart.
- `AsyncBodies.put` (`r2.py:151-165`) is the in-memory twin, with the same create-only PUT, Content-MD5 and ETag check, and refuses keys outside `bodies/`.
- `put_parameters` (`r2.py:111-124`) sets PDF headers (`inline`, immutable cache) for `.pdf` keys.

**Must change for A §7.1:**
- New compressible bodies go to the bare `<sha>` key with `Content-Encoding: gzip` and the original `Content-Type`; PDFs, images and archives go as-is. Today every body is gzipped to `<sha>.gz` with `Content-Type: application/gzip` (`put_parameters`, `:121-123`; `body_files.retain_body_file`, `:116-127`).
- Add the older-copy check: one HEAD of `<sha>.gz` before the PUT (A §7.1 step 2). Today there is none.
- Delete the `immutable` flag and the overwrite default of `put` (`:338-398`); that is P B3. `put` also carries the raw-index manifest cache (`:340-375`) and the `indexes/` If-Match path (`:381-385`), which go with the raw index.
- Delete the exclusion-gate hooks (`:370-372`, `:415-419`).

##### 2.2 `body_files.py` (159) and `body_keys.py` (73)

- `retain_body_file` (`body_files.py:105-159`) hashes and gzips one spooled file in a single pass, refuses a file that changed during retention (`:128-129`), and uploads with `put_file`. **Repurpose** as the writer's per-body step. **Change:** on a 412 it downloads the stored object and decompress-compares it (`:137-148`). A §7.1 says a 412 is `unchanged`, "with no HEAD and no comparison". It also writes the `.pdf` copy for new PDFs when `store_uncompressed_pdfs` is set (`:149-153`); new writes need no copy, because a PDF is stored as-is at `<sha>`.
- `body_key_digest` (`body_keys.py:11-18`) is the body-key shard check on the P §8 keep list. **Keep.**
- `derive_body_key` (`raw_schemas.py:179-193`) returns the logical key `bodies/sha256/<aa>/<sha>.gz` for every body. It matches D §3's "logical body key", the ID input. **Keep** (P §8).
- `physical_body_object_key` (`body_keys.py:50-66`) guesses `.pdf` or `.gz` from a media type, filename or format. **Change required, so P §8's "keep unchanged" is wrong:** D §7.5 `suffix(body)` is `.pdf` only with a verification record, else `''` when a capture recorded `stored_suffix ''`, else `.gz`. The function must take the recorded suffix, not a format hint. Its golden tests (`test_retained_body_keys.py`) stay, with the `''` case added.

##### 2.3 Receipt builder: `raw_archive.py:94-237`, `bundles.py` (133), `archive_members.py` (244)

- `bundles.separate` (`bundles.py:28-117`) walks a response record, replaces every embedded body with a `captures[]` entry carrying `pointer`, `sha256`, media type and `fidelity`, and `restore` (`:118-133`) inverts it. That is D §5.2's `captures[]` with `pointer`.
- `prepare_capture` (`raw_archive.py:103-204`) builds the receipt line and expands archives:
  - ZIP and Apple FileWrapper (`rtfd`) bodies, only after a complete `saved` outcome (`:120-127`);
  - Office Open XML and ODF packages stay whole, detected by suffix, media type or `is_office_zip` (`:130-139`);
  - each member becomes its own `captures[]` entry with `pointer = ['archive_members', i, …]`, `context_url` = the container's URL and `original_path` = the member name (`:172-179`), which is D §5.2's `context_url` and `member_path`;
  - the payload budget bounds member bytes (`:141-152`).
- `archive_members.py` reads members without extraction under `ZipLimits` (`:17-28`: archive 64 MiB, member 64 MiB, total 128 MiB, 1,024 members, depth 1), refuses ZIP64, multi-disk and encrypted members, and keeps duplicate names apart by `entry_index`.

**Repurpose** all three for A §7.2. **Changes:**
- write `member_path` (today `original_path`), `sniffed_format`, `sniff_version`, `stored_suffix`, and on the storing line `stored_md5` and `stored_bytes` (D §5.2);
- stop writing `links` into the line (`raw_archive.py:115-116`, `:183-198`) and stop parsing member links at capture (`:182-200`);
- member media type is guessed from the extension (`:166-170`); D §5.2 keeps `media_type` as "the server's claim", which a member does not have, so record null and let `sniff` decide;
- the 64 MiB archive limit means a large ZIP gets no member entries, so D §6.2's ZIP fingerprint ("taken from `captures` without reading the ZIP") does not exist for it. The specs set no expansion limits. See §6 rule conflicts.

##### 2.4 Capture checks: `capture_inspection.py` (150), `pdf_tools.py` (182), `image_tools.py` (74)

- `inspect_body` (`capture_inspection.py:71-150`) classifies bytes: empty; challenge markers in the first 8 KB (`cf-chl-`, `<title>just a moment`, `verify you are human`, `<title>access denied`, `:77-86`); video and audio; images decoded once; PDFs need `%%EOF` in the last 8 KB or a readable structure (`:95-99`, with `pdf_tools.readable_pdf`); FileWrapper; XML only from a complete parse; JSON; `#EXTM3U`; ZIP, legacy Office, RTF, `WEBVTT`; text.
- **Repurpose** as the core of the `sniff` reading (D §6.2) together with `document_links.response_kind` (acquisition section). **Change:** drop the media-type branches (`:87-88`, `:111-113`, `:131-133`, `:141-146`), which A §8.3 forbids; map to D's format values. The PDF tail check and the challenge markers have no home in D (§6 below).
- `inspect_capture` (`:21-68`) decides capture outcomes (`challenge`, `invalid_document`, `html` …) and harvests links during capture. In the target capture records facts and the model classifies (A §9.2), so this half goes.

##### 2.5 `capture_url_admission.py` (27)

Generated XML probes (guessed URLs) are not re-seeded unless an independent publisher link exists (`:14-27`, used at `raw_archive.py:244-254`; commit `f461f40e`). The target loses this: D §7.7 keeps one `url_state` row per requested URL and rechecks it at the family interval forever, probes included. See the knowledge list.

##### 2.6 PDF copy job: `pdf_backfill.py` (243) and `migrate_pdf_bodies_to_uncompressed` (`raw_storage.py:280-362`)

What `pdf_backfill.backfill_uncompressed_pdfs` (`:159-243`) already does for P B13:
- stream-decompresses a `.gz` body to a temp file, checks the decompressed SHA-256 against the key and the `%PDF-` header (`_decompress_and_verify_to_file`, `:105-129`);
- uploads `bodies/sha256/<aa>/<sha>.pdf` with `put_pdf_file`, which is create-only with Content-MD5 and PDF headers (`r2.py:446-450`);
- never touches the `.gz` source (docstring `:1-7`);
- has a dry run.

**What must change for B13:**
1. **Candidate set.** It takes candidates from `accepted.json` entries whose type or name looks like a PDF (`_load_accepted_entries`, `_is_entry_pdf`, `_iter_pdf_digests`, `:31-86`). B13 is "every older gzip PDF". That set has to come from the capture rows of older receipts plus a sniff of the first bytes, not from the viewer's accepted list.
2. **Size cap.** `MAX_PDF_BACKFILL_BYTES = 512 MiB` (`:29`) refuses larger PDFs. The largest body is 1.19 GB (A §5). Lift it to the single-PUT limit.
3. **Existence check.** It HEADs every `.pdf` key first (`_object_exists`, `:89-95`). B13 says "copies that already exist return 412 and get their record", so drop the pre-check; on a 412, one HEAD reads the ETag for the record.
4. **Verification records.** None are written. B13 and D §5.3 need a record for both the `.gz` source and the `.pdf` copy (`key`, `size`, `etag`, `sha256_verified`, `checked_at`, `job`).
5. **One path.** The in-memory variant (`_decompress_and_verify_bytes`, `:132-156`, and the `store.read` branch, `:226-237`) duplicates the streaming one. Keep streaming only.
6. **Fold in `migrate_pdf_bodies_to_uncompressed`.** That function lists every body (`store.keys('bodies/sha256/')`), reads each whole into memory, and also writes ZIP-member PDFs to `.pdf` keys (`raw_storage.py:330-354`). Member bodies are already captured as their own entries with their own `.gz`, so the member branch is redundant once candidates come from capture rows; drop it.
7. **Exclusions.** Both functions consult the exclusion gate (`pdf_backfill.py:170-180`; `raw_storage.py:290-294`); B4 deletes it.

The CLI entry is `viewer_publication/backfill_uncompressed_pdfs.py` (96) with a 16-line script shim (site section). The whole job is deleted after B13 runs (P §6.6).

#### 3. Replace: the rebuild catalog and document index (RB), with the rules to lift

The model SQL replaces this code. These are the parts whose rules or code are worth lifting, and the places where the code already implements a rule the specs define differently.

##### 3.1 ID formulas (`index/bipartite.py`)

- `source_identity` (`:165-167`) = SHA-256 of `compact([body_key, filename, source_url])`, with `compact` = `json.dumps(ensure_ascii=False, separators=(",", ":"), allow_nan=False)` (`index/schemas.py:377-378`). That is exactly D §3's compact JSON and D §7.4's formula.
- `compute_document_id` (`:197-205`) = SHA-256 of `["bodies", sorted distinct body keys]`, else `["sources", sorted distinct source_ids]`. Same as D §7.5.
- **No golden vectors exist today.** No test pins a fixed hex value for either function; `compute_document_id` is called directly only in `test_wave2c_bwac.py:164`, inside a fake engine. P E3 must create them, as it says.
- **The formula is implemented four times:** here; a streaming SQLite variant for large components (`bipartite.py:295-309`); docspec-rs `connected_components.rs:23-36` (Rust); and a Python fallback of the engine's whole CC transform (`native_features.py:1036-1177`, run when the engine lacks the variant, `:1233-1237`, added in `580b802b`). Only one survives: the model SQL's.

**Rule conflict: the inputs are not today's, so IDs will not match byte for byte.** A §9.1 says the ID formulas keep today's exact inputs, so `source_id` and `document_id` match the current system byte for byte. The serialization matches, but the inputs differ in three measured ways:

1. **Several source triples per capture row today.** `index/sources.py:119-145` (`source_names`) emits one `(body, filename, url)` triple for each of: the `Content-Disposition` filename (`:127-130`, `disposition_filename` `:86-103`, `filename*` preferred); the URL path basename of the context URL **and** of the final URL (`:131-136`); query parameters named `filename`, `file`, `name`, `document` or `attachment` (`url_document_names`, `:38-54`); and a retained local path when nothing else names the body (`:137-142`). D §7.4 has one effective filename per capture row (recovered name, member basename or the URL's last segment) and one source URL. So today's 1.68M source files include triples D will not produce, and D's work list (D §6.3) is a different set.
2. **D §5.2's header allowlist drops `Content-Disposition`**, so the target cannot recover header filenames from new receipts at all.
3. **`document_id`'s body set.** Today only "connectable" bodies count: 2xx, saved, non-empty, and a format in the document set **minus `html` and `binary`** (`document_body`, `bipartite.py:236-253`). D §7.5 uses every real file's body, web pages included. Every document with an HTML real file, or with an `application/octet-stream` body, gets a different ID.

Also unspecified in D: whether "the URL's last segment" is percent-decoded. Today it is decoded strictly, with `+` kept literal (`url_filename`, `sources.py:30-35`). `source_id` parity depends on matching that. And D §6.3/§7.4 do not say which URL is `source_url` (requested, final or `context_url`); today both the context and the final URL produce triples.

The practical consequence is small, because public links do not depend on `document_id` (A §10.1). But E3's golden vectors and E4's parity must expect these differences, and A §9.1's sentence should say "the same formulas and serialization", not "match byte for byte".

##### 3.2 Endpoint grouping (`bipartite.py:20-51`, `:222-233`)

`entry_key` groups "download variants of one endpoint": it drops `download`, `download=1` and `download=true` from the query (and from a `?` embedded in the path, via house-naming's `QUERY`) before comparing endpoints. D §7.2 keeps `download=1` in `url_key` because it "almost always selects a different file". Either may be right: today's rule merges `x.pdf` and `x.pdf?download=1` into one endpoint; D's keeps them apart (and `same_body` will still join them when the bytes match). Flag for the S sample.

##### 3.3 Record roles today (`index/sources.py`, `document_evidence.py`)

- `document_evidence.document_body_fields` (`:221-248`) sniffs content (image, PDF, ZIP, `rtfd`, House XML roots, HTML by regex) and marks four exact page titles as error pages (`:241-246`: the House repository's "Not Found | Committee Repository | U.S. House of Representatives", "Page Not Found | govinfo", "U.S. Senate: 404 Error Page", "403 Forbidden"). D's generic error words catch all four; keep them as registry samples.
- `house_record` (`:185-218`): `amendment-doc` roots are documents of kind `amendment`; `committee-meeting` is a source record; **`witness-list` is a document** (`:209-212`). D §7.3's source-record registry lists "meeting and witness records", so witness lists would stop being documents. Owner decision.
- `schemas.extract` (`index/schemas.py:437-493`) recognizes records by URL before calling house-naming: GovInfo `metadata/pkg/<id>/{mods,premis,mets}.xml`, `api.govinfo.gov/collections/<C>/<ts>` listings and `packages/<id>/summary`, `api.congress.gov/v3/{hearing,committee-meeting,bill}/…`, and error pages at `docs.house.gov/committee/Error/Error.aspx` and `www.govinfo.gov/error`. D covers the API hosts (API-endpoint registry) and MODS/PREMIS by XML root, but **METS is not in D's source-record roots**, and the two error-page URLs have no registry. It also retries house-naming without the URL on `invalid-source-url` (`:485-490`), which the D §6.3 producer should keep, and swallows every other `NamingError` (`:491-492`), which D §6.3 replaces with `status = error`.
- `recognize_publisher_page` (`index/sources.py:418-441`) marks a saved HTML page as a hearing or meeting page when the page was recorded for its own URL with a hearing/meeting title or type. D §7.3 has no such role; listing pages come from link-count thresholds.
- `saved_responses.saved_response` (`:31-57`) applies 29 human-reviewed `(url, body_key)` labels from `saved_response_reviews.json` (soft 404s, landing pages, JavaScript shells …). D has no home for them (knowledge list).

##### 3.4 Link context and meeting context (`index/document_sources.py`, `index/records.py`)

`read_document_sources` (`index/records.py:494-553`) is the function the brief names. What it does:
- replays scraper records from receipts by family and receipt suffix (Congress.gov meetings, Senate pages, House sites, House state, document inventory, `/receipts.jsonl`; `:509-534`);
- re-parses bodies only in three cases: House meeting and witness XML (`add_retained_house_documents`, `:448-491`), Senate HTML pages not already seen (`add_retained_senate_pages`, `:401-445`), and records marked `html_requires_document_discovery`, which it re-reads with the Senate parser `source_details` (`:535-551`);
- feeds `DocumentSources`, an occurrence graph that propagates labels and meeting context along redirects (`publisher_redirect`), parent-page links (`linked_page`) and URL repairs (`document_sources.py:151-229`).

**Class: Replace.** The target gets link labels from every HTML and XML page's `readings.links` (D §6.2) and joins them by `url_key` (D §7.10), so there is nothing per-family to lift. The generic link pass to lift is `document_links.tree_document_links` (acquisition section). What carries signal:
- **Labels come partly from scraper records inside receipts** (`add_link` reads `publisher_occurrences` from receipt `links`, `document_sources.py:245-324`). These are the "facts only in derived tables" of P §9.
- **Redirect-aware context.** A link to a URL that redirected is credited to the final URL (`_add_transfer`, `:183-206`). D §7.10 matches `linked_from` against the occurrence's endpoint `url_key` only, i.e. `context_url`. A link written with the pre-redirect URL will not match unless the join also tries `requested_url`. Spec gap.
- **Feeds and sitemaps never pass context** (`collection_url`, `:143-148`, and `transfer_occurrence`, `:151-161`). D §7.10 would name an RSS feed or sitemap as `linked_from` when it is the earliest linking page.
- **Labels the target drops.** Today an occurrence also keeps the XML group's description, the paragraph around the link, page headings and witness cards (`:494-544`). D §7.10 keeps link `text`, `doc_type` and `add_date` only.
- **Bug, latent:** `records.py:483` strips only `HMKP` from `meeting-id`. House meeting IDs are `HHRG…`, `HMKP…` or `HMTG…` + event ID (fixtures under `packages/congress_api/tests/fixtures`: `HHRG106245`, `HMKP106292`, `HMTG100431`). For D §6.5, strip the 4-letter meeting-type prefix.
- **Duplicate code:** `index/sources.py:234-388` repeats `capture_schema`, `capture_batches`, `_capture_tables`, `record_from_capture_row` and `add_retained_senate_pages` from `index/records.py:26-130,401-445`, line for line (`diff` shows only a blank line). It was left behind by the `e4b3216b` split.

##### 3.5 Version fingerprints to lift (D §7.1)

Three functions already define a version as a digest of code and data, which is the rule D §7.1 should state for parser, sniff and catalog versions:
- `index/metadata.py:488-497` `parser_fingerprint`: house-naming's `.py` and `.json` files plus `extract`'s source. Seed for `catalog_version` (D §6.3).
- `document_evidence.py:38-53` `evidence_fingerprint`: reader modules plus the Poppler and Pillow versions. Seed for the `xml`/`html` parser versions.
- `document_recovery.py:19-20` `recovery_fingerprint`: the module's own bytes.

The counter-example is `source_update_proof.py:14-23`, a hand-listed module set that went stale when `document_index.py` became a shim (lessons, mistake 12).

##### 3.6 Other RB pieces

- `read_retained_body` (`document_evidence.py:130-163`) reads `.gz`, falls back to `.pdf`, bounds the read and checks the SHA-256. The readings producers need the same with the `''` suffix and `Content-Encoding` handling. Small lift.
- `catalog_cache.py` minus `LocalStore`: body-inspection result caches and catalog input fingerprints (`:139-271`). Replace.
- `immutable_metadata.py`, `derived_files.py`, `index_selector.py`: custody and selection for derived catalog files. Replace; release manifests carry digests (D §8.1).
- `capture_metadata.py` (310, in RX): reads every new body during capture (PDF opening page, cover fields, page count) and writes `indexes/processing/body-results/` parts. The target reads no embedded PDF text for now (D §6.2), so the cover-derived kinds (`content_document_kind`, `content_citation`, `content_congress`, `content_amendment_type`; `parsers/document_cover.py:8-9`) disappear. Deliberate in D, but it is a parity cause for E4 (amendment and witness-statement covers).

#### 4. Replace: raw index (RX) and incremental catalog (IC)

- **RX.** Hash-prefix routing (`partition_routing.py`), state route pages (`raw_state_routes.py`), copy-on-write capture and state leaves with Python merges (`raw_storage.py:363-1446`), reading inventories and adoption (`raw_readings*.py`, `raw_adoption*.py`). Content-addressed keys, `captures` and `url_state` replace it. The retention planner is `native_capacity.py:430-576` (147 lines, P's figure confirmed); it classifies unmatched objects as reclaimable (lessons, mistake 2). `raw_storage.py:50-72` monkeypatches `raw_state_routes` at import.
- **The two local-file substitutions.** `raw_storage.py:654-672` (named by P B11) and `source_capture_inputs.py:61-74`, which P misses: in production it substitutes `.cache/docspec-catalog/captures-0.parquet` for remote capture batches when row-group sizes match. Both are live until the switch.
- **IC.** The incremental catalog: dependency closure, memberships, coalesced batches, proofs, adoption and qualification over native storage. `native_features.py` (1,270) holds the DocSpec adapters for it (change streams, schema evolution, backfill, CC refresh) plus the Python CC fallback. No signal to keep beyond the lessons list: the model is recomputed whole (A §5).

#### 5. Review tools (REV): Replace the binding, keep the vocabulary

- `document_reviews.apply_review_candidate` (`:44-81`) applies an assistant review only when `group_sha256` (a digest of the whole document and every member row, `review_group_digest` `:33-41`) still matches, then replaces `document_kind` with the reviewed forms. `document_review_receipts.py` verifies review evidence files by digest.
- D §7.9 targets link keys instead, so a review follows a file through merges, and `kind_override` is the verdict. The group-digest binding cannot survive: every model run changes groups.
- **Keep:** `SUPPORTED_FORMS` (`document_reviews.py:18-21`, 13 forms) as the allowed values of `kind_override`, and the evidence-digest check as the rule for review records.
- **Plan gap (also in the site section):** P §2 says review tools survive, but they are bound to catalog groups, and no plan step migrates the 86 published assistant reviews into provenance `reviews`.

#### 6. Rule conflicts found in retention (code vs spec)

1. **IDs will not match byte for byte** (§3.1): several source triples per row, Content-Disposition names, HTML excluded from `document_id` bodies, decoding unspecified.
2. **`download=1` endpoint variants** merged today, kept apart by D §7.2 (§3.2).
3. **`witness-list` XML** is a document today, a source record in D §7.3 (§3.3).
4. **METS records** are recognized today by URL; D's source-record roots omit METS (§3.3).
5. **Physical key by guess** today, by record in D §7.5 (§2.2).
6. **412 → download and compare** in `retain_body_file` (`body_files.py:137-148`) vs A §7.1.
7. **Every body gzipped to `.gz`** vs A §7.1's bare key and `Content-Encoding`.
8. **Archive expansion limits** (64/64/128 MiB, 1,024 members) exist only in code; A §7.2 and D §6.2 assume member entries for every ZIP.
9. **PDF completeness** (`%%EOF` or readable) is required today (`capture_inspection.py:95-99`); D §7.3 accepts any complete 2xx PDF.
10. **Challenge pages** are detected by body markers today; D §7.3's error signs read only title, heading and text size.
11. **Generated probes** are not re-seeded today; D §7.7 rechecks every requested URL.
12. **Linked-from** follows redirects and skips feeds today; D §7.10 does neither.
13. **`meeting-id` prefix**: the old index strips only `HMKP` (bug); D §6.5 needs the numeric event ID.
14. **Plan §8 keep list:** `physical_body_object_key` cannot stay unchanged (§2.2).

#### 7. Dormant code in retention

| Code | Evidence | Purpose (from history) | Proposed target use |
|---|---|---|---|
| `catalog/__init__.py` (48), `raw/__init__.py` (34), `review/__init__.py` (30) | zero importers anywhere (AST graph; grep) | facades created in `e4b3216b` ("decompose docspec_client and retention") to group modules by layer | none as code. The grouping is the right one for what survives: put the raw writer (`r2`, `body_files`, `body_keys`, `bundles`, `archive_members`, `LocalStore`) under `raw/`, and the provenance review writer under `review/`, then delete the rest |
| `docspec_host.py` (20) | imported only by 4 test files | shim after `bdc40971` moved the host transport to `docspec_client` | none; tests should import `docspec_client` |
| `capture_url_admission.py` | live, but its rule has no target home | `f461f40e`: keep generated probes from being scheduled again | a capture-scope registry entry for probe families, or an exclusion of generated-probe URLs from the `url_state` queue |
| `saved_response_reviews.json` + `saved_responses.py` | live in the viewer path only | 29 human labels on saved responses | labels for P §5.3's sample, and provenance records if D gains a "not a document" verdict |

### 4.2 congress_api acquisition, parsers, transport, models, matching, cli, replay, transcripts, adapters; satellite packages

Scope: `packages/congress_api/src/congress_api/{acquisition,adapters,parsers,matching,models,transport,cli,replay,transcripts}/`, their congress_api tests, and `packages/committee_meeting`, `packages/congress_shared`, `packages/youtube_api`, `apps/committee_youtube`, `apps/inflation_gsheets`. Worktree `/Users/mikewolfd/Work/wt/ct-ticket-audit` at d9730967. `congress_api/retention/` is the parent's; calls into it are noted, not inventoried.

Method: static reading; `wc -l`; an AST import graph over `packages/ apps/ scripts/ tests/ .github/` (`inv_acq_imports.py`, output `import_graph.json`); test attribution by AST imports (`inv_acq_tests.py`); `git log` on candidate dormant files. No tests, builds or network.

Spec shorthand: A = engine-first-architecture.md, D = engine-first-data-model.md, P = simplification-plan-20261024.md.

#### 1. Summary

Line counts are measured `wc -l`. Test lines are the congress_api test files that import the group (by AST); most test files import several groups, so the "shared" figure double counts across rows. 143 distinct test files (26,762 lines) touch this scope; 85 of them (17,176 lines) also import `retention`, `viewer_publication` or `docspec_client`, so their fate follows the parent's classification as much as this one.

| Group | Class | Target component (spec §) | src lines | test lines |
|---|---|---|---|---|
| acquisition capture core: `raw_sync.py`, `streamed_recovery.py`, `retained_import.py`, `recovery_queue.py` | **Repurpose** the event loop, spooling budgets and range download; **Replace** replay mode, raw-index queue, capture-time readings, `recovery_queue` | raw writer / capture job (A §7.1–7.2, §12); B14 | 1,262 | 3,927 shared (capture + transport tests); exclusive 956 |
| acquisition B16 fetchers: `committees.py`, `meetings.py` | **Repurpose** (fetch loops, pagination guards, XML fallback) | committee and meeting fetchers through the raw writer (A §8.5–8.6, P B16) | 265 | 830 shared |
| acquisition inventory fetchers: `house.py`, `house_fallback.py`, `house_sites.py`, `senate.py`, `gpo.py`, `gaps.py`, `refresh.py` | **Keep** (they feed the committee explorer, a separate product) but they must also fetch through the raw writer, which P B16 does not list | meeting_records from House and Senate inventories (A §8.6) | 1,805 | ~7,693 shared |
| `acquisition/documents.py` + `transport/document_probe.py` | **Dormant** | proposed: labeling aid for the S sample (P §5.3) | 112 | 147 |
| parsers link + sniff core: `archive_links.py`, `document_links.py`, `page_content.py`, `file_wrapper.py` | **Repurpose** | `html`/`xml`/`sniff` readings (D §6.2), registries (D §7.1), `real_files` (D §7.3) | 607 | 781 direct + wide sharing |
| parsers meeting: `house_documents.py`, `house_evidence.py`, `house_xml.py`, `house.py`, `xml.py`, `congress.py` | **Repurpose** | XML links with `group_path` (D §6.2), `meeting_records` (D §6.5), `meeting_ref` (D §7.5) | 464 | shared |
| parsers Senate: `senate_page.py` (1,145), `senate.py`, `senate_player.py`, `senate_probes.py` | **Keep** for the explorer; **Replace** its archive use (link-label re-derivation in `retention/index`) | generic HTML reading (D §6.2) | 1,411 | shared |
| parsers House committee sites: `committee_pages.py`, `committee_discovery.py` | **Keep** (crawler for the explorer); exclusion rules seed the capture-scope registry | capture scope (D §7.1) | 466 | shared |
| parsers GPO: `gpo.py`, `gpo_hearings.py`, `gpo_text.py` | **Keep** (out of target scope) | MODS event IDs are a meeting_ref source the spec omits (§4) | 669 | shared |
| parsers explorer helpers: `document_cover`, `document_types`, `witness_pdf`, `witness_names`, `reviewed_witness_lists`, `captions`, `media`, `observations`, `text`, `legislators`, `gemini` | **Keep** (out of target scope); `captions.py` signatures feed `sniff` | — | 893 | shared |
| `parsers/source_family.py` | **Repurpose** | receipt `family` (D §5.2), recheck-interval registry key (D §7.1) | 179 | shared |
| transport fetch: `rust_fetch.py`, `source_capture.py`, `zyte.py`, `http.py`, `congress.py`, `senate.py` | **Repurpose** | the fetcher (A §7.1 spool, no cut-off; D §5.2 receipt fields) | 798 | shared (in capture row) |
| transport media: `audio.py`, `gemini.py` | **Keep** (out of target scope) | — | 271 | shared |
| models core: `base`, `content`, `transport`, `xml`, `congress`, `congress_xml`, `house`, `documents` | **Keep**; `congress.py` and `DocumentLink` **Repurpose** | JSON parser (D §6.4–6.5); link struct (D §6.2) | 994 | 410 exclusive + shared |
| models other: `gpo`, `senate`, `legislators`, `media`, `transcription` | **Keep** (out of target scope) | — | 1,294 | shared |
| matching target-relevant: `committees.py`, `house.py`, `meetings.py` | **Repurpose** (regexes, code rules) | `meeting_ref`, `committee_key` (D §7.5); `meeting_type` (D §6.5) | 232 | shared |
| matching, the rest (GPO/video/recording/Senate page matching, reviewed decisions) | **Keep** (out of target scope: committee explorer) | — | 1,765 | 383 exclusive + shared |
| adapters (all 14 modules) | **Keep** (out of target scope: committee explorer model builders) | — | 2,494 | 1,766 exclusive + shared |
| cli capture: `raw_sync.py`, `raw_progress.py`, `common.py` | **Repurpose** the capture path; **Replace** the catalog modes (~155 lines, est.) | capture job (A §12) | 675 | shared |
| `cli/document_index.py` | **Replace** (forwards to catalog modes) | model SQL (A §9) | 71 | 2 test files |
| `cli/sync_weekly_tables.py` | **Keep** (parked, P §7) | — | 336 | shared |
| cli inventory entry points: `committees`, `meetings`, `house`, `house_sites`, `senate`, `inventory`, `gpo_fetch` | **Keep** | — | 336 | shared |
| cli explorer entry points: `gpo_match`, `gpo_transcripts`, `senate_captions`, `transcribe` | **Keep** (out of target scope) | — | 298 | shared |
| replay: `gpo.py`, `house.py`, `senate.py` | **Replace** (readings backfill by parser version, A §8.3); not in P's delete table | — | 346 | 980 shared |
| transcripts | **Keep** (out of target scope) | — | 775 | 21 exclusive + shared |
| `packages/committee_meeting` | **Keep** (out of target scope: explorer schema) | — | 1,441 (incl. 98 example) | 329 |
| `packages/congress_shared` | **Keep** (`storage`, `custody`, `dates`, `auth` used by surviving writers) | raw writer, publish credentials | 919 | 199 |
| `packages/youtube_api` | **Keep** (out of target scope) | — | 1,498 | 280 |
| `apps/committee_youtube` (committee explorer) | **Keep** (out of target scope); a docspec-rs consumer; owns the P B6 layout writer | — | 5,878 | 1,165 |
| `apps/inflation_gsheets` | **Keep** (unrelated product: BLS CPI) | — | 663 | 0 |
| package `__init__`s | — | — | 44 | — |

congress_api in-scope source total: 18,830 lines (acquisition 3,404; adapters 2,494; parsers 4,692; matching 1,997; models 2,288; transport 1,115; cli 1,719; replay 346; transcripts 775).

#### 2. Detail per group

##### 2.1 acquisition capture core (1,262 lines)

`acquisition/raw_sync.py` (622) is the live capture loop that `raw-source-sync --capture-only` runs (`.github/workflows/capture-raw-sources.yml:340-355`).

What survives as the fetcher's engine room (Repurpose, A §7.1):
- Bounded concurrency with explicit memory and spool budgets: `_ByteBudget` (`raw_sync.py:45-70`), `SyncBackpressurePolicy` (`:73-107`), the scheduling loop (`:517-560`), retry-later delays with at most 3 in-run retries (`:361-365`), Zyte-auth stop (`:381-382`), clean shutdown that finishes admitted files (`:561-570`).
- Shared upload de-duplication within a run (`retain`, `:441-452`), matching A §7.1 step 1 ("uploads nothing if the body is already in the run's own set").

What goes (Replace):
- **Replay mode** (`acquire`, `:297-309`): re-reads a retained body when `body_key` is set and `links_scanned` is false. P F2 names `raw_sync.py:298`; confirmed.
- **Raw-index queue**: `SyncQueueManager.initialize_queue` (`:113-197`) builds the queue from `archive.capture_queue` (`:143-153`) or a scan of `archive.state` (`:155-183`). Target: `url_state` from the live release (A §12, D §7.7).
- **Capture-time readings**: `CaptureMetadata` (`:291-293`) and `read_metadata` (`:422-439`) parse every new body inside the capture run, in a process pool. In the target, parsing is a lake producer (`readings`, A §8.3); capture records only the sniffed format. P does not list this removal.
- **Body re-read on a create conflict**: when `bodies.put` reports the key exists, the loop downloads the whole object and recomputes its info (`:412-415`). A §7.1 step 3: a 412 is `unchanged`, "no HEAD and no comparison". Rule conflict (§4).
- **Gzip every body**: `retain_body_file(..., 'body.gz')` (`:398-401`). Target writes new bodies at the bare `<sha>` key, gzip only for compressible types with `Content-Encoding` (A §7.1). The writer itself is the parent's `retention/body_files.py`.

`acquisition/streamed_recovery.py` (454): resumable, hash-journaled HTTP Range download pinned by `If-Unmodified-Since` (`download_ranges`, `:31-118`), plus `recover_pdf` (`:172-222`) and `recover_zip` (`:225+`), which retain a publisher-qualified large file and write a normal receipt. This is the only code that has stored bodies far above the 64 MiB cap (the 1.19 GB body, A §5). **Repurpose** for P B14 and for A §7.1's "any size up to the single-PUT limit": it already streams to disk and verifies SHA-256 while writing. Changes: drop the publisher-manifest requirement (B14 URLs have no publisher digest), record `outcome` from D §5.2 instead of `"saved"` (`:210`, `:284`, `:422`), and write the new receipt fields.
- **Defect:** the CLI route is broken. `cli/raw_sync.py:469` calls `download_ranges(archive, args.selected_urls or (), fetch=fetcher.fetch)`, but the signature is `download_ranges(client, url, path, *, size, last_modified, ...)` (`streamed_recovery.py:31-40`): it raises `TypeError` on the unexpected `fetch` keyword. Added by e4b3216b (2026-10-23, "wire Wave-2C CLIs"); no test covers the route (only `test_streamed_recovery.py`, which calls the function directly).

`acquisition/retained_import.py` (47): splits a URL batch into initial and retry passes over `archive.state` (`:9-24`). Tied to the raw-index state; **Replace** with `url_state`-driven selection, though the partition rule (new/pending vs retryable, refuse anything else) is worth keeping as a test.

`acquisition/recovery_queue.py` (139): plans a failed-URL recovery campaign from raw-archive tables (`completed_from_tables`, `:11-68`; `plan_recovery`, `:80+`). Reads `snapshot.states_for` and pyarrow tables of the raw index. **Replace** (goes with the raw index; rebuild against `url_state` if campaigns are still wanted). Not in P's delete table.

Tests (by import, all shared with retention unless marked): `test_async_capture.py` (excl.), `test_async_capture_native.py`, `test_capture_capacity.py`, `test_capture_checkpoint.py`, `test_capture_delayed_retry.py` (excl.), `test_capture_failure_regressions.py`, `test_capture_processes_native.py`, `test_spooled_capture.py`, `test_file_backed_capture.py`, `test_streamed_recovery.py` (excl.), `test_retained_import.py` (excl.), `test_recovery_queue.py` (excl.), `test_targeted_recovery.py`, `test_wave2c_bwac.py`, `test_raw_source_sync.py`.

##### 2.2 acquisition B16 fetchers (265 lines)

`acquisition/committees.py` (104) and `acquisition/meetings.py` (161) call the Congress.gov API directly (`transport/congress.py:8-9`) and write gzip JSONL snapshots through `retention.committees.write` / `retention.meetings.write` (`committees.py:16-18,103`; `meetings.py:34,156`). Nothing reaches raw. P B16 is right that both must fetch through the raw writer.

Reusable as-is in the new fetcher (Repurpose, A §8.5–8.6):
- `detail_url` (`committees.py:23-29`): strict host/path validation and credential-free endpoint.
- Pagination guards: repeated page and non-advancing pagination refusals (`committees.py:62-75`; `meetings.py:89-98`); duplicate-code refusal (`committees.py:64-66`).
- Incremental listing by `updateDate` with a 2-day overlap (`meetings.py:56-61,77-78`) and the FIRST_CONGRESS = 112 floor (`:40`).
- The JSON→XML fallback on HTTP 500 with an identity check of `(congress, chamber, eventId)` against the requested endpoint (`meetings.py:114-129`).

Must change:
- Stop writing JSONL snapshots and the `.pending.json` retry file (`meetings.py:67-70,103,153-157`); a failed detail fetch becomes a receipt line, and `url_state` retries it.
- The recorded URL must exclude `api_key`: `transport/congress.py:9` puts the key in the query string and `requests` puts it in `response.url`. Today the code strips it by hand (`meetings.py:89` `split("?")[0]`; `committees.py:29`). The raw writer needs this as a rule, because `allowed_url` refuses any URL with an `api_key` parameter (`archive_links.py:19,56-57`) and refuses `api.congress.gov` outright (`:50`). Capability gap (§5).
- The `joint` → `nochamber` translation (`meetings.py:43,126-127`) means chamber spellings differ between endpoint and record; D does not fix canonical chamber values for `meeting_ref`/`meeting_keys` (§4).

##### 2.3 acquisition inventory fetchers (1,805 lines)

`house.py` (280), `house_fallback.py` (100), `house_sites.py` (539), `senate.py` (417), `gpo.py` (337), `gaps.py` (116), `refresh.py` (16). These run in `update-data.yml` (`:94,155-182`) and write state JSON with embedded bodies (`RawContent`, `models/content.py:38-60`) plus CSVs for the committee explorer. Their bodies never pass through the raw writer: `raw-source-sync` only harvests URLs from these files as seeds (`cli/raw_sync.py:48-58` → `json_links`; then `retention/raw_archive.py:295-350`).

Class: **Keep** (they are the committee explorer's collectors, a product P §7 parks). But A §8.6 says `meeting_records` derive from "the House and Senate meeting inventories, all fetched through the raw writer", so `house.py` (meeting and witness XML, `house.py:45-80` `request`) and `senate.py` (`:153` `request`) must route their fetches through the raw writer too. **P B16 names only `committees.py` and `meetings.py`; it misses these.** `gpo.py` (MODS, transcript HTML) and `house_sites.py` (committee event pages) are the same pattern; whether they must move depends on whether their bodies feed the target (MODS is `source_record`, its links count; see §4 on MODS event IDs).

`senate.py` docstring (`:1-32`) states pages are associated to Congress.gov events by rarity-weighted title matching (`matching/senate_pages.associate_pages`). That association is not a body fact (see §4).

`refresh.py` `due` (`:9-16`): weekly / 28-day / annual recheck by meeting age. A candidate for the recheck-interval registry (D §7.1), though that registry is keyed by family, not age.

Calls into retention: `retention.house.seed/timestamp`, `retention.tables.read_state/write_state/write_csv`, `retention.senate.seed_fetch` (`senate.py:57`, the P B6 layout writer), `retention.committees.read`, `retention.body_files.content_bytes`.

##### 2.4 Dormant: `acquisition/documents.py` (69) + `transport/document_probe.py` (43)

No importer outside tests (AST graph; `document_probe` is imported only by `documents.py`). `test_document_link_probe.py` (147 lines) exercises it. History: added in 43f112ef (2026-10-01, "Capture missing raw sources...") as "the bounded document-link probe used to inspect these outputs", last changed 87791e9c (2026-10-19). `resolve_document` follows an HTML landing page to a file with ranged GETs (`document_probe.py:13-43`, `Range: bytes=0-<limit>`, stops at a PDF/ZIP magic), reports `step_limit`/`loop`/candidates.

Proposed target uses:
1. A labeling aid for the hand-labeled sample of P §5.3 (S): it shows, cheaply and without full downloads, whether an HTML response is a landing page for exactly one file, which is the question the file-shape and listing rules must answer.
2. A pre-check for P B14: one bounded probe per cut-off URL to confirm the publisher still serves a file and its `Content-Length` before the full re-fetch.
Its fixtures in `test_document_link_probe.py` are also ready-made samples for the file-shape registry (D §7.1 requires a real sample per entry).

##### 2.5 parsers link + sniff core (607 lines)

These are the body parsers the parent's `retention/index/*` and `retention/capture_inspection.py` call to re-derive links and labels.

`document_links.py` (204):
- `tree_document_links` (`:121-161`): one lxml pass over `a[@href] | link[@href] | object[@data] | embed[@src] | iframe[@src] | meta[@http-equiv]`, honoring `<base href>` (`:123-124`), meta refresh (`:149-151`), label normalization (`:132`), and a `basis` per link (`download_link`, `alternate_document`, `meta_refresh`, `embedded_document`, `publisher_document_context`). **Repurpose** as the `html` reading's link pass (D §6.2). Changes: keep **every** link, in document order, with `href` as written (today it keeps only document-like links, resolves them, and de-duplicates by resolved URL, `:133,157-160`); record `base_href` (already read at `:123`); add `group_path`; drop the host-gated publisher routes (`:127`).
- `links_from_trees` (`:108-118`) with `page_content.page_trees` (`page_content.py:8-42`): adds links embedded in Next.js `__NEXT_DATA__` event data and JSON-LD events, depth-bounded at 12 and 4 MiB per fragment. Keep as part of the HTML parser; `source_selector` (`:116`) is the natural place to note that a link came from embedded data.
- `http_url` + `remove_dot_segments` (`:51-94`): RFC 3986 resolution via `urljoin` plus host validation (control characters, credentials in the authority, IDNA, port syntax). **Engine-first duplicate** for the model: link resolution must be the engine's SQL function (A §13 item 8, P C8). Keep `http_url` in the fetcher as an input guard only.
- `FILE` (`:9`), `DOCUMENT_ROUTE` (`:11`), `is_document_url` (`:15-30`): **Repurpose** as the seed of the file-shape registry (D §7.1, §7.3). Today's list: `.pdf .xml .doc(x) .xls(x) .ppt(x) .zip .rtf .txt .csv`, routes `/download/`, `/media-center/files/`, `/wp-content/uploads/`, `/_cache/files/`, `/imo/media/doc/`, `/services/files/`, `/sites/*/files/`, `files.serve`, `a=files.serve`. D's broad list is a superset in spirit; today's routes apply only on `.house.gov`/`.senate.gov`/CSCE hosts (`:127`), D's apply everywhere.
- `response_kind` (`:180-204`) + `binary_pdf_header` (`:164-177`): **Repurpose** for the `sniff` parser (D §6.2). Detects `pdf` (incl. a binary preamble), `zip`, `legacy_office`, `rtf`, Apple `file_wrapper`, `html`, `xml`. Must change: drop the media-type fallbacks (`:195-197` HTML by `Content-Type`; `:202-203` `unverified_pdf`), which A §8.3 forbids; map to D's values (`legacy_office`→`doc`; split `docx` from `zip`); add `json`, `vtt`, `m3u8` (signatures exist in `captions.py:16,43`), `text`, `image`, `warc`, `empty`.
- `download_query_fallback` (`:33-48`): a code-defined URL repair for one host (`democrats-transportation.house.gov` `&download=1` → `?download=1`). No home in D; see §4.

`archive_links.py` (269):
- `allowed_url` (`:26-63`): SSRF and scope guard: media files, private and `.internal` hosts, API hosts, credential query keys, embedded-URL paths except known archive replays. **Repurpose**: keep the safety half in the fetcher (non-global IPs, secrets, credentials); move the scope half (media, API hosts) to the capture-scope registry (D §7.1, §7.7).
- `ARCHIVE_REPLAY_PATHS` (`:20-23`): `web.archive.org/web/<14 digits>[id_]/` and `webarchive.loc.gov/all/<14 digits>[id_]/`. Seed for the URL-wrapper registry's archive entries (D §7.2). Differences in §4.
- `capture_links` (`:66-99`): repairs the `lis.gov/cgi-lis/t2GPO/<url>` wrapper and splits concatenated file URLs. Not in D's wrapper registry (§4).
- `related_links` XML branch (`:225-246`): records `tag`, `text`, `attributes`, and `source_xpath` from `getpath` (an indexed path such as `/committee-meeting/meeting-documents/meeting-document[3]/files/file[1]`). **Repurpose** for the `xml` reading: `group_path` is that path truncated at the nearest grouping ancestor. Changes: stop resolving and scope-filtering (`capture_links(..., url)` at `:242-245`).
- `json_links` (`:102-196`): harvests document URLs from Congress.gov JSON and inventory state. D gives JSON readings no links (§4).
- Playlist branch (`:249-268`): subtitle links only. Captions are never real files (D §7.3), so this only matters for capture scope.

`file_wrapper.py` (69): strict reader for Apple's serialized RTFD FileWrapper (`regular_file`, `:18-69`), zero-copy. **Keep** with the sniff/format code: D's format list has no value for it; it currently surfaces as `file_wrapper` (`document_links.py:191-192`). D needs either an `other` mapping or its own value.

##### 2.6 parsers meeting (464 lines)

- `house_evidence.document_group` (`:50-70`) and `parse_retained_evidence` (`:73-116`) already compute `group_path`-shaped selectors for House meeting XML (`/committee-meeting/meeting-documents/meeting-document[i]`, `:80`) and witness XML (`/witness-list/panel[i]/witness[j]/witness-documents/witness-document[k]`, `:99`), each file's `doc-url`, `doc-type`, and the group's attributes (where `add-date` and `publish-date` live; consumed at `matching/house.py:66,75-76`). `html_document_groups` (`:21-36`) does the same for the docs.house.gov HTML fallback with `//li[i]` selectors. **Repurpose** for the `xml` reading's links (D §6.2 `group_path`, `doc_type`, `add_date`, `publish_date`) and thereby `same_rendition` (a) (D §7.5).
- `house_documents.read_xml` (`:116-138`) is the House rendition rule today: one `meeting-document` with several `file` elements is one document in several formats, PDF first (`:127`). Same rule as D §7.5 (a) plus the format-preference registry.
- `parsers/congress.py` `meeting_from_xml` (`:44-78`), `parse_congress_xml` (`:17-22`): strict Congress.gov XML meeting reader. **Repurpose** as the XML-fallback producer for `meeting_records` (D §6.5).
- House meeting XML carries what `meeting_records` needs (sample `packages/committee_meeting/tests/house-formats.xml`): `meeting-id="HHRG106245"` (event ID after the prefix), `congress-num`, `meeting-type`, `meeting-details/meeting-date/calendar-date`, `meeting-title`, `committees/committee-name@id` (`RU00`). Model fields at `models/house.py:33-36,88,194,239-243`.
- `parsers/xml.py` `parse_xml` (`:12-13`) strips the UTF-8 BOM docs.house.gov prefixes; keep for the XML parser. `xml_root` (D §6.2) is the parsed root tag.

##### 2.7 parsers Senate (1,411 lines)

`senate_page.py` (1,145) holds Senate site rules: site list `SITE` (`:22`), listing URL patterns (`:30`), date regex `DATE` (`:57`) and `written_day`/`century_year` (`:876-893`), heading/table/paragraph link context (`link_headings` `:474-538`, `table_columns` `:439-463`), witness layouts, `attachment_page` (`:905-908`, Drug Caucus `/media-center/files/` landing pages), `event_details` (`:917+`). Importers include `retention/index/{records,sources,document_sources,schemas}.py` and the explorer adapters.

- For the archive, this is the per-site link-label re-derivation the target replaces with the generic HTML reading plus `group_path` (D §6.2). **Replace** for that use.
- For the explorer, **Keep**.
- Partial repurpose: `DATE` + `written_day` for `content_date` ("null unless exactly one date qualifies", D §6.2).
- `attachment_page` is the Senate landing-page case (P E4: "about 4,900 lose Senate landing pages"). D's generic rule covers it if `/media-center/files/` is in the file-shape registry (today's `DOCUMENT_ROUTE` has it; D's broad list has `/files/`).

##### 2.8 parsers House committee sites (466) and GPO (669)

`committee_pages.py` (228) and `committee_discovery.py` (238) crawl committee websites for `house_sites.py`: calendar GraphQL JSON (`committee_pages.py:20-31`), sitemap and anchor discovery (`:40-49`), event titles (`:52-70`), news/press exclusion (`committee_discovery.py:16-18,25-44`). **Keep** for the explorer. The exclusion regexes (`EVENT`, `RESOURCE`, `NEWS`) are useful seed entries for the capture-scope registry (D §7.1). Calendar GraphQL POSTs cannot be expressed as links, so they stay fetcher code.

`gpo_hearings.parse_mods` (`:94+`) extracts `event_ids` (`:166`) and committee authority IDs (`:106,116`) from MODS. **Keep** (out of scope), but see §4: this is a `meeting_ref` and committee source D omits.

##### 2.9 `parsers/source_family.py` (179)

`family` (`:7-179`) routes by host, path and pointer to the source families (`congress/meetings`, `house/meeting-xml`, `senate/pages`, `documents`, …). Importers: `retention/raw_archive.py`, `retention/source_inputs.py`, `retention/index/{metadata,sources}.py`. **Repurpose**: the writer sets the receipt `family` (D §5.2) at fetch time from this function, and the recheck-interval registry (D §7.1) keys on its output. Drop the local-path heuristics (`:96-176`), which exist only to classify old local files.

##### 2.10 transport fetch (798 lines)

- `rust_fetch.py` (305): drives the Rust `source-fetch` worker, which writes every direct body to a temp file (`RustResponse`, `:68-100`); `fetch_spooled` hands the file to the collector without reading it into memory (`:234-257`). This is A §7.1's spooling, already built. `retry_later` (`:22-65`) honors `Retry-After` (≥30 s for GovInfo ZIP generation, `:57-64`). Zyte fallback with `prior_attempts` (`:272-282`) matches D §5.2 `prior_attempts`. **Repurpose.** Changes: the default cap `max_bytes=64 * 1024**2` (`:134`) must rise to the single-PUT limit.
- `source_capture.py` (180): manual redirect loop with a scope check per hop and a `redirects` list (`:123-164`, D §5.2 `redirects`); completeness rules (206 or `Content-Range` → incomplete, `:115-117,152-154`). **Repurpose.** Changes: default `max_bytes` 64 MiB (`:42`); `read_bounded` truncates the body at the cap (`:31-39`); Zyte bodies are base64 in a JSON response and decoded in memory (`:66-122`), capped at `max_bytes*4/3 + 1 MiB` (`:71`), so Zyte cannot honor "nothing is cut off" without a streaming JSON decode (§5); records full header copies (`response_header_items`, `provider_metadata`, `source_metadata`, `:68-70,104-111,139,151`), which D §5.2 forbids.
- `http.py` (192): `get_with_retry` with host pacing (1.2 s for docs.house.gov, 60 s after a 403), Zyte option, credential-free errors (`:137-192`). **Keep** for the inventory fetchers. `response_metadata` (`:92-122`) "retain[s] all received headers": no allowlist, so `Set-Cookie` would land in receipts (§4).
- `zyte.py` (59), `congress.py` (9), `senate.py` (53): **Keep**.

##### 2.11 models

- `models/congress.py` (210): typed Congress.gov envelopes (`CommitteesPage`, `CommitteeResponse`, `MeetingsPage`, `MeetingResponse`, `CommitteeRecord` with `parent`, `CommitteeMeeting`), and `parse_response`. **Repurpose** as the JSON parser for `committee_records` (D §6.4: `systemCode`, `name`, `chamber`, `parent.systemCode`; `congress` from the response's `request.congress`, `RequestInfo` `:20-26`) and `meeting_records` (D §6.5: `eventId`, `congress`, `chamber`, `title`, `date`, `type`, `committees[].systemCode`). The committee **detail** endpoint has no congress (`acquisition/committees.py:77-79`), so a detail response yields a completion row.
- `models/documents.py` `DocumentLink` (`:17-24`: `url`, `basis`, `text`, `tag`, `attributes`, `original_url`, `source_selector`) is D §6.2's link struct under other names: `url`→`href` (as written), `source_selector`/XPath→`group_path`, and `doc_type`/`add_date`/`publish_date` lifted from `attributes`.
- `models/content.py` `RawContent` (`:38-60`) embeds bodies base64 in JSON state. It goes away for anything routed through the raw writer.

##### 2.12 matching target-relevant (232 lines)

- `matching/house.py:24,32`: the docs.house.gov meeting directory regex `docs.house.gov/meetings/[A-Z]{2}/[A-Z]{2}\w{2}/\d{8}/<eventId>/`, exactly D §7.5's first `meeting_ref` form. Today the event ID is an input, not a capture group; the SQL version captures it.
- `matching/house.py:33-34`: "hs for standing committees, hl for Intelligence and the select committees (hlig00 is IG00)". Conflicts with D §7.5's `'hs' || lower(code)` (§4).
- `matching/house.py:36`: meeting-type → XML prefix (`Hearing`→`HHRG`, `Markup`→`HMKP`, else `HMTG`), and `FILED` (`:9`) for House filenames. Useful as `meeting_records` test vectors.
- `matching/committees.py`: `hierarchy_from_code` (`:53-57`, `[hsj][a-z0-9]{3}\d{2}`, `00` = full committee) and `native_parent` (`:11-13`) give `parent_system_code` when the response omits `parent`. `ALIAS` (`:8`) is a YouTube-channel alias table; it must not leak into `committee_key`.
- `matching/meetings.py` `meeting_type` (`:13-38`): normalizes publisher type, falling back to title phrases. D §6.5 keeps `meeting_type` as published; this is a ready rule if the site wants normalized types.

##### 2.13 cli (1,719 lines)

- `cli/raw_sync.py` (524): capture entry (`capture_sources`, `:231-284`; `connect_storage`, `:295-341`) survives, rewired: no `RawStorage`/`NativeDatasets` (`:381-394`), no raw-index archive. **Replace** the catalog and adoption modes: `add_catalog_modes`, `operation_mode`, `adoption_inputs`, `adopt_catalog` (`:61-153`, 93 lines), the `operator-status`/`retention-plan` branches (`:422-441`, 20 lines), `adopt-raw` and catalog update (`:472-513`, 42 lines): about 155 lines (est.). `--max-file-mib` default 64 (`:186`). The broken `streamed-recovery` call is at `:469` (§2.1).
- `cli/document_index.py` (71): a local filename-index command that forwards to `raw_sync` catalog modes (`:29-58`) or `retention.document_index.build` (`:61-64`). No entry point; run as a module. **Replace** with the catalog.
- `cli/sync_weekly_tables.py` (336): writes weekly retention files into docspec `WeeklyRetentionTables` (`:192-198`; run at `update-data.yml:196`). **Keep** (parked, P §7). A docspec-rs consumer (§7).
- `cli/raw_progress.py` (124): progress sidecar. Keep.

##### 2.14 replay (346 lines)

`replay/gpo.py`, `replay/house.py`, `replay/senate.py`: one-off enrichment of inventory state from local research caches, run with `python -m` (docstrings `gpo.py:1-9`, `house.py:1-11`, `senate.py:1-12`); no workflow runs them. Target: a new parser version is backfilled over raw bodies (A §8.3 "Versions"). **Replace**. Not in P's delete table.

##### 2.15 Out-of-scope products (Keep)

- **Committee explorer**: `adapters/*` (2,494), most of `matching/*` (1,765), `transcripts/*` (775), `transport/{audio,gemini}.py` (271), `models/{gpo,senate,legislators,media,transcription}.py` (1,294), `packages/committee_meeting` (1,441), `packages/youtube_api` (1,498), `apps/committee_youtube` (5,878). P §7 parks the explorer. Two facts matter for the target:
  - `apps/committee_youtube/src/committee_explorer/docspec_views.py` uses docspec-rs `RefreshSpec` (`first_value_by`, `collect_distinct_with_provenance`, `collect_set`, `aggregate`, `:134-196`) and `ExportSpec`/`ExportPin` (`:543,556,621`), run by `export.py:957-960` when `DOCSPEC_BINARY` is set (`publish-explorer.yml:103-105`). P F's engine cuts must check this consumer.
  - P B6's layout writer, `committee_explorer/parquet.py:406-428`, writes `bodies/sha256/<aa>/<sha>.pdf` (raw) or `.gz` (gzip, `mtime=0`) into the explorer's local publication stage, not the raw bucket, and hashes a re-serialized JSON payload when the payload is a dict (`:412`). B6's "call `put_body`" fits only once it is clear these keys are explorer-local.
  - Human decisions live in code: `matching/reviewed_committees.py` (`REVIEWED`), `matching/committee_adjustments.py` (`ADJUSTMENTS`), `matching/senate_corrections.py` (`DATE_CORRECTIONS`), `parsers/reviewed_witness_lists.py`. A §7.3 puts reviewed decisions in provenance. They serve only the explorer today; if any are wanted in the archive (e.g. Senate/joint committee codes, D §7.5), they move to provenance.
- **`apps/inflation_gsheets`** (663): BLS/FRED CPI aggregation run by `bls-cpi-update.yml`. Unrelated to the archive.
- **`packages/congress_shared`** (919): **Keep**. `storage.R2Config`/`connect_r2` (`storage.py:16-162`) builds the client every writer uses; `custody` (atomic writes, verified files) has 31 source importers, many in the catalog that goes. Note `canonical_json_bytes` (`custody.py:262-281`) uses `sort_keys=True` and `allow_nan=True`: it is **not** D §3's compact JSON (`allow_nan=False`), so it must not generate the ID golden vectors.

#### 3. Repurpose opportunities, ranked by target work saved

Savings are estimates of new code and edge cases avoided.

1. **Fetcher and spooling** (`acquisition/raw_sync.py:45-107,517-570`, `transport/rust_fetch.py:68-257`, `transport/source_capture.py:42-180`, Rust `source-fetch`) → the raw writer's fetcher (A §7.1–7.2, P B2). Already spools to disk, budgets memory, follows redirects with a per-hop scope check, falls back to Zyte with `prior_attempts`, honors `Retry-After`. Change: lift the 64 MiB cap and rework the reservation math (buffer must hold 3× max file, `raw_sync.py:90-94`, impossible at 5 GB); remove replay, capture-time readings and the raw-index queue; 412 → `unchanged` without a re-read; header allowlist; new receipt fields; bare-key layout. *Est. 1,000–1,500 lines saved.*
2. **HTML/XML link extraction** (`document_links.tree_document_links` `:121-161`, `page_content.page_trees` `:8-42`, `archive_links.related_links` XML branch `:225-246`, `house_evidence.document_group` `:50-70`, `DocumentLink` `models/documents.py:17-24`) → `html` and `xml` readings with `links`, `base_href`, `group_path`, `doc_type`, `add_date`, `publish_date` (D §6.2). Change: all links, as written, document order, no dedupe, no resolution; generic `group_path` (li, tr, meeting-document, document; add `witness-document`, §4). *Est. 300–500 lines plus the Next.js, meta-refresh, BOM and entity-safe XML cases.*
3. **Congress.gov fetch loops and models** (`acquisition/meetings.py:49-161`, `acquisition/committees.py:23-104`, `models/congress.py`, `parsers/congress.py:44-78`) → B16 fetchers and the JSON/XML producers of `committee_records`/`meeting_records` (D §6.4–6.5). Change: raw writer, no JSONL state, credential stripping, completion rows. *Est. 400–600 lines.*
4. **House meeting XML readers** (`house_evidence.py:50-116`, `house_documents.py:95-138`, `house_xml.py`, `models/house.py`) → `meeting_records` from House XML (event ID from `meeting-id`), `same_rendition` (a), and `meeting_ref` (c) (D §6.5, §7.5). *Est. 200–300 lines.*
5. **Range download** (`acquisition/streamed_recovery.py:31-118`) → P B14 cut-off re-fetch and any body above the in-memory budget (A §7.1). Change: no publisher manifest required; D §5.2 outcome; fix the CLI call at `cli/raw_sync.py:469`. *Est. 100–150 lines plus resumability tests (`test_streamed_recovery.py`, 359 lines).*
6. **Sniffing** (`document_links.response_kind` `:180-204`, `binary_pdf_header` `:164-177`, `captions.py:16,43`, `file_wrapper.py`) → `sniff` parser (D §6.2). Change: no media-type fallback; D's value set. *Est. 100–150 lines and the irregular-PDF and RTFD cases.*
7. **Registry seeds**: file shapes from `FILE`/`DOCUMENT_ROUTE` (`document_links.py:9,11`); capture scope from `allowed_url`/`MEDIA_FILE` (`archive_links.py:18,26-63`) and `committee_discovery.py:16-44`; URL-wrapper archive entries from `ARCHIVE_REPLAY_PATHS` (`archive_links.py:20-23`); recheck keys from `source_family.family`. Samples from `test_capture_url_admission.py` (279), `test_document_link_resolution.py` (148), `test_circular_document_links.py` (62), `test_committee_download_wrappers.py` (177). *Est. the first contents and sample tests of 4 of D §7.1's 13 registries.*
8. **Receipt family** (`parsers/source_family.py:7-95`) → D §5.2 `family`, recheck-interval registry key. *179 lines.*
9. **meeting_ref and committee_key rules** (`matching/house.py:24,32-36`; `matching/committees.py:11-13,53-57`) → D §7.5 SQL and its sample tests; carries the `hl` exception the spec lacks. *Small in lines, high in correctness.*
10. **Dormant probe** (`acquisition/documents.py`, `transport/document_probe.py`) → labeling aid for S and B14 pre-check (§2.4). *112 lines.*

#### 4. Rule conflicts (code vs spec)

Either side may be right; each needs an owner decision or a spec edit.

1. **64 MiB cut-off.** `raw_sync.py:215`, `rust_fetch.py:134`, `source_capture.py:42`, `cli/raw_sync.py:186`, `capture-raw-sources.yml:343` (`--max-file-mib 64`) vs A §7.1 "Nothing is cut off". The resource-bounded mode (`--max-file-mib 0`) reaches about 682 MiB with the workflow's buffers (`response_capacity`, `raw_sync.py:36-42`; 2,048 MiB buffer, 5,120 MiB spool), still short of the 1.19 GB largest body.
2. **Create conflict re-reads the body.** `raw_sync.py:412-415` vs A §7.1 step 3 (412 → `unchanged`, no HEAD, no comparison).
3. **All response headers recorded.** `transport/http.py:92-122`, `source_capture.py:68-70,104-111,139,151`, and the Rust worker's `response_header_items`; `retention/raw_archive.prepare_capture` writes the whole response dict into the receipt. No allowlist and no cookie filter exists anywhere in the repo (grep for `set-cookie`/allowlist finds none). A §7.2 and §14: allowlisted headers only, no cookies or authorization. D §5.2 lists `response_header_items` and provider metadata as MUST NOT.
4. **Links resolved at parse time against one URL.** `document_links.py:124,133`; `archive_links.py:27,73,242-245`. D §6.2/§7.2: `href` as written; the model resolves against `base_href` or every context the page was fetched at.
5. **Only document-like links, de-duplicated.** `document_links.py:135-160`. D §6.2: every link, document order.
6. **Sniff uses the server's media type.** `document_links.py:195-197,202-203`. A §8.3 forbids it.
7. **Archive wrappers.** Code: `web.archive.org` and `webarchive.loc.gov`, `id_` modifier only, and replays are admitted as capture URLs (`archive_links.py:20-23,33-44`). D §7.2: `web.archive.org` and `webharvest.gov` with any modifier, unwrapped for joins. `webarchive.loc.gov` is missing from D; `webharvest.gov` is missing from the code's list (only `scripts/webharvest/webharvest_committee_map.py:26` has a regex for it, outside this scope).
8. **URL repairs in code, not in D's registries.** `lis.gov/cgi-lis/t2GPO/<url>` wrapper and concatenated URLs (`archive_links.py:66-99`); `democrats-transportation.house.gov` `&download=1` (`document_links.py:33-48`); docs.house.gov `http`→`https` request rewrite (`source_capture.py:21-28`); `http://`→`https://` rewrites on House XML URLs (`house_documents.py:125,149`, `matching/house.py:53`). D's wrapper registry lists Proofpoint, rs6.net, exit.asp and two archives; other variants belong in provenance `url_variants`. The `lis.gov` wrapper fits D's registry; the others need a decision.
9. **Success status.** Code treats only 200 as success for capture (`retention/capture_inspection.py`, called from here) and inventory fetches accept `(200, 404)` (`house.py:45`). D §7.3 `good_fetch` is 200–299; `streamed_recovery` records complete 206 responses (`:210,217`).
10. **Outcome vocabulary.** Code: `saved`, `html`, `http_error`, `challenge`, `parse_failed`, `excluded_scope`, `pending`, `timeout`, … (`raw_sync.py:31-33`, `streamed_recovery.py:210`). D §5.2: six outcomes. The `captures` ingest mapping must translate older lines (parent's D1).
11. **House committee codes.** D §7.5 `'hs' || lower(code)`; `matching/house.py:33-34` says Intelligence and select committees are `hl` (`hlig00` is `IG00`). The spec's rule would map `IG00` to `hsig00`, which names no committee.
12. **Removed House XML documents.** Code drops elements with a non-empty `remove-date` (`house_documents.py:72,98-106,125`; `house_evidence.py:56,65`). D §6.2's link struct has `add_date` and `publish_date` but no `remove_date`, so removed renditions would still group, give meeting refs and link context.
13. **Witness documents are not a grouping ancestor.** D §6.2 lists `li`, `tr`, `meeting-document`, `document`; House witness XML groups renditions under `witness-document` (`house_evidence.py:98-100`, `house_documents.py:104`). Without it, witness renditions fall back to rule (b) of D §7.5.
14. **XML link text.** The `file` element carries `doc-url` but no text (`archive_links.py:244` takes `itertext()` of that node); the label is the ancestor's `<description>`. D's `text` for XML links will be empty unless the parser takes the group's description.
15. **JSON gives no links.** `archive_links.json_links` (`:102-196`) is how Congress.gov `meetingDocuments`/`witnessDocuments` URLs reach capture today (via seeds, `cli/raw_sync.py:48-58`). D §6.2 records links only for HTML and XML, and D §7.7's queue reads only those, so a document listed only in Congress.gov JSON would never be queued. Needs measurement before the switch.
16. **Senate inventory has no event ID.** A §8.6 sources `meeting_records` from the Senate inventory, but Senate pages carry no Congress.gov event ID; today it comes from fuzzy title/date association (`acquisition/senate.py:1-20`, `matching/senate_pages.py`), not from the body. D §6.2 says a reading depends only on its body.
17. **GPO MODS event IDs.** `gpo_hearings.parse_mods` reads `event_ids` and committee authority IDs (`:106,116,166`). D §7.5's `meeting_ref` sources omit them, so GovInfo hearing documents get no meeting ref from their MODS.
18. **Chamber spelling.** Congress.gov endpoints use `nochamber` for joint (`meetings.py:43,126-127`). D does not fix the `chamber` values used in `meeting_ref` and `meeting_keys`.
19. **Retry timing.** `rust_fetch.retry_later` (`:22-65`) waits per `Retry-After`; `Retry-After` is not in D §5.2's header allowlist and D §7.7 makes retryable outcomes due at the next run. Fine for daily runs; note that GovInfo ZIP generation asks for 30 s.
20. **Senate heading-derived kinds and witness ownership** (`senate_page.py:151-305,474-538`) have no place in D: kinds come from `house-naming` only. This is a cause for P E4's parity report ("link-label coverage changes").
21. **File-shape scope.** Today's route patterns apply only on House, Senate and CSCE hosts (`document_links.py:127`); D's registry applies on any host. Label-based detection (`PROMPT`, `:10,140`) has no D counterpart.

#### 5. Capabilities missing (must be built)

- **URL unwrap and strip-list** (D §7.2): no Proofpoint `urldefense ?u=` (with `-XX`/`_` decoding), no `rs6.net/tn.jsp ?p=`, no `exit.asp ?link=`, no tracker or page-state stripping, no `webharvest.gov` unwrap, no `www.`/default-port/trailing-slash normalization (grep over packages, apps and scripts finds none).
- **Generic HTML reading facts** (D §6.2): `title`, `heading`, `text_bytes`, `link_count`, `link_text_bytes`, `content_date`. Only site-specific extractors exist (`committee_pages.event_title` `:52-70`, `senate_page.event_details` `:917+`).
- **Generic `group_path`**: exists only for House XML and the docs.house.gov `//li[i]` fallback.
- **Sniff values** `json`, `docx` vs `zip`, `text`, `image`, `warc`, `empty`; and the sniff code version recorded at fetch.
- **Header allowlist and cookie redaction** in the fetcher.
- **Credential stripping** for recorded URLs (Congress.gov and GovInfo API keys in query strings) so B16 can fetch through the raw writer.
- **Streaming Zyte bodies**: base64 inside JSON is decoded in memory (`source_capture.py:66-122`); "nothing is cut off" through Zyte needs a streaming decode or a size ceiling the spec acknowledges.
- **`meeting_ref` from Congress.gov URLs** (`congress.gov/<congress>/meeting/<chamber>/<eventId>/`): no parser exists; only sample URLs (`parsers/reviewed_witness_lists.py:11-62`).
- **Raw-writer routing for House and Senate inventory fetches** (A §8.6; beyond P B16).

#### 6. Engine-first duplicates

- `document_links.http_url` + `remove_dot_segments` (`:51-94`): RFC 3986 resolution; the model must use the engine's URL functions (A §13 item 8, P C8). Keep the Python copy only as a fetch-time input guard, and use it to generate conformance vectors.
- `acquisition/recovery_queue.completed_from_tables` (`:11-68`): pyarrow scans over raw-archive tables in Python; goes with the raw index.
- `committee_explorer/export.py` / `parquet.py` write the explorer's Parquet with pyarrow and, optionally, docspec `ExportPin` (`export.py:957-960`): out of the archive's scope, but it is two export paths for one publication.
- No Python in this scope does joins or grouping for the archive model; that duplication lives in the parent's `retention/`.

#### 7. Delete-table items in this scope that P misses

- **`cli/raw_sync.py` catalog and adoption modes**, about 155 lines (est.; `:61-153`, `:422-441`, `:472-513`), plus `RawStorage`/`NativeDatasets` setup (`:381-394`). P's table names the catalog modules but not their CLI routes.
- **`cli/document_index.py`** (71 + 2 test files): goes with the catalog.
- **`replay/*`** (346; tests shared, 980 lines across 5 files): superseded by readings backfills.
- **`acquisition/recovery_queue.py`** (139; `test_recovery_queue.py` 58, part of `test_wave2c_bwac.py` 707): reads the raw index.
- **`acquisition/retained_import.py`** (47; `test_retained_import.py` 119): partitions over `archive.state`.
- **Capture-time readings** in `raw_sync.py` (`:288-293,422-439`): readings move to the lake.
- **The broken `streamed-recovery` CLI route** (`cli/raw_sync.py:462-471`): fix if B14 uses it, else delete.
- **Consumers the engine cuts must check**: `committee_explorer/docspec_views.py` (RefreshSpec, ExportSpec/ExportPin) and `cli/sync_weekly_tables.py` (`WeeklyRetentionTables`). P F3 lists `spicysearch`, `spicyengine` and `DocSpec`, not these.
- **P B16 scope**: add `acquisition/house.py` and `acquisition/senate.py` (and decide on `gpo.py`, `house_sites.py`), per A §8.6.

### 4.3 Site, viewer publication, publication and measurement scripts, workflows

Scope: `apps/site`, `packages/viewer_publication`, `scripts/publication/`, `scripts/publication_preflight.py`, `scripts/viewer_release_identity.py`, `scripts/measure/`, `scripts/tests/`, `.github/workflows/*` (with the `.github/scripts` and `.github/tests` they call), and the custom-domain edge tooling (`congress_api/retention/r2_edge_rules.py`, `viewer_publication/apply_r2_edge_rules.py`, `scripts/publication/apply-r2-edge-rules.py`, `infra/cloudflare/congressional-data-r2-edge.json`).

Worktree `/Users/mikewolfd/Work/wt/ct-ticket-audit` at d9730967. Read-only. Every count below comes from `wc -l`. `fork-site/inv_site_counts.sh` reproduces each one and names the exact files. "A", "D" and "P" mean the architecture spec, the data-model spec and the plan.

#### 1. Summary table

| Group | Class | Target component (spec §) | src lines | test lines |
|---|---|---|---|---|
| Site reader core: `cache.ts`, `startup.ts`, `cooperative.ts`, `client.ts`, `session.ts`, `bootstrap.ts`, `worker.ts`, `publication.ts` | **Repurpose** (plan §8 keeps cache/withVerifiedJson/startup) | Reader shell, worker, caches, verified reads (A §11.1, §11.3, §11.4) | 581 | 405 |
| Site v6 + ExportPin reader branch: `catalog-v6.ts`, `catalog.ts`, `observations.ts`, `recoveries.ts`, `reviews.ts`, `detail-record.ts`, `types.ts` | **Replace** | New release-format reader (A §11.1, D §8.1; P A1) | 1,293 | 940 |
| Site filename views and presentation: `FilenameEvidence.tsx`, `FilenameListing.tsx`, `filename-presentation.ts`, `filename-match.ts`, `filename-search.ts`, `filename-rules.ts`, `navigation.ts`, `provenance.ts`, `kinds.ts` | **Repurpose** (about half) | Document page, list, labels (A §11.5–11.6, D §8.1 detail fold; P A5–A10) | 1,782 | 346 |
| Site committee explorer: `Explorer.tsx`, `data-source.ts`, `parquet-source.ts`, `record-presentation.ts`, `query-utils.ts`, views, etc. | **Keep** (parked, P §7); patterns repurposed | Not in target; meetings partly superseded by `meetings.parquet` (D §8.1) | 7,970 | 1,373 |
| `apps/site/scripts/verify-live-publication.mjs` | **Repurpose** (the plan says Replace) | Node canary HTTP layer, plus the Chromium harness for the contract test (A §10.3.5, §15.5) | 400 | 143 |
| Site static pages, styles, content, YouTube dashboard | **Keep** | Static site (A §11) | about 960 (TS/JS remainder) | 82 (`built-filenames.test.mjs`) |
| viewer_publication: journal/resume/attempt route (`attempt`, `continuation`, `local`, `reconciliation`, `resume`, `plan`, `verify`, `publish_viewer_r2`, `publication_cli`, `cli`, `client.py:1-263`) | **Replace** | Publish job (A §10.3) | 2,682 | 2,180 |
| Preflight and release identity (`publication_preflight.py`, `release_identity.py`, `viewer_release_identity.py`, `prepare_workflow_resume.py`, two CLI shims) | **Replace** (tiny repurpose) | Early skip by input identity (A §10.3.2, D §8.3); code identity (P B7) | 609 | 657 (incl. resume/cli script tests) |
| `client.py:264-391` (`publish_manifest_pointer`, `ConditionalManifestPublisher`) | **Repurpose** | Create-only upload and If-Match flip (A §10.3.4, §10.3.6) | 128 | in `test_filename_exports.py` |
| viewer_publication v6 preparer (17 modules + 2 shims) | **Replace** | Model SQL + engine export (A §9–10, D §7–8) | 3,294 | 2,682 |
| `filename_viewer.py` (local Python viewer and HTTP server) | **Replace** | None; dies with the Python catalog | 871 | in v6 tests |
| `filename_exports.py` (ExportPin route) | **Repurpose for F0, then delete** | F0 converter (P §5.4) | 1,254 | 383 |
| Edge tooling (`r2_edge_rules.py`, `apply_r2_edge_rules.py`, shim, infra JSON) | **Repurpose** (delete only the WAF part) | Origin: CORS, cache headers, CSP, `?filename=` (A §11.7) | 722 | 211 |
| `compact_readings.py`, `compact_reviews.py` | **Dormant** | None; Basin compacts (A §8.7) | 366 | 332 |
| `filename_reviews.py` + `stage-document-reviews.py` + `document-review-*.json` | **Replace** at switch; the data needs a migration decision | Provenance `reviews` (D §5.3, §7.9) | 188 (+907 JSON) | 183 |
| `publish_docspec_runtime.py` + shim; `.github/scripts/setup-native-runtime.py`, `check-native-runtime.py` | **Keep** | Pinned engine (A §12) | 217 + 257 | 141 + 250 |
| `backfill_uncompressed_pdfs.py` + shim | **Repurpose** (B13), then delete | One-time PDF copy job (P B13, D §5.3 verification) | 96 | in congress_api `test_pdf_backfill.py` (parent) |
| `scripts/publication/pipeline_status.py` | **Replace** (heartbeat reader repurposable) | `status.json` (A §12) | 352 | 298 |
| Measurement scripts for deleted subjects (13 files) | **Replace** | None | 2,725 | 531 |
| Measurement scripts that stay useful (`viewer_benchmark_server.py`, `benchmark_viewer_browser.mjs`, `process_rss.py`) | **Repurpose** | Speed and heap targets (A §11.2; P A11), local contract runs | 427 | 192 |
| `.github/scripts/verify-capture-run.py` | **Replace** (checks repurposable) | R-check and weekly check (P §3, A §7.4) | 323 | 497 |
| Workflows | mixed, see §7 | Capture, publish, maintenance (A §12) | 1,383 yml + 390 md | 2,505 (`.github/tests`) |

#### 2. Detail per group

##### 2.1 Site reader core: Repurpose (581 src, 405 tests)

All of these sit in `apps/site/src/components/explorer/reader/filenames/`.

- **`cache.ts`** (74). `retainedBytes` (1-12) estimates the retained heap of decoded values. `byteCache` (22-53) is a byte-bounded LRU with entry admission and stats. `awaitShared`/`sharedLoad` (55-74) share in-flight loads without sharing cancellation. Target use: the per-session offset-index cache for `detail` row groups (A §11.1; P A1: "each row group's offset index fetched once per session and cached"), the Range cache, and a heap estimate for the canary. No change needed.
- **`startup.ts`**. `withVerifiedJson` (9-76) streams a response under a deadline and a byte cap, checks the decoded length, SHA-256-verifies the bytes, then parses JSON. `canonicalJson` (79-83) compares JSON independently of key order. Target use: verified whole-file reads of `list.parquet` and `meetings.parquet`, which are read whole and carry `sha256` in the manifest (D §8.1 `files[]`). Change: return the bytes instead of `JSON.parse` (line 62). Keep the JSON variant for the manifest.
- **`cooperative.ts`** (22). `yieldToMessages` yields once per 512-row batch so worker cancel messages run. Target use: the search and facet loops over decoded `list` arrays in the worker (A §11.1). Keep.
- **`client.ts`** (111). `createFilenameClient` (21-88) handles request IDs, cancellation, rebuilding a failed worker, and a snapshot-identity check (48-53). `publicationLifecycle` (96-111) handles bfcache. Target use: the main-thread side of the A §11.1 worker. Change the identity check to the release ID, and replace "the file list changed, reload" with A §11.3's re-read-pointer-and-reload on 404.
- **`worker.ts`** (53). A message router (`/api/info`, `/api/rows`, `/api/entry/…`, 30-45) over one cached catalog promise (23). Keep the shell. The routes change to list search/facets, detail by row, link by key, ranges and meetings.
- **`session.ts`** (104). One worker per page, the global `window.filenameViewerApi`, and a result cache (63-74). Keep.
- **`publication.ts`** (131). `loadPublication` (27-49) reads pointer → manifest, with version checks and pinned `catalogs/<id>.json` locators (31-35). `watchPublication` (57-89) polls the pointer on focus and every 60 s. `latestReviewUrl` (91-105) handles snapshot-pinned links. Repurpose about 40%: the pointer → manifest read and the no-store/force-cache split (22). The pinned catalog locators conflict with A §10.3.7 retention (see §4). Polling is not in the spec. Keep it only as a "new data" notice.

##### 2.2 Site v6 + ExportPin reader branch: Replace (1,293 src, 940 tests)

- `catalog-v6.ts` (680) has two modes, chosen by manifest shape at line 148. The ExportPin mode (214-391) lacks `technical`, `review` and `matchUrls`, so `worker.ts:34-37` would throw on those routes. The native v6 mode (392-680) walks JSON route trees (392-414, 482-535). Both read rows as objects (`parquetReadObjects`, 188). Filtered search either loads every component row (308) or streams every source partition (547-559). That is O(N) objects per search and conflicts with A §11.1's column-by-column arrays.
- `observations.ts` (332) decodes Brotli JSON observation blocks. `recoveries.ts` (37) and `reviews.ts` (80) load sidecar JSON overlays. `detail-record.ts` (14) and `types.ts` (141) carry v6 shapes. None of these fit D §8.1. P §6.1 names this branch as replaced.
- Small pieces worth lifting before deletion:
  - `rangeFile` (75-102): exact `Content-Range` validation, a shared pending map and a bounded cache. This is the AsyncBuffer for hyparquet offset-index reads.
  - `compareText` (112-118): compares code points the way Arrow and Python do, where JS compares UTF-16 units. It is needed wherever the reader compares strings against Arrow-sorted `list` order.
  - `savedCopyUrl`'s filename sanitizer (44-45): mirrors `r2_edge_rules.sanitize_download_filename`.

##### 2.3 Site filename views and presentation: Repurpose about half (1,782 src, 346 tests)

- `FilenameEvidence.tsx` (410) is the detail panel: "Open saved copy" (79), status notes (143), possible dates (216-224), review labels (239) and the origin graph (267-290). `FilenameListing.tsx` (100) is the result list.
- `filename-presentation.ts` (750) holds labels for fields, formats, congress, committee and HTTP status (21-534). Most of it labels house-naming fields, which survive as `f.*` in the `detail` fold (D §8.1), so most labels carry over.
- Date notes (`checkedAtNote` 455, `retrievedAtNote` 461-466) must change to A §11.6's three labels.
- The recovery note (531-533) labels a recovery by format. Replace it with the D §7.8 display kind.
- `provenance.ts` (189): `validUrl` (52-60) is reusable. `provenanceUrlKey` (62-65) is a weaker URL key than D §7.2 (host+path+query+fragment; it drops only the scheme). `evidenceGraph` (81-155) builds multi-hop page→file paths, which goes beyond the target's single `linked_from` per occurrence (D §7.10). Delete it, or keep it as display over the occurrence rows.
- `navigation.ts` (174) and `filename-search.ts` (31) hold URL state and search parsing. Keep them, keyed by link key instead of `source_id`.

##### 2.4 Site committee explorer: Keep (parked) (7,970 src, 1,373 tests)

- This is a separate publication, `/data/explorer/CURRENT.json` on Pages (`dashboard.astro:16`), with its own Parquet reader (`parquet-source.ts`). The target does not cover it, and P §7 parks "Committee explorer and weekly retention".
- Patterns to lift:
  - `data-source.ts:8-12` accepts a set of supported `schema_version`s. That is the A §11.4 "current and previous" rule, already written.
  - `data-source.ts:26-29` and `RecordDetail.tsx:146-147` already use `DecompressionStream('gzip')`, which A §11.5 needs for saved copies.
  - `parquet-source.ts:96-118` is a second copy of the Range-read helper. Consolidate it with `rangeFile`.
- Coupling: `Explorer.tsx` hosts the filename views (`CapturedCatalogNote`/`FilenameInspector`, 2354-2427). It joins committee files to captured files through `matchUrls` (`catalog-v6.ts:581-606`), which scans every source partition per lookup and stops at 24. That is O(N) per open. In the target the committee file's `saved_copy_sha256` gives the link key directly (first 8 bytes, D §8.2), so the join becomes one `links.parquet` point lookup (A §10.1).

##### 2.5 `verify-live-publication.mjs`: Repurpose (400 src, 143 tests)

- P §6.1 lists it under "replaces at the switch", but P §8 keeps "`--verify-publication`'s Chromium checks". Those checks are this file:
  - `browserRuntimeProbe` (280-352) launches Chromium, waits for `window.filenameViewerApi` and calls `/api/info`.
  - `browserProbe` (354-376) loads Playwright from `PUBLICATION_BROWSER_MODULES`.
  - The call chain is `scripts/publication/pipeline_status.py --verify-publication` (294, 320-346) → `viewer_publication/verify.py:live_observation` (357-384) → this script.
- Lift these three pieces:
  - `bounded()` (33-112): a request budget, a byte budget, a timeout, and decoded-versus-encoded length handling. This becomes the Node canary's HTTP layer (A §10.3.5).
  - The Chromium probe: becomes the CI contract test harness (A §15.5).
  - The CLI shell (378-400).
- Delete the v6-specific pointer, review and recovery checks (113-278).
- Playwright is not a site dependency (`package.json`). The contract test must pin it.

##### 2.6 viewer_publication: journal, resume and attempt route: Replace (2,682 src, 2,180 tests)

- `attempt.py` (346), `continuation.py` (492), `local.py` (161), `reconciliation.py` (84), `resume.py` (50), `plan.py` (67), `verify.py` (384), `publish_viewer_r2.py` (612), `publication_cli.py` (219), `cli.py` (4), and `client.py:1-263` (`GuardedPublicationClient` 43-241 with full read-back `verify()` 162-178, journal events and the receipt registry; `ContinuedPublicationClient` 244-263).
- In the target, immutable content-addressed release prefixes plus one If-Match flip make resume unnecessary (A §10.3.4-10.3.6, §12 "no journals").
- Keep two things before deleting:
  - `client.py:124-135`, the derived-prefix firewall and the explicit-condition requirement. It is the raw firewall that corpus-recovery publication also uses. Move it into P B3's single namespace policy first.
  - `publish_viewer_r2.public_probe` (374-411). It checks HTTPS CORS, 206 with the expected `Content-Range`, `PAR1` and exposed headers, which are canary assertions (A §10.3.5). Port them into the Node canary.

##### 2.7 viewer_publication: v6 preparer: Replace (3,294 src, 2,682 tests)

- Modules: `filename_native.py` (1,067), `native.py` (108), `filename_native_recoveries.py` (265), `filename_renderer_state.py` (188), `filename_navigation.py` (58, marked "historical v5" in its docstring), `filename_observations.py` (280), `filename_json_stream.py` (110), `filename_budget.py` (213), `filename_details.py` (126), `filename_compression.py` (12), `filename_resources.py` (17), `filename_alias_index.py` (170), `filename_aliases.py` (29), `filename_recoveries.py` (88), `filename_review_binding.py` (181), `publish_filename_viewer.py` (231), `filename_test_fixture.py` (117), and two CLI shims (34).
- All of it builds v6 delivery assets from the Python catalog: it imports `catalog_batches`, `catalog_rows`, `partition_routing` and others (`filename_native.py`). The model SQL plus the engine export replace it (A §9-10).
- `filename_viewer.py` (871) is the local Python viewer. It has an HTTP server (`handler_for`, 768ff) and reads saved bodies locally or through the Cloudflare API (`RetainedFiles`, 159-275). It goes with the Python catalog.

##### 2.8 `filename_exports.py`: Repurpose for F0 (1,254 src, 383 tests)

This is the unwired ExportPin route (git a7375f36, 0cdd8d44, 2026-10-21, ct-2yl5). It is the closest existing code to P §5.4's converter:

- `fold_source_readings_table` (549-620): folds filename readings into `list<struct<field, values>>`. D §4's fold uses one `value` per element, so it needs unnesting.
- `compute_facet_entries` (504-546): the manifest's `facet_counts`.
- `publish_occurrence_parquet` and `occurrence_flat_schema` (285-470): flatten nested `source_occurrences` into a flat occurrences file with a page index. That covers F0's "link labels from the old occurrences".
- `compute_browse_ranges` (470-501): row-group min/max.

It also shows two engine-first problems:

- `compute_facet_entries` re-implements, row by row in Python, a facet summary that `docspec_client.facet_summary` already provides (imported at line 13).
- `compute_browse_ranges` re-reads every row group to compute min/max that Parquet statistics already hold.

Delete it with F0 at the switch (P §6.6).

##### 2.9 Edge tooling: Repurpose (722 src, 211 tests)

- `r2_edge_rules.py`:
  - `evaluate_waf_request` (64-104) and the path regexes (19-28) model the WAF prefix allowlist.
  - `evaluate_response_headers` (107-159) models CORS, nosniff, Referrer-Policy, CSP (omitted for PDF), Cache-Control and the `?filename=` disposition.
- `apply_r2_edge_rules.py` (464) plans and applies three Cloudflare API PUTs: R2 CORS, the zone WAF ruleset and response-header transforms (96-288). `verify_live_edge` (348-413) asserts 403 on `/receipts/*`, `/indexes/*` and other blocked paths (359-372).
- A §11.7 drops the path allowlist and keeps CORS, cache headers, CSP and `?filename=`. So delete only the WAF parts:
  - `r2_edge_rules.py:19-28, 64-104`;
  - `apply_r2_edge_rules.py:41-43, 48-71, 106-135, 276-280, 359-372`;
  - the JSON's `waf_custom_rules` (28-48);
  - `test_r2_edge_rules.py:99-107` and the WAF assertions in `test_r2_public_edge_and_pdf_storage.py:253-356`.
  - *est.* about 150 src and 60 test lines.
- Update the paths: drop `/exports/*` and `catalogs/`, and add no-store for `viewer-publications/status.json`.
- Platform-primitive check: CORS and transform rules could be managed with `wrangler r2 bucket cors` and Terraform's Cloudflare provider instead of 464 lines of hand-rolled API calls. Measure the switch before deciding.

##### 2.10 Dormant: `compact_readings.py` (252), `compact_reviews.py` (114); 332 test lines

- Both arrived in f2fea711 (2026-10-22, "Direct-to-R2 payload offloading, full columnar normalization…").
- `compact_readings` dedupes and compacts the old `readings/*.parquet` shards. `test_catalog_compaction.py` and two e2e tests import it; no workflow or CLI calls it.
- `compact_reviews` drops redundant review columns. Only `__init__.py` references it; no test covers it.
- Purpose in the target: none as a runtime path, because Basin compacts the lake tables (A §8.7) and the engine must not hold table maintenance (A §13).
- Proposed use: `deduplicate_reading_table`'s keep-latest-by-PK logic (19-60) can serve as a fixture helper for D §10.1's PK-uniqueness and rebuild-equivalence tests. Delete the rest.

##### 2.11 Reviews publication: Replace, with a data decision

- `reviews.ts` (counted in the reader), `filename_reviews.py` (165), `filename_review_binding.py` (in the v6 count), `apps/site/scripts/stage-document-reviews.py` (23), `document-review-identities.json` (895 lines, 86 reviewed groups, every row with a `body_key`), and `document-review-publication.json` (a 156 MB evidence archive on a GitHub release).
- The verdicts are `candidate_applied` (category change) and `annotation_only_unsupported_forms`.
- The target has provenance `reviews` targeting link keys, with verdicts `hide`, `duplicate_of`, `title_override` and `kind_override` (D §5.3, §7.9). Each row's body key gives a link key directly (sha256[0:8]), so `candidate_applied` maps to `kind_override`.
- P §2 says "review tools" survive, but no plan step migrates these 86 reviews into provenance. See §6.

##### 2.12 Keep: engine pinning and status

- `publish_docspec_runtime.py` (201) builds and uploads the byte-pinned runtime that `.github/scripts/setup-native-runtime.py` (187) and `check-native-runtime.py` (70) install and check. That matches A §12 "pinned by revision and digest, checked before storage access".
- `.github/docspec-remote.json` holds the Basin catalog URI and warehouse; it names secrets only as environment-variable names. Keep it for the lake (A §8). Its `owned_prefix`/`docspec.namespace-generation` keys belong to the old lifecycle store (P §6.3 "not needed any more").
- `.github/scripts/finalize-raw-source.py` (45) does an If-Match update of `status/raw-source-sync.json`. That pattern fits A §12's `status.json`. Keep it while capture keeps a heartbeat.

##### 2.13 `pipeline_status.py`: Replace (352 src, 298 tests)

- It reads the GitHub run, the capture heartbeat and the viewer `continuation.json`/`events.jsonl` (`continuation()`, 113-209), and optionally runs the Chromium verification (320-346).
- The continuation half dies with the journal. The `heartbeat()` monotonicity checks (58-112) can stay if capture keeps its heartbeat.
- A §12 asks publish to write `viewer-publications/status.json`, which nothing writes today.

##### 2.14 Measurement scripts

- **Replace** (2,725 src, 531 tests). Each measures a subject that the switch deletes:
  - `benchmark_catalog_grouping.py` (77) and `benchmark_core_rebuild.py` (507): the Python catalog. CI references the latter in `capture-raw-sources.yml:36`.
  - `benchmark_viewer_publication.py` (291): the v5 builder.
  - `compare_publication_costs.py` (236), `measure_publication_control.py` (188), `publication_costs.py` (134): the journal publisher.
  - `compare_raw_keyed_updates.py` (195), `compare_raw_keyed_updates_scale.py` (376): the raw index.
  - `measure_alias_preparation.py` (109), `measure_catalog_partition_reuse.py` (137), `measure_preparation_decoded.py` (191), `measure_preparation_resources.py` (90): the v6 preparer.
  - `probe_corpus_recovery_memory.py` (194): the old importer.
- **Repurpose** (427 src, 192 tests):
  - `viewer_benchmark_server.py` (248) serves local files with bounded Range and CORS.
  - `benchmark_viewer_browser.mjs` (161) times loader startup in real Chromium (96-130).
  - `process_rss.py` (18) samples resident memory.
  - Together they are most of P A11 ("measure startup, search, detail and heap … with F0") and a local contract-test server. They need a heap metric, which neither script records today, and the new reader entry points.

#### 3. Repurpose opportunities, ranked by target work saved

Savings are *est.* lines of new code avoided.

1. **Site reader shell** (`worker.ts`, `client.ts`, `session.ts`, `cooperative.ts`, `cache.ts`; about 360 lines). Covers worker routing, cancellation, rebuilding a failed worker, bounded LRU caches, shared in-flight loads and cooperative yields. Track A1 needs all of it. *Saves about 300 lines.* Change the routes and the identity check.
2. **Local Range/CORS server and Chromium timing harness** (`viewer_benchmark_server.py`, `benchmark_viewer_browser.mjs`; 409 lines plus 192 test lines). They become P A11's speed measurement and a local run of the A §15.5 contract test. *Saves about 300 lines.* Add a heap metric and point them at the new reader.
3. **F0 converter pieces** from `filename_exports.py` (fold, facets, occurrence flattening; about 330 lines in 285-620). P §5.4 needs folded `detail`, `occurrences` with link labels, and facet counts from the pinned catalog. *Saves about 300 lines* of a throwaway tool. Prefer the engine RunSpec where it can (P §5.4).
4. **Canary and contract-test harness** from `verify-live-publication.mjs` (`bounded()` 33-112, `browserRuntimeProbe` 280-352, CLI 378-400) and `public_probe` (`publish_viewer_r2.py:374-411`). They supply the bounded Node HTTP layer, Chromium-in-CI and the CORS/206/`PAR1` assertions. *Saves about 200 lines.*
5. **Create-only upload and If-Match flip** (`client.py:266-391`). `publish_manifest_pointer` already flips with If-Match (create with If-None-Match) and does no read-back. `ConditionalManifestPublisher.put_immutable_asset` streams create-only PUTs. *Saves about 100 lines* of A §10.3.4/10.3.6. To change: add Content-MD5; on 412, HEAD and compare the ETag to the expected MD5 instead of returning `'existing-immutable'` (348, 380); write `previous_release_id`. Or move upload into the engine's create-only remote boundary (see §5, engine-first).
6. **Edge config minus the WAF** (about 570 of 722 lines). It keeps the A §11.7 CORS, cache, CSP and `?filename=` rules applied as code. *Saves about 400 lines* of re-creation. Alternatively replace it with wrangler or Terraform.
7. **Verified whole-file read** (`startup.ts:9-76`). Read `list.parquet` and `meetings.parquet` whole with SHA-256, length and deadline checks against the manifest. *Saves about 70 lines*; split it into a bytes variant.
8. **Committee-explorer → document link via `saved_copy_sha256`**. This replaces the O(N) `matchUrls` scan (`catalog-v6.ts:581-606`) with one `links.parquet` lookup on sha256[0:8]. It saves no new code, but it removes a superlinear path and keeps the parked explorer working after the switch.
9. **Presentation labels** (`filename-presentation.ts`, 750 lines; about half fits the `detail` fold's `f.*` and `r.*` display). *Saves about 300 lines* of A6/A9 page work.
10. **Small patterns**:
    - `data-source.ts:8-12`: the supported-schema-version set (A §11.4).
    - `DecompressionStream` (`data-source.ts:26-29`; `RecordDetail.tsx:146-147`) for A §11.5.
    - `compareText` (`catalog-v6.ts:112-118`).
    - `release_identity.locked_runtime`/`source_files` (`release_identity.py:24-107`) for P B7's code identity (uv.lock digest) and the model profile's SQL-file hashing (D §7.1).
    - `backfill_uncompressed_pdfs.py` (80) as the B13 CLI entry.
    - `publish_docspec_runtime.py` (Keep).

#### 4. Rule conflicts (code versus spec)

Either side may be right. Each is flagged for the owner.

1. **Release ID.** Code: a random `releases/<uuid4>/` prefix (`publish_viewer_r2.py:475`). Spec: SHA-256 of the file list and the schema version (A §10.3.3). Spec gap: A §10.3.3 does not fix the serialization (field order, compact JSON?) that the release ID hashes. The spec should fix it so a reader can verify the manifest against the pointer by recomputing the ID.
2. **Timestamps in content.** Code: the manifest gets `published_at` (`publish_viewer_r2.py:476, 482`). Spec: the manifest holds only content (A §10.2, §10.3.4; D §8.1).
3. **Read-back after write.** Code: a full GET after every PUT (`client.py:162-178`; `publish_viewer_r2.py:525-534`), and SHA-256 in object metadata. Spec: Content-MD5, no re-read, one HEAD only on 412 (A §10.3.4, §13.5).
4. **412 treated as success without a check** (`client.py:344-348, 376-380`). Spec: a 412 must be checked against the expected MD5 with one HEAD (A §10.3.4).
5. **Pinned old releases.** Code: `catalogs/<catalog_id>.json` locators are written forever (`publish_viewer_r2.py:543-548`) and read for snapshot-pinned review links (`publication.ts:31-35`, `client.ts:50-52`). Spec: only the live and last-good releases are sure to exist; retention deletes the rest, and a stale tab reloads (A §10.3.7, §11.3). Pinned links will break unless they move to link keys.
6. **Pointer shape and reader identity.** Code: the pointer holds `catalog_id`, `source_manifest`, `recovery`, `published_at` and `full_release_inputs` (`publish_viewer_r2.py:485-500`), and the reader polls every 60 s (`publication.ts:80`). Spec: `{release_id, previous_release_id}` (D §8.1), with re-read on 404 (A §11.3).
7. **Public links.** Code: 64-hex `source_id`, optionally pinned by `?catalog=` (`publication.ts:91-105`, `navigation.ts`). Spec: a 16-hex link key that resolves through `links.parquet` (A §10.1, D §8.2).
8. **Saved-copy suffix** (`catalog-v6.ts:24-48`). Code: `.pdf` is chosen by guessing from format, filename and URL, so a PDF without a made copy (B13 is pending for 261,055) links to a missing object. Spec: the suffix comes from `stored_suffix` or a verification record (D §7.5 `suffix()`).
9. **Non-PDF `.gz` saved copies.** Code: they are linked as attachments under the original filename (`catalog-v6.ts:44-47`; `r2_edge_rules.py:144-146`). Older `.gz` objects carry `Content-Type: application/gzip` with no `Content-Encoding` (D §5.1), so the user very likely receives gzip bytes named, say, `report.docx`. This is unverified and needs one live request. Spec: unpack with `DecompressionStream`; offer files over 100 MB as a labeled compressed download (A §11.5).
10. **Spec security issue (A §11.5).** "Opened with the media type from detail": if an unpacked HTML/SVG/XML body is opened as a `blob:` URL, it runs in the Pages origin. Today's design deliberately avoids running archived HTML: there is a sandbox CSP on non-PDF objects (`r2_edge_rules.py:139-141`) and FILENAME-VIEWER.md says archived HTML is not run. The spec should require download, text view, or a sandboxed iframe without `allow-same-origin`/`allow-scripts` for active types.
11. **Date labels.** Code: "Retrieved <date>" and checked-at notes (`filename-presentation.ts:455-466`). Spec: "Captured <date>", "In our archive since <date> (original capture date not recorded)" and "Capture date not recorded" (A §11.6).
12. **Decoding.** Code: rows are decoded as objects (`catalog-v6.ts:188`; `parquet-source.ts:131-160`). Spec: column by column into arrays and dictionary codes (A §11.1). Neither reader uses `useOffsetIndex` or `usePageIndex`. Whether hyparquet 1.31.2 (`apps/site/package.json`) exposes them is unverified: `node_modules` is absent in this worktree.
13. **Edge allowlist.** Code: the WAF blocks `/receipts/*`, `/indexes/*` and other paths, and `verify_live_edge` fails unless they return 403 (`apply_r2_edge_rules.py:359-372`; infra JSON 28-48). Spec: no path allowlist, `r2.dev` serves every key, and everything stored is public (A §11.7, §14).
14. **Cut-off.** Code: the capture workflow passes `--max-file-mib 64` (`capture-raw-sources.yml:346`), and the local viewer caps reads at 64 MiB (`filename_viewer.py:174-210`). Spec: nothing is cut off (A §7.1; P B2, B14).
15. **One credential.** Code: the same `R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` secrets serve capture, catalog update and viewer publish (`capture-raw-sources.yml` capture and `update_catalog_after_capture` jobs; `publish-filename-viewer.yml`). Spec: separate tokens per job (A §12, §14).
16. **Recovery display.** Code: shown as "Recovered copy as <format>" (`filename-presentation.ts:531-533`). Spec: the display kind from the recovery-kind registry; an unmapped category fails the build (D §7.8).
17. **Review semantics.** Code: `candidate_applied` replaces `document_kind`/`document_family` per group (`catalog-v6.ts:197-198`; `reviews.ts:41-44`), keyed by `document_id` plus member `source_ids` plus `body_key`. Spec: verdicts on link keys, applied after grouping (D §7.9).
18. **Facet computation.** Code: Python per-row loops (`filename_exports.py:504-546`). Spec: facet counts over the non-hidden `list` rows, computed in the model/export (D §8.1, A §4.5).
19. **JSON hashing.** `verify-live-publication.mjs:15-21` re-escapes non-ASCII to match Python's ASCII JSON. D §3's compact JSON keeps non-ASCII as-is. This matters only if someone reuses that helper for golden vectors.

#### 5. Capabilities missing (must be built from scratch)

- **Reader:**
  - `list` decoded column by column in the worker, with search and facet counts over the arrays;
  - `detail` reads by row through `useOffsetIndex` (one offset-index fetch per row group per session);
  - `links` point lookups through `usePageIndex`;
  - `occurrences`/`recoveries` range reads, paged for long ranges;
  - `meetings` read at most once per session;
  - shard handling;
  - a hearing filter on `meeting_keys`.
  Nothing in the site reads a column index or an offset index today.
- **Link-key routing:** 16 hex, a not-found notice, and the hidden "removed by review" page (A §11.5, D §7.9). The site has no `hidden` concept.
- **Node canary** with a heap budget (A §10.3.5). No heap measurement exists anywhere in scope: `retainedBytes` is an estimate, and the browser benchmark times only.
- **Contract test** in CI with a pinned headless browser (A §15.5). Playwright is not a dependency.
- **Publish job:**
  - pin snapshots;
  - completeness gate;
  - input identity and early skip (A §10.3.1-10.3.2, D §8.3);
  - content-addressed release ID;
  - `inputs/<input_digest>.json`;
  - `status.json`;
  - flip with `previous_release_id`.
  Only the flip helper exists (§3 item 5).
- **Weekly maintenance workflow** (A §7.4, §10.3.7; P B9): LIST plus join, release retention that keeps live and last-good releases more than a day old, and the orphan report. No release-deletion code exists in scope. That is correct for publish, which must never delete, but retention must still be written.
- **Shared concurrency group** for publish and maintenance (A §10.3.7).
- **Saved-copy behavior** (A §11.5): open at the physical key from `saved_suffix`; unpack with `DecompressionStream` up to 100 MB; labeled compressed download above that; alternates.
- **Recovery kind labels** and the attachment rule display (D §7.8).

**Engine-first findings (Python duplicating engine work):**

- `filename_exports.py`, `filename_native.py` and `compact_readings.py` write and compact Parquet with pyarrow. In the target, the engine owns export (A §13.3) and Basin owns compaction (A §8.7, §13).
- `compute_facet_entries` duplicates `docspec_client.facet_summary` (`filename_exports.py:13, 504`).
- `ConditionalManifestPublisher` uploads release files from Python. A §13.5 and P §8 put create-only remote writes in the engine. Decide which side uploads before writing the publish job.

#### 6. Delete-table corrections (P §6.6 rows in scope)

| Plan row | Plan estimate | Measured (src + tests) | Correction |
|---|---|---|---|
| Viewer publication: the journal, resume and attempt route | 2,786 + 2,005 | **2,682 + 2,180** core: `attempt`, `continuation`, `local`, `reconciliation`, `resume`, `plan`, `verify`, `publish_viewer_r2`, `publication_cli`, `cli`, `client.py:1-263`; ten test files. Dying with it but unnamed: **609 + 657** (`release_identity.py`, `viewer_release_identity.py`, `publication_preflight.py`, `prepare_workflow_resume.py`, `publish-viewer-r2.py`, `publication_cli.py` shim; `test_workflow_resume.py`, `test_publication_cli.py`, `test_publication_preflight.py`), **+567 tests** in `.github/tests` (`test_viewer_r2.py`, `test_filename_publication.py`), **+97** (`pipeline_status.py` `continuation()`), **+233** workflow | Close for the core. Name the extras. Before deleting `client.py`, move the prefix firewall (`client.py:124-135`, shared with corpus recovery) into P B3. Keep `verify.py:357-384` until the Chromium probe moves to the contract test. |
| Viewer publication: the v6 preparer and the v6 reader branch | 1,695 + 1,112 | Preparer **3,294 + 2,682** (17 modules, 2 shims; 17 test files); local viewer `filename_viewer.py` **871**; reader branch **1,293 + 940** | Underestimated about 2.5×. 1,695 roughly equals only `filename_native`, `native`, `filename_native_recoveries`, `filename_renderer_state` and `filename_navigation` (1,686; my inference). It misses 1,608 lines of `filename_*` helpers used only by v6 and ExportPin, plus `filename_viewer.py`. Realistic total: **5,458 src + 3,622 tests**. |
| Measurement scripts for deleted subjects | 1,862 + 723 | **2,725 + 531** for the 13 deleted-subject scripts; **427 + 192** should stay (`viewer_benchmark_server.py`, `benchmark_viewer_browser.mjs`, `process_rss.py`) | The source figure is low by about 860. The test figure 723 is *all* measure tests, including 192 for scripts P A11 should reuse. Delete 2,725 + 531, keep 427 + 192. |
| The custom-domain path allowlist and its tooling | at cut | Whole tooling **722 + 211**; WAF part only *est.* **150 + 60** | Do **not** delete `r2_edge_rules.py`/`apply_r2_edge_rules.py` whole: they also carry the CORS, cache, CSP and `?filename=` rules that A §11.7 keeps. Cut the WAF parts listed in §2.9. |
| *Missing:* ExportPin route | — | `filename_exports.py` 1,254 + `client.py:264-391` 128; test 383 | Use it for F0 (or the flip helper), then delete it with F0. |
| *Missing:* dormant compaction | — | 366 + 332 | Delete (§2.10). |
| *Missing:* review publication path | — | `filename_reviews.py` 165, `stage-document-reviews.py` 23, `document-review-*.json` 907; test 183 (`reviews.ts` and `filename_review_binding.py` are counted above) | Replaced by provenance `reviews`. **Decision first:** migrate the 86 assistant reviews (body keys give link keys; `candidate_applied` maps to `kind_override`) or drop them. |
| *Missing:* raw-index capture verifier | — | `.github/scripts/verify-capture-run.py` 323; tests 497 (`test_capture_verification.py` 336, `test_native_capture_verification.py` 161) | It reads `indexes/captures.parquet` (82-84). Fold it into the raw-index row; its receipt→body checks feed the R-check and B9. |
| *Missing:* site v6 reader tests and verifier | — | `verify-live-publication.mjs` 400 + 143 | Repurpose, not delete (§2.5). |
| *Missing:* docs | — | `apps/site/FILENAME-VIEWER.md` 202 (describes a retired Worker and v5 binaries); `.github/workflows/raw-source-tables.md` 390 | Rewrite at the switch. |

#### 7. Workflows → target job

| Workflow | Today | Target job | Notes |
|---|---|---|---|
| `capture-raw-sources.yml` (504) | Push validation; daily 03:23 `--update-only` (Python catalog update); manual `--capture-only`; `update_catalog_after_capture` job (`raw-source-sync --update-only`, 462) | **capture** (its capture-only path); the update path and the dependent job are replaced by **publish** | Drop `--max-file-mib 64` (346). Read the queue from the live release's `url_state` (P F2). Use a capture-only credential. Push validation moves to CI. |
| `publish-filename-viewer.yml` (233) | Disabled with `gh workflow disable` (`docs/plans/branch-integration-20261016.md:46`); cron `11,41 * * * *`, workflow_run, push; resume axis | **none**: delete (P F1) | The new publish job replaces it, triggered after capture or on demand, in one concurrency group with maintenance. |
| `deploy-pages.yml` (118) | Builds the site, stages the committee-explorer snapshot, `test:explorer`, `test:built-filenames`, size budget | **Keep** (site deploy) | Add the A §15.5 contract test here or in validation. |
| `validate-explorer.yml` (80) | PR validation: `dev.py` lanes, npm build | **Keep** (CI) | Add the reader and contract tests and the determinism checks (A §15). |
| `publish-explorer.yml` (157) | Committee-explorer data to the `pipeline-data` branch | **none** (parked, P §7) | Unclear: decide whether `meetings.parquet` supersedes it. |
| `update-data.yml` (243) | Weekly YouTube, Congress.gov meetings/GPO, meeting inventory and committees to `pipeline-data` | **capture**, for the committee and meeting fetches (P B16, A §8.5-8.6); the rest is parked | Committee and meeting fetches must go through the raw writer; today they write their own files. |
| `bls-cpi-update.yml` (48) | inflation_gsheets | **none** (unrelated app) | Keep. |
| *(new)* weekly maintenance | — | **maintenance** (A §7.4, §10.3.7; P B9) | Build it, in publish's concurrency group, with its own token. |

#### Unclear (what would settle each)

- **Committee explorer** (site 7,970 + 1,373; `publish-explorer.yml`; `update-data.yml`): the owner decides whether it survives beside the document explorer or is absorbed by `meetings.parquet`. P §7 says re-scope first.
- **The 86 assistant reviews:** do they count as reviewer decisions that should become provenance `reviews` records? This is an owner decision; P has no step for it.
- **hyparquet:** does 1.31.2 support `useOffsetIndex`/`usePageIndex`? Check the installed package before A1.
- **Who uploads release files:** the Python `ConditionalManifestPublisher` or the engine's create-only remote boundary (A §13.5, P §8)?
- **Pointer polling:** keep `watchPublication`'s 60 s pointer poll as a UX notice, or drop it? The spec requires only re-read on 404.

### 4.4 house-naming, docspec_client, corpus_recovery, news_lake, source-fetch, scripts, root tests

Worktree `/Users/mikewolfd/Work/wt/ct-ticket-audit` at d9730967. Specs: A = `docs/engine-first-architecture.md`, D = `docs/engine-first-data-model.md`, P = `docs/plans/simplification-plan-20261024.md`. Line counts are `wc -l`, measured; "est." marks estimates. Probes of house-naming output were run with `/Users/mikewolfd/Work/wt/ct-viewer-publish/.venv/bin/python -I` against the worktree's `packages/house-naming/src` (no tests, no network).

#### 1. Summary table

| Group | Class | Target component (spec §) | Src lines | Test lines |
|---|---|---|---|---|
| house-naming runtime `src/house_naming/*.py` | Keep (repurpose as producer core) | `filename_readings` producer, D §6.3; committee codes for D §7.5 | 3,993 py + 34,977 JSON data | 13,325 py + 2,295 JSON |
| house-naming `scripts/` (audit tools) + `tools/build.py` | Keep | catalog maintenance; imported by its tests | 581 + 71 | (in the 13,325) |
| house-naming `archive/tools/` | Dormant | proposed: catalog_version change review, D §6.3 / §7.1 | 1,502 | 0 |
| house-naming `bill_codes.py` | Dormant | proposed: `measure_keys` / `gpo_package_id` vocab, D §6.3 | 49 | (in test_audit_remediation_tcs4) |
| docspec_client custody path (`client.py`, `host.py`, `transport.py`, `schema.py`, `binary.py`, `__init__`) | Keep (news_lake, committee explorer use it) | none in archive target; parked consumers, P §7 | 2,267 (1,411+326+217+179+47+87) | 187 (test_ipc_and_merge) |
| docspec_client `verify_runtime` / `resolve_docspec_binary` / `QUALIFIED_DOCSPEC_RUNTIME` | Repurpose | pinned engine check, A §12 | client.py:177-240, binary.py:7-47, models.py:16-25 | — |
| docspec_client archive-only builders (CC / aggregate models, merge, facet, viewer normalizers) | Replace | the model's job spec (A §13.7, P C7) | est. ~530 | 321 (test_export_policy) |
| docspec_client pure-Python BLAKE3 | Replace (by the `blake3` library) | — | 107 (transport.py:18-124) | ~15 (one test) |
| docspec_client shims `docspec.py`, `docspec_host.py` | Replace (after news_lake imports move) | — | 124 | 0 |
| corpus_recovery keep set (`guards`, `acknowledge`, `html`, `govinfo`, `admission`*, `inventory`*) | Keep (with spec changes) | recovery imports, A §7.2; P §8 keep list | 875 (149+4+56+106+249+311) | 235 |
| corpus_recovery `assemble`, `transfer` | Repurpose | recovery receipt writer, D §5.2; A §7.1 | 272 | 421 |
| corpus_recovery `mappings`, `publication`, `preservation`, `diagnostics` | Replace | provenance `recoveries` (D §5.3); model publish (A §10) | 547 | 971 |
| scripts/corpus_recovery keep (`prepare_batch`, `reconcile`, `run_corpus_recovery`) | Keep | recovery imports, A §7.2 | 311 | 155 + 218 (govinfo test) |
| scripts/corpus_recovery `prepare_source_records`, `dispatch_import`, `coalesce` | Repurpose | D §5.2 import lines; P B7 code identity | 549 | 485 (223+63, plus test_dispatch_corpus_recovery_import 199 in the package tests) |
| scripts/corpus_recovery `dispatch_corpus_recovery_publication.py` | Replace | publish job, A §10.3 | 483 | 615 (476 + 139) |
| scripts/webharvest | Keep (+ repurpose samples) | recovery acquisition upstream of A §7.2; `url_key` unwrap samples, D §7.2 | 1,616 | 757 |
| news_lake (all) | Keep (parked, P §7) | not part of the archive target | 9,394 | 7,799 |
| source-fetch (Rust) | Keep (with changes) | fetcher transport, A §7.1 | 357 (main.rs:1-357) | 42 (main.rs:358-399) |
| scripts/dev.py + test-suites.toml | Keep | project runner (P §3) | 258 | 0 |
| scripts/incremental_boundary_proof.py | Dormant → Replace | (spike; P §6.6 row 1) | 261 | 55 (congress_api tests) |
| scripts/README.md | Keep (rewrite at switch) | — | 38 (md) | — |
| tests/conftest.py | Keep | loopback marker, binary defaults | 33 | — |
| tests/e2e tiers 1–4 + harness + runner | Replace | contract test / invariants, A §15 (not reusable as is) | — | 6,113 + 878 + 254 |
| tests/e2e tier 5 (adversarial) | Replace (with their subjects) | — | — | 1,158 |
| tests/fixtures | symlink → `packages/congress_api/tests/fixtures` (365 files, 11 MB) | parent's scope | — | — |

\* `admission.py` and `inventory.py` survive only after their raw-index branches are cut; see §2.3.

#### 2. Detail per package

##### 2.1 house-naming (`packages/house-naming`)

**Keep.** It is the filename parser the target keeps (A §13 forbids filename parsers in the engine; P §2 lists it as surviving). Public API: `Engine.extract(filename, *, member_surnames=None, source_url=None)` (engine.py:61-88) returns `metadata: dict[str, list[str]]` built by `values.filename_metadata` (values.py:18-165). `catalog_version` in `guide.json` is `"3.2.7"`, equal to `__version__` (`__init__.py:7`).

Production callers today: `congress_api/retention/index/schemas.py:437-493` (`extract((filename, source_url))`), `index/metadata.py:487-497` (`parser_fingerprint`), `viewer_publication/filename_viewer.py:132-133`. The CLI, corpus helpers and audit scripts serve its own tests.

**What it already returns for each D §6.3 column** (probe outputs on `HHRG-118-AG03-20230301-SD001.pdf`, `CHRG-118hhrg52348.pdf`, `BILLS-118hr1234ih.xml`, `HHRG-118-AG03-MState-S001234-20230301.pdf`, `HR1234_S001234_001.pdf`):

| D §6.3 column | house-naming output today | Producer must compose |
|---|---|---|
| `document_kind`, `document_family` | `document_kind`, `document_family` lists (values.py:128-164; `categories.document_families` categories.py:61-68, sorted) | nothing |
| `committee_code` | `committee_code` list (strict record field `committeeCode`, snake-cased at values.py:116) e.g. `["AG03"]` | nothing (the key mapping is the model's, D §7.5) |
| `congress` | `congress` list of strings, e.g. `["118"]` | int, set only when exactly one value |
| `date_token` | `date_token` list | scalar when exactly one |
| `measure_type`, `measure_number` | `measure_type` (lowercased, values.py:96-97, 121-122), `measure_number` (raw digits) | scalar when exactly one |
| `filename_date` | `meeting_date` as `YYYYMMDD` text; `date_token_candidates` as ISO dates | `meeting_date` → date, else the single candidate, else null |
| `measure_keys` | `measure_references` like `hr1234` (values.py:105, no congress, leading zeros stripped), plus `measure_type` / `measure_number` | `{congress}-{type}-{number}` (needs the congress; see §4) |
| `bioguide_ids` | `bioguide_token`; `sponsor_bioguide_id` and `member_bioguide_id` (roles, upper-cased at values.py:100-101) | union, sorted |
| `gpo_package_id` | `package_family` / `package_family_code` (GPO collection, e.g. `chrg`, `bills`, `crpt`); `naming.COLLECTION_CODES` (naming.py:41-43) holds the 22 GPO collections | the stem, only when `package_family_code` is a GPO collection (HHRG/HMKP are also emitted as `package_family`, so the code check matters) |
| `status`, `error_type` | `NamingError(code, message)` (errors.py:5-12) | today `schemas.py:491-492` swallows it and returns `{}`; the producer must write `status='error'`, `error_type=code` |
| `fields` (fold) | everything else, including `_code`, `_label`, `_candidates` variants | fold, minus the typed columns |
| `catalog_version` | `guide['catalog_version']` = `3.2.7` | D wants it to cover vocabularies passed in (`member_surnames`; none passed today), the typed-field derivations and the effective-filename rule. `congress_api/retention/index/metadata.py:487-497` already hashes the package's `.py` and `.json` plus `extract`'s source: lift it and add the producer's own code. |

**Committee vocabulary vs `'hs' || lower(code)`.** `guide['committees']` holds 131 House folder codes over 27 two-letter prefixes. Six of those prefixes are not House standing committees: `EC00` Joint Economic Committee, `IT00` Joint Committee on Taxation, `JL00` Joint Committee on the Library, `JP00` Joint Committee on Printing, `JR00` Joint Select Committee on Deficit Reduction, `HL00` Commission on Security and Cooperation in Europe. `IG00` is the House Intelligence committee, whose Congress.gov code is `hlig00`, not `hsig00`. That is documented in `congress_api/matching/house.py:33` ("hs for standing committees, hl for Intelligence and the select committees (hlig00 is IG00)") and tested at `congress_api/tests/test_meeting_inventory.py:41`. The field type also allows two-character codes (`committeeCode` pattern `^[A-Z]{2}(?:[0-9]{2})?$`), and `Engine.committee` says "'AG' is not rewritten to 'AG00'" (engine.py:102-104). So the rule yields `hsag` for `AG`. See §4.

**Dormant pieces.**
- `archive/tools/` (1,502 lines, 9 files): no importers. They were moved there in aa3bd2aa (2026-10-23, "purge house-naming bloat"). They replay saved filenames through a frozen and a current parser and diff the metadata in both directions (`compare_filename_metadata.py`, `recompare_filename_metadata.py`, `check_house_naming_upgrade.py`). **Proposed use:** the review step before the model profile moves to a new `catalog_version` (D §6.3: "a new catalog version is one background job"; D §7.1: the profile moves when the new version's work list is empty). Run over two `filename_readings` versions instead of saved Parquet.
- `bill_codes.py` (49 lines): GovInfo bill types and versions from `guide['extraction_vocabularies']`. Only its own test imports it (`tests/test_audit_remediation_tcs4.py:12`). **Proposed use:** validate the `type` in `measure_keys` and split the `BILLS-…` stem when composing `gpo_package_id`.

##### 2.2 docspec_client (`packages/docspec_client`)

**Who imports it** (non-test, outside the package): `congress_api` (raw_storage, docspec, docspec_host, native_features, catalog_dependency_storage, catalog_memberships, document_review_catalog, weekly_tables, cli/raw_sync), `viewer_publication` (filename_exports, publish_docspec_runtime), `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py`, **`news_lake`** (storage/docspec/client.py, incremental.py, schema.py) and **`apps/committee_youtube/src/committee_explorer/docspec_views.py`**.

**After the switch it is still used.** news_lake (parked; P §7 says it "keeps the DocSpec backend") calls about 30 `NativeDatasets` methods through `news_lake/storage/docspec/client.py`, including `refresh`/`plan_refresh`/`seal_generation` (lines 95-101), `compact_lifecycle` (159), `read_keys` (225), `changes_batches` (243), `read_changes` (258), `capture_inputs` (263), `run_ipc` (278) and `update_ipc` (304), plus the export path (`export`, `export_pin`, `latest_export`). The committee explorer uses `try_latest`, `run_table`, `refresh`, `update_table`, `export` and `hash_input`. news_lake also imports the shim modules `docspec_client.docspec` and `docspec_client.docspec_host`.

**Repurpose for A §12 ("pinned by revision and digest and MUST be checked before any storage access").** `NativeDatasets.verify_runtime` (client.py:177-240) checks the binary's SHA-256, its platform from the header magic, a 40-hex source revision, build features and capabilities. It runs before every CLI call (`_call`, client.py:316-326) and before host acquisition (`_acquire_host`, client.py:332-344). Changes needed:
- pins are optional (`_has_runtime_pins`, client.py:312-314);
- `resolve_docspec_binary` falls back to sibling build directories and then `shutil.which("docspec")` (binary.py:22-47), which is a PATH lookup;
- `QUALIFIED_DOCSPEC_RUNTIME` (models.py:16-25) pins `c949c676…` with a darwin-arm64 digest only. That revision is an ancestor of the pinned d9c6719, 7 commits behind it.

The target launcher needs mandatory pins, no PATH fallback and a Linux digest.

**Replace at the switch (archive-only), est. ~530 src lines.** These have no news_lake or committee-explorer user:
- `ConnectedEdgeSpec`, `AggregateSpec` and `ConnectedComponentsTransform` (models.py:328-352, 409-540);
- `apply_update_merge_spec` and `_merge_row_pair` (specs.py:476-692; only `congress_api/retention/raw_storage.py:376-515` uses them);
- `facet_summary` (specs.py:430-475);
- the viewer-only normalizers for `fold_readings`, `facet_sets` and `child_tables` (specs.py:69-98, 117-198).

`build_export_spec`, `parse_export_pin` and the policy normalizers stay, because news_lake's C5 export (`news_lake/storage/docspec/export.py:121`) goes through them. Tests: `test_export_policy.py` (321) goes with them.

**Pure-Python BLAKE3** (transport.py:18-124, 107 lines) runs for every `run_ipc`/`update_ipc` payload (client.py:432, 605) unless the `blake3` package is installed. It is not a declared dependency (`pyproject.toml` lists only httpx and pyarrow), and grep finds no `blake3` in `uv.lock`, so in practice it always runs, at Python speed and O(bytes) per payload. Replace it with the maintained `blake3` library (or an engine-computed digest) and delete the fallback.

##### 2.3 corpus_recovery (`packages/corpus_recovery`) and `scripts/corpus_recovery`

These are raw writers for recovery imports (A §2 "raw writer"; A §7.2).

**Keep, with spec changes.**
- `guards.py` (149): `RecoveryGuard` (lines 64-149) and `active_cloud_writers` (36-60) are on the P §8 keep list. `GuardedNative` (20-33) wraps native candidate runs and goes at the switch.
- `acknowledge.py` (4): re-export of `congress_api.retention.write_recovery.reconcile_lost_acknowledgment`.
- `html.py` (56): classifies recovered HTML. Its title words (lines 13-16: "session verification", "rate limit reached", "access denied", "request not accepted", "page not found", "404 not found", "just a moment") are real samples for D §7.1's error-words registry; see §4.
- `govinfo.py` (106): keeps a GovInfo ZIP and every member as separate captures (`prepare_capture(..., mode='retained_import')`, line 76-77). This matches A §7.2 ("an archive's members are separate entries in one line").
- `admission.py` (249): `verify_import` is on the P §8 keep list ("recovery admission"). It verifies `indexes/raw.json` identity and its write events (lines ~196-236). That branch goes with the raw index, so it does not survive unchanged.
- `inventory.py` (311): `reconcile`, `head_body` and `sealed_inputs` keep the read-only batch-vs-store check. `scan_receipt_history` (139-267) reads the old raw_archive tables and must read `captures` instead.

**Repurpose.**
- `assemble.py` (106) builds the recovery receipt lines. To meet D §5.2 it must drop `preserve_download_state` and `download_state` (lines 53-59, 92-94; D §5.2: "New lines MUST NOT carry … `download_state` and `preserve_download_state`") and drop `source_file`/`source_line` in favour of `run_id`. It must also emit `recovery_evidence.{original_url, imported_at, match_basis, acquisition.*}` and `writer`. `index_rows` (97-106) feeds the raw index and goes.
- `transfer.py` (166): `checked_put` (25-46) and the body loop (115-137) are the upload path. Today they:
  - require and write the older layout `bodies/sha256/<aa>/<sha>.gz` (lines 109-112, 119-120; `raw_archive.body_payload` gzips every body at level 1);
  - do a full `store.read(key)` GET before upload (129);
  - read the body back in full after every PUT (`checked_put` 40-45) and decompress-compare it (134);
  - read each local body fully into memory (116).

  A §7.1 asks for a `<sha>` key with `Content-Encoding` for compressible types, one create-only PUT with `Content-MD5`, and a 412 counted as unchanged "with no HEAD and no comparison". `import_batch`'s raw-index selection (`RawStorage.prepare/publish`, 151-166) goes. Lift the guard, journal and save_payload seams.
- `scripts/corpus_recovery/prepare_corpus_recovery_source_records.py` (215) already implements D §5.2's "`retrieved_at` … the recovered copy's own original time". It picks one explicit `timestamp_basis` from five sources (archive index capture time, existing official capture, sealed package member capture, transport receipt, rendered transport receipt; lines 130-158) and records the basis. Changes:
  - read `captures` instead of the old capture Parquet (lines 104-111);
  - stop copying the whole recovery row into `recovery_evidence.acquisition` (line 167), because it carries local paths (`body_path`, `request_evidence`), which D §5.2 forbids;
  - the `.gz` body-key check at line 126 changes with A §7.1.
- `scripts/corpus_recovery/dispatch_corpus_recovery_import.py` (212): the lock, cloud-writer check and guard wiring survive. The code pins (lines 113-128) hash every `congress_api` `.py` file, the scripts, the corpus_recovery modules and the native execution files, and the guard re-checks them during the run. That detects a mid-run change, but it does not refuse uncommitted code and does not digest `uv.lock`. P B7 wants the git tree hash plus the `uv.lock` digest and a refusal of uncommitted changes. `viewer_publication/release_identity.py:58,95` already digests `uv.lock` (another fork's scope) and can be reused. The baseline reads of `indexes/raw.json`, `indexes/catalog.json` and `accepted.json` (151-162) go.
- `coalesce_corpus_recovery_batches.py` (122): batch sealing survives; the `accepted.json` mapping baseline goes.

**Replace.**
- `mappings.py` (111) writes `viewer-publications/recoveries/accepted.json` with `If-Match`. Its replacement is provenance `recoveries` records (D §5.3) through P B8. Its "a conflicting edit to an old decision is refused" check (lines 31-38) becomes D §5.3's rule that a correction is a new record superseding by `id`.
- `publication.py` (142): catalog, mapping and viewer phases.
- `preservation.py` (258): compares native raw-index selections.
- `diagnostics.py` (36): catalog build observation.
- `scripts/.../dispatch_corpus_recovery_publication.py` (483), including `SelectedRuntime` (21-150).
- Tests:

  | Test | Lines |
  |---|---|
  | `test_accepted_viewer_plan` | 301 |
  | `test_publish_corpus_recovery_mappings` | 315 |
  | `test_merge_corpus_recovery_mappings` | 51 |
  | `test_catalog_diagnostics` | 29 |
  | `test_verify_corpus_recovery_import_preservation` | 150 |
  | `test_native_import_preservation` | 125 |
  | `test_dispatch_corpus_recovery_publication` | 476 |
  | `test_runtime_ownership` | 139 |

**Recovery kinds (D §7.8).** `prior_access_category` appears nowhere in code: no `.py`, `.ts` or `.json` in the repo, and no commit (`git log -S` hits only docs). It exists only in the 2026-10-15 receipts in R2, written by a tool not in this tree. corpus_recovery imports carry `source_associations[].basis` (`recovery_basis`, e.g. `user_accepted_url_variant`, `official_document_identifier`, `resolved_source_url`, `web_archive`) and no category. So D §7.8's "an unmapped category MUST fail the build" fails every corpus_recovery import unless the registry maps their absence. See §4.

##### 2.4 scripts/webharvest

**Keep.** It is an acquisition tool that stops at local receipts; import goes through corpus_recovery. No importers outside the folder and its tests.

**Repurpose as `url_key` samples (D §7.2).** `webharvest_committee_map.split_replay` (lines 42-65, regex line 26) parses `webharvest.gov/congress<NNN><xx>/<selector>/<embedded>`. It handles three embedded-URL styles: an explicit scheme, a single-slash scheme (`http:/host`) and an omitted scheme (assumed http). The selector may also be a redirect selector rather than a 14-digit timestamp. D §7.2's unwrap names only `webharvest.gov/<collection>/<ts>[modifier]/<url>`. These cases belong in the URL-wrapper registry's samples (§4).

**Note.** `webharvest_cdx.key` uses SURT canonicalization (`surt`, line 31-41). SURT is right for matching CDX keys but differs from `url_key`, so do not reuse it there.

##### 2.5 news_lake (`packages/news_lake`)

**Keep (parked, P §7).** The archive target never touches it.

**What it shares with the archive.** It imports `docspec_client` (above) and `congress_shared.custody` (`canonical_json_bytes`, `write_atomic_bytes`, `verify_local_file`). One congress_api test imports it (`congress_api/tests/test_native_features.py:474`); that test goes with native_features. `validate-explorer.yml:16-17` triggers on its paths.

**Groups.**

| Group | Lines |
|---|---|
| `storage/docspec` + backend shim | 4,351 |
| pyiceberg reference stack (`catalog`, `coordinator`, `control`, `releases`, `mapping`, `partitions`, `arrow_patch`) | 1,624 |
| `contract` | 441 (+ schema JSON 512) |
| `adapters` | 986 |
| `identity` | 476 |
| `analysis` | 838 |
| `cli` / `context` / `__init__` | 522 |
| `docs/checks/validate.py` | 156 |

**Engine-first duplicates, parked.**
- `storage/docspec/incremental.py` (1,120) derives bridges incrementally in Python from native change streams.
- The pyiceberg coordinator and catalog are a second Python Iceberg writer, kept as a differential oracle.

**Risk for the engine cuts.** P §6.6's docspec-rs row removes "unused routes, lifecycle families". news_lake still calls lifecycle routes (`seal_generation`, `compact_lifecycle`, `changes_batches`, `read_keys`; client.py lines above). The docspec-rs delete count must treat news_lake as a live consumer.

**Not reusable for D §6.2.** `adapters/urls.normalize_url` (lowercase scheme and host, drop the fragment) and `analysis/cluster.normalize_text` (casefold plus whitespace collapse) both differ from D's rules. D §6.2's fingerprint is NFKC with no casefold.

##### 2.6 source-fetch (`packages/source-fetch`, Rust)

**Keep (A §7.1 fetcher transport).** Its only caller is `congress_api/transport/rust_fetch.py`, via `cli/raw_sync.py`. It already:
- spools each body to `<id>.body` with `create_new` (main.rs:183-188), which satisfies A §7.1's "spool each body to a temporary file";
- decodes gzip, br and deflate within a byte cap (203-241);
- refuses declared-oversize bodies (130-156, 192-201);
- shares a rate limiter and disables automatic redirects.

**Changes needed.**
- The cap is the caller's: `rust_fetch.py:134` defaults `max_bytes=64 * 1024**2`, which is the source of the 201 cut-off bodies. A §7.1 wants anything up to 5 GB stored whole.
- It emits every header as `response_header_items` (main.rs:163-176). D §5.2 forbids that field on new lines and requires the allowlist; it can be filtered here or in Python.
- It computes no SHA-256, MD5 or sniff. Adding them to the copy loop (225-236) would save Python a second full read of every spooled body (A §4.3 "do expensive work once").
- The README names a `reqwest-fetch-bench` binary and an `experiment.md` that do not exist (Cargo.toml declares only `source-fetch`).

##### 2.7 scripts/dev.py, test-suites.toml, README, incremental_boundary_proof.py

- **`dev.py` (258) — Keep; it is the runner P §3 mandates.** Lanes come from `test-suites.toml`. `production-offline` roots include every package's tests, the root `tests` and `scripts/*/tests`; `native-loopback` needs `SOURCE_FETCH_BINARY`. No lane names a deleted layer by name, but the roots cover tests of deleted code; they shrink as those files go. `doctor` checks the pyarrow version against `uv.lock` (lines 97-103) and the poppler binaries; the `baseline` check pins a filename-patterns experiment parser (`test-suites.toml [baseline]`).
- **`incremental_boundary_proof.py` (261 + 55-line test `congress_api/tests/test_incremental_boundary_proof.py`) — Dormant.** No production importer; it is the ct-l5q1 spike, with `docs/experiments/incremental-boundary-20261019.md`. The ticket audit found its test checks the fixture only (`docs/reviews/2026-10-24-ticket-audit/batches/czsd/czsd-verdicts.md:36`). Delete it as P §6.6 says. It is not part of the live incremental catalog.
- **`scripts/README.md` (38) — Keep, rewrite at the switch.** It describes "indexes" and the filename-viewer publish.

##### 2.8 Root tests/

- **`tests/conftest.py` (33) — Keep.** It defaults `DOCSPEC_BINARY` to `../spicy-stack/docspec-rs/target/release/docspec` with no revision or digest check (lines 14-16). That is fine for tests, but it is not the A §12 pin.
- **`tests/e2e` — Replace (8,403 lines in all: tiers 7,271, harness 878, runner and conftests 254).** It is the ct-4t6s "opaque-box" suite, added in f2fea711 (2026-10-22). Its features F1–F29 are the old source Parquet, weekly tables, raw archive, canonical catalog and browser tables (run_all.py:31-61).
  - 15 of 31 test files (3,469 lines) import no production code. They build a schema inside the test and ask the harness oracle about it, for example `test_f20_source_columns_dropped_from_filenames` (tier1 test_f20_f23:30-45). That is a check that agrees with itself and verifies nothing.
  - Tier 4 reads `../pipeline-data` and `output/…` and skips when they are absent.
  - Tier 5 imports deleted modules (`weekly_tables`, `raw_archive`, `viewer_publication.compact_readings`/`filename_exports`) and the committee explorer.
  - The harness's `LocalR2Staging` (staging.py:35-81) writes a third body layout: `.pdf` uncompressed for PDFs, `.gz` for others.
  - Small reusable pieces for A §15 release checks: `ParquetOracle.verify_row_group_metadata` (parquet_oracle.py:116-158: row-group bounds and footer ratio) and `verify_unique_keys` (183-199). The latter is an O(n) Python set; at release scale prefer pyarrow or the engine.

#### 3. Repurpose opportunities (ranked by target work saved; estimates)

1. **house-naming as the `filename_readings` producer core (D §6.3).** All facets and keys already come out (table in §2.1). The producer adds only scalar collapse, `filename_date`, `measure_keys`, `bioguide_ids` and `gpo_package_id` composition, the status/error mapping from `NamingError.code`, and `catalog_version`. *Saves est. most of the producer: the parser is 3,993 lines plus 35k lines of catalog data; the new code is est. 150–250 lines.*
2. **`prepare_corpus_recovery_source_records.py` timestamp-basis logic (D §5.2 recovery `retrieved_at`).** Five-way evidence selection with an explicit basis (lines 130-158). *Saves est. 100–150 lines and the review of which time a recovered copy carries.*
3. **`docspec_client.verify_runtime` + `resolve_docspec_binary` for A §12.** Digest, platform, revision and capability checks before any call. *Saves est. 80–120 lines; changes are mandatory pins, no PATH fallback and a Linux digest.*
4. **corpus_recovery `assemble` + `transfer` body loop as the recovery-import writer (A §7.1–7.2, D §5.2).** Keeps the guard, journal and save_payload seams and the receipt chunking (100 lines per file). *Saves est. 150 lines; the layout, PUT semantics and line fields change as in §2.3.*
5. **`congress_api/retention/index/metadata.py:487-497` `parser_fingerprint` → `catalog_version` (D §6.3).** Already hashes the house-naming sources and data. *Small (est. 20 lines) but it fixes the version rule. Parent's scope; noted here because it belongs to the producer.*
6. **`RecoveryGuard` + `active_cloud_writers` (P §8).** Keep as is for the recovery import's concurrency fence. *Saves est. 150 lines.*
7. **`webharvest_committee_map.split_replay` cases → URL-wrapper registry samples (D §7.1 "each entry carries a real sample", D §7.2).** *Saves est. a day of sample hunting; the code itself is not lifted because the registry is SQL data.*
8. **`corpus_recovery/html.py` title words → error-words registry samples (D §7.1, §7.3).** *Small; closes a gap (§4).*
9. **house-naming `archive/tools` compare/recompare → catalog_version review (D §7.1).** *Saves est. 200–400 lines of diff tooling.*
10. **`bill_codes.py` → `measure_keys` type validation.** *Small.*

#### 4. Rule conflicts (code vs spec — either may be right)

1. **`committee_key := 'hs' || lower(committee_code)` (D §7.5).**
   - `matching/house.py:33-34` and `test_meeting_inventory.py:41` show House select committees and Intelligence use `hl` (`IG00` → `hlig00`).
   - house-naming's own committee table includes joint committees and a commission under House folder codes (`EC00`, `IT00`, `JL00`, `JP00`, `JR00`, `HL00`).
   - Two-character codes (`AG`) are valid filename syntax but give `hsag`.

   The spec's "unmapped unless sample tests confirm" covers Senate and joint codes only. These House-table cases need an explicit registry, which the spec does not list.
2. **Recovery kinds (D §7.8).** No code produces `prior_access_category`. corpus_recovery imports carry none, so "unmapped category MUST fail the build" fails every corpus_recovery import. Either the registry maps absence, or the import writer must start writing a category.
3. **Plan §8 keep list says recovery `checked_put` survives unchanged; A §7.1 / §13.5 disagree.** `checked_put` re-reads every written object in full (transfer.py:40-45). The body loop GETs before upload (129) and decompress-compares (134). It uses the `immutable=` flag that P B3 deletes. A §7.1 says a 412 means unchanged "with no HEAD and no comparison".
4. **Recovery body layout.** The recovery path writes `<sha>.gz` with gzip for every type (transfer.py:119; `raw_archive.body_payload`). A §7.1's new writes use `<sha>` with `Content-Encoding` for compressible types and as-is for PDFs. The e2e harness writes a third layout (`.pdf` / `.gz`).
5. **Recovery receipt keys.** `dispatch_corpus_recovery_import.py:187` uses `receipts/documents/import/<run_id>-<seq>.jsonl.gz`. A §7.2 says "New writers MUST use date-shaped prefixes only", and A §8.2 daily ingest lists only date-shaped prefixes, so these receipts would wait for the weekly sweep.
6. **Recovery receipt line fields.** The lines carry `preserve_download_state`, `download_state`, `source_file` and the whole recovery row with local paths in `recovery_evidence.acquisition` (assemble.py:92-94; prepare_source_records.py:167). D §5.2 forbids the first two and local paths, and expects `run_id` and `writer`.
7. **Provenance `recoveries.kind` (D §5.3) vs `accepted.json` `kind`.** In `accepted.json` (`viewer_publication/filename_recoveries.py:11`), `kind` is the file type (`pdf`), not a display kind. B8's reconciliation must not copy one into the other unless D means file type.
8. **Error words (D §7.1).** D's list is access denied, forbidden, not found, retry later, service unavailable, error. Recovery HTML classification also treats "just a moment" (Cloudflare challenge), "session verification", "rate limit reached" and "request not accepted" as error or challenge pages (html.py:13-16). A challenge page with more than 2,048 text bytes would become a real file under D's list.
9. **`measure_keys` without a congress.** house-naming emits `measure_references` such as `hr1234` with no congress for many filenames (probe: `HR1234_S001234_001.pdf` → no `congress`). D §6.3 gives the key form `{congress}-{type}-{number}` and does not say what happens when congress is unknown.
10. **`bioguide_ids` sources.** D names `bioguide_token` and `sponsor_bioguide_id`. house-naming also emits `member_bioguide_id` from the strict record. It co-occurs with `bioguide_token` in the probe; including it costs nothing and covers strict-only parses.
11. **A §12 engine pin vs today.** Pins are optional (client.py:312-314). Binary resolution can come from PATH (binary.py:43-45; `news_lake/storage/docspec/client.py:35-36`; root `tests/conftest.py:14-16`). The qualified revision is `c949c676` with no Linux digest (models.py:16-25).
12. **D §5.2 header allowlist vs source-fetch.** source-fetch emits every header as `response_header_items` (main.rs:163-176).

#### 5. Capabilities missing (build from scratch)

- The `filename_readings` producer: status/error rows, typed-key composition, the `catalog_version` rule including vocabularies, and an append through the engine. house-naming supplies only the parse.
- A committee-code → Congress.gov system-code registry covering `hs`, `hl`, `js` and two-character codes. Only the reverse direction exists (`matching/house.py:34`).
- A recovery-kind registry and any writer of `prior_access_category`.
- A provenance writer for `provenance/<kind>/<ts>.jsonl` with supersession. Today recoveries go to `accepted.json`.
- P B7 code identity (git tree hash + `uv.lock` digest, refusing uncommitted changes) and D §5.2 `writer {job, commit, lockfile_digest}` on recovery-import lines.
- A create-only, `Content-MD5` body PUT in the recovery path, with 412 = unchanged.
- Streaming hashing and sniffing in the fetch transport (none in source-fetch).

#### 6. Engine-first duplicates (Python doing engine work)

| Code | What it duplicates | Disposition |
|---|---|---|
| `docspec_client/specs.py:476-692` `apply_update_merge_spec` / `_merge_row_pair` | the engine's UpdateMerge, re-done in Python for `raw_storage` | goes with the raw index |
| `docspec_client/transport.py:18-124` | hand-written BLAKE3 | use the `blake3` library |
| `corpus_recovery/transfer.py` `index_rows` + `RawStorage.prepare/publish` (97-106, 151-166) | capture rows computed in Python | goes; A §8.2 ingest replaces it |
| `corpus_recovery/preservation.py` (258) | compares native selections in Python | goes |
| `news_lake/storage/docspec/incremental.py` (1,120) and the pyiceberg stack (1,624) | incremental derivation and Iceberg writes in Python | parked; P §7 says no work |
| `tests/e2e/harness/parquet_oracle.py:183-199` | uniqueness via a Python set, O(n) | if reused, do it in pyarrow or the engine |

#### 7. Delete-table corrections (rows in scope) and misses

- **"`docspec_client`'s HTTP custody path, with its fallbacks and the pure-Python `blake3`, if nothing else uses it" (P §6.6, "at cut").** Something else does use it: news_lake (parked, P §7) and the committee explorer call the custody path (§2.2). It cannot be deleted at the switch. What can go is the archive-only builders, est. ~530 src lines plus `test_export_policy.py` (321), and, only after news_lake moves its imports, the shims `docspec.py` + `docspec_host.py` (124). The pure-Python BLAKE3 (107) goes only by adding the `blake3` dependency, not by deleting the custody path.
- **"Python incremental catalog: 22 modules, the `catalog/` facade, `incremental_boundary_proof.py` — 9,509 + 6,744."** `incremental_boundary_proof.py` is 261 lines plus a 55-line test, and it is a dormant spike, not catalog code. Confirm the deletion; the parent should check whether the 9,509/6,744 counts include it.
- **Misses in scope:**
  - The corpus_recovery raw-index, catalog and viewer coupling is not in the table. Src: `publication.py` 142, `mappings.py` 111, `preservation.py` 258, `diagnostics.py` 36, `GuardedNative` ~14, the `transfer` raw selection est. ~50, `inventory.scan_receipt_history` ~129, `scripts/.../dispatch_corpus_recovery_publication.py` 483, and the mapping part of `coalesce` est. ~60. That is **est. ~1,280 src**. Tests: **1,586** (301+315+51+29+150+125+476+139).
  - `tests/e2e` (**8,403 lines**) tests the deleted layers' outputs or nothing at all.
  - P §8 keep list: "recovery admission" and "recovery `checked_put`" do not survive unchanged (§4 items 3–6).
  - house-naming `archive/tools` (1,502) and `bill_codes.py` (49) are dormant. They are not delete candidates, for the uses proposed in §2.1.

### 4.5 docspec-rs (the engine)

Read-only static review of `/Users/mikewolfd/Work/spicy-stack/docspec-rs` at `d9c6719` (engine `main` HEAD). Paths are relative to that repo unless prefixed `ct:` (`/Users/mikewolfd/Work/wt/ct-ticket-audit`). Nothing was built or run. Counts are `wc -l` on tracked files, made with `fork-docspec/inv_ds_count.py` and `inv_ds_perfile.py` (output in `inv_ds_group_counts.md`). "Inline" means `#[cfg(test)] mod … {}` blocks inside source files, counted as tests. *est.* marks a count derived from a line range, not a whole file.

**Engine size.** 144,756 Rust lines: 66,073 production source, 78,683 tests (40,930 in `tests/`, the rest in `src/**/tests.rs`, `*_tests.rs`, inline modules and the 3,538-line provider suites under `src/engine/remote_build_provider_tests/`). Plus the Dagster adapter (1,583 tracked lines), 1,594 lines of `examples/`, and 1,374 tracked files under `experiments/`.

**Which revision is pinned.** `d9c6719` is engine `main`. congressional-tech pins the runtime at `c949c67` (`ct:packages/docspec_client/src/docspec_client/models.py:16-18`), 7 commits behind. Those 7 commits added the deferred lifecycle commits, the dataset-name predicates and the remote write caps (`b4b827d`, `97373eb`, `d05df4d`), which is why plan C0 can revert them without breaking the consumer.

**Who uses the engine after the switch.** Nothing in `spicysearch`, `spicyengine` or `DocSpec` mentions docspec-rs, `docspec_client` or its routes. Those repos pin the unrelated Python `docspec==0.12.4` wheel (`spicysearch/pyproject.toml:9-21`, `spicyengine/pyproject.toml:8,43`). The engine's only consumers are in congressional-tech:

- the incremental catalog, raw index and viewer publication, all deleted at the switch;
- `news_lake`, parked on DocSpec by plan §7. It calls only `run_table`, `update_table`, `refresh` (join), `changes_batches` (served by `engine/comparison.rs:197`), `read_keys`, `read_arrow`, `latest`, `release`, `export` (with `computed_columns`), `compact`, `compact_lifecycle`, `seal_generation` and `capture_inputs` (grep of `ct:packages/news_lake/src`);
- the committee explorer, optionally. It runs only when `DOCSPEC_BINARY` is set (`ct:.github/workflows/publish-explorer.yml:103-105`), and uses aggregate refresh with `first_value_by`, `collect_distinct_with_provenance` and `collect_set` (`ct:apps/committee_youtube/src/committee_explorer/docspec_views.py:115-205`) plus export.

The target archive uses none of the lifecycle store, so every "Keep" below for lifecycle code means **kept for news_lake or the committee explorer, outside the target**.

#### 1. Summary

| group | class | target component (spec §) | src lines | test lines |
|---|---|---|---:|---:|
| ConnectedComponents kernel: `DisjointSet` + streaming scan (`topology.rs:31-280`), spec validation (`connected_components.rs:39-202`) | Repurpose | C4 grouping (A §9.3, §13.4; D §7.5) | *est.* 414 | shared: `tests/partitioning_and_cc.rs` 1,228 (mixed) |
| CC lifecycle wrapper: `eval.rs`, `incremental.rs`, `lineage.rs`, closure and evidence (`topology.rs:283-509`), `compute_document_id`, `is_body_edge` | Replace | model SQL aggregates and ID formula (D §7.5); no incremental CC (A §5) | *est.* 1,565 | in `partitioning_and_cc.rs` and `related_refresh/` (not split) |
| `connected_components/sha256.rs` (hand-written SHA-256) | Replace | DataFusion `sha256()` in model SQL; `sha2` crate for C3 digests | 85 | 29 |
| Export writer core: `export/pipeline.rs`, `pipeline/child.rs`, `parent.rs` (fold), `facets.rs`; `HashingFile` (`export.rs:658-697`) | Repurpose | C3 deterministic multi-file export (A §10.1-10.2, §13.3; D §8.1) | 1,902 + *est.* 40 | shared: `tests/exports.rs` 2,037, `tests/exports/mcp.rs` 399, `src/engine/export/tests.rs` 706 |
| Export child-slice reader `pipeline/slice.rs` | Dormant | C3 acceptance oracle ("page reads on the output", plan C3) | 474 | used only by `tests/exports.rs:1573-1805` |
| Export lifecycle shell: `engine/export.rs` (spec, channels, authority), `export/host.rs`, `export/remote.rs`, `export/read.rs`, `export/validation.rs`, `src/export.rs` | Keep (news_lake, committee explorer); `validation.rs` Repurpose | — / C3 output checks | 2,816 | 1,026 |
| Storage write path: `write_batches_inner` (`storage.rs:359-659`), `append` (`storage.rs:858-929`), `storage/batch.rs` | Repurpose | C2 lake appends (A §8.1; D §6) | 1,749 (whole files) | in `storage/tests.rs` 1,150 (shared) |
| Table properties (`storage.rs:132-140`) and the lifecycle gc toggle (`catalog.rs:1134,1163`) | Replace (C0) | D §6 table properties | *est.* 12 | — |
| Remote write caps (`storage.rs:376-390`) | Replace (C0, unless M1.3 keeps them) | D §6 writer settings | 15 | — |
| `storage/pinned.rs` (`TablePin`, `open_pin`) | Repurpose | pinned snapshots (A §10.3.1) | 381 | 216 |
| `query.rs`, `query/sequence.rs` (`NativeTable` DataFusion provider) | Repurpose | C1 multi-input SQL (A §13.1) | 929 | 1,115 |
| `budget.rs` (threads, `FairSpillPool`, scratch) | Keep | C6 bounded resources (A §12, §13.6) | 231 | 210 |
| `sql_validation.rs:169-220` (refuses volatile functions) | Repurpose | determinism guard (A §10.2) | *est.* 52 of 390 | — |
| `storage/remote.rs` (`RemoteCatalog`: REST, 429/5xx retry, requirements passed through) | Keep | C1/C2 Basin access (A §8.1, §13.2) | 368 | 40 |
| `storage/remote/objects.rs`: scope boundary, create-only writes, digest-verified delete actor | Keep (plan §8) | raw-bucket isolation (A §14) | 1,019 | 2,809 (`objects/tests*`, `removal_tests`) |
| ↳ `upload_file` / `verify` / `verify_if_present` (multipart + BLAKE3 readback) | Repurpose | release upload (A §10.3.4, §13.5) | *est.* 160 of the above | — |
| `storage/remote/namespaces.rs` (namespace generations) | Unclear | — | 167 | 251 |
| `storage/partitioning.rs` | Keep identity transforms; Replace hand-written calendar (`:94-169`, `:335-360`) | readings and filename_readings partitions (D §6.2-6.3) | 456 (calendar 102) | in `tests/partitioning_and_cc.rs` |
| `catalog.rs` lifecycle KV store | Keep (news_lake); deferred commits (`:80-87`, `:242-326`) Replace (C0) | none; target has no lifecycle store (plan §6.3) | 1,419 (deferred *est.* 93) | 596 |
| Engine core: pipeline, planner, admission, locations, write and merge, refresh (join), changes, comparison, inputs, compaction, verification, key pruning, occurrences, model, IPC (HTTP is its own row) | Keep (news_lake) | none in target | ≈ 24,000 *est.* (sum of those group counts) | ≈ 10,500 unit + most remaining integration suites, ≈ 30,000 *est.* |
| `engine/aggregation*` (UDAFs) | Keep (committee explorer); Dormant for target | — | 1,556 | 556 |
| Backfill family: `engine/backfill/**`, `engine/intake.rs` | Replace (no consumer after the switch; coupled) | — | 6,140 | 2,592 + 4,513 integration |
| Schema evolution `engine/schema.rs` | Replace (no consumer after the switch) | — | 806 | 766 |
| Dependency corrections `engine/corrections*` | Replace (no consumer after the switch) | — | 662 | 886 |
| Evidence updates `engine/evidence.rs` | Replace (no consumer after the switch) | — | 1,014 | 1,599 |
| Retirement planners (`changes/retirement.rs`; `retention/{availability, compaction_recovery, export_recovery, grants, recovery, retirement, seals}`) | Replace | — | 2,548 | 2,999 + 3,189 integration |
| Retention inventory, owners, removal, lifecycle GC (`retention.rs`, `retention/{compaction, inventory, owners, removal}`), `storage/removal.rs` | Unclear (news_lake's `compact_lifecycle` needs part of it) | — | 7,080 | 5,739 + 1,603 integration |
| Restore points and remote restore (`src/restore*`, `engine/restore*`) | Replace | — | 2,483 | 559 + 1,200 integration |
| Succession history `engine/history/**` | Replace, after untangling (`compact_lifecycle` calls it) | — | 1,178 | 923 + 566 integration |
| Provider qualification suites `engine/remote_build_provider_tests/**` | Replace | one isolation smoke test (A §14) | — | 3,792 |
| Other remote and profile tests (`remote_startup_tests.rs`, `remote_query_tests.rs`, `profile_tests.rs`) | Keep startup and query tests; profile tests Dormant | C1 remote config | — | 1,986 |
| `test_hooks.rs` and fault injection (56 `stop_after` sites, 167 test-util cfg lines in 46 files, 60 production-only branches) | Replace | A §13 forbids test-only production paths; A §15.7 ratchet | 179 + threading at cut | — |
| Dataset-name predicates (`pipeline.rs:317-335`, `pipeline/completion.rs:234-237`, `release_check.rs:86-93,226-229`, `write/build.rs:362-372`) | Replace (C0) | A §13 MUST NOT, A §15.7 | *est.* 40 | — |
| `main.rs` (clap, JSON stdout `:1339`), `error.rs`, `progress.rs` | Repurpose | C7 job-spec CLI (A §13.7) | 1,834 | 425 |
| `cli_args.rs` | Replace | — | 150 | 53 |
| HTTP: 77 routes, about 10 alias routes (`http.rs:44-72`), retention handlers `http/retention.rs` | Keep core (news_lake via HTTP); Replace aliases and handlers of retired families | — | 1,924 (`retention.rs` 389) | 653 |
| `adapters/dagster` | Replace | — | 1,583 (all files) | (included) |
| `examples/` (R2 probes, Comments probes, `news_poll_scale`, `layout_probe`) | Dormant; `layout_probe` Keep (used by `tests/layout_probe.rs`) | M1 harness seed | 1,594 | — |
| `experiments/`, `docs/reviews/` | Dormant evidence archive (not code) | — | 1,374 and 1,251 tracked files | — |

#### 2. Detail by group

##### 2.1 ConnectedComponents (C4)

**What exists.** `topology.rs:31-75` is a disjoint-set forest (path halving, union by rank). `GraphTopology::from_table` (`topology.rs:94-280`) streams a projected DataFusion table and unions each row with:

- the first row that had the same `row_key` (`:193-196`);
- the first row that had the same `(namespace, token)` (`:202-216`).

So a group of n rows costs n−1 unions, not n²: the "one node per body, n edges" property of A §9.3, achieved without explicit token nodes. Memory is charged to the shared budget as it grows (`:224-232`), so an oversized graph refuses cleanly.

**What does not match the target.**

- **Not 32-bit, and no node cap.** Parents are `Vec<usize>` (`:32`). Every row retains a cloned `String` row key, file path and token list (`:185-221`), and the indexes are `HashMap<String, usize>` and `HashMap<(String, String), usize>` (`:126-127`). A §13.4 asks for in-memory 32-bit IDs and a refusal above a configured node count. The engine refuses on a byte budget only.
- **Application policy compiled in.** The engine computes `document_id` itself (`connected_components.rs:23-36`, called at `topology.rs:259`). It decides which edges are bodies by the names `body`, `bodies` and `body_key` (`topology.rs:24-29`). Both are application policy that A §13 forbids in the engine, and both trip ratchet 7 (A §15.7).
- **Input and output are lifecycle-bound.** `register_input` reads a `ReleasePin` (`connected_components.rs:93-122`). `from_table` requires the `__docspec_file` and `__docspec_row` occurrence columns (`topology.rs:104-108`).
- **Incremental machinery the target does not need.** The model recomputes every run (A §5), but the engine carries closure over old and new topologies (`topology.rs:422-509`), incremental refresh (`incremental.rs`, 281 lines) and representative aggregates with BLAKE3 change signatures (`eval.rs`, 944 lines). The aggregates belong in model SQL.

**Repurpose.** Lift `DisjointSet` and the batch-streaming budget pattern into a generic operator over `(node u32, group u32)` pairs. Assign dense IDs with a SQL hash aggregation or `dense_rank`. Add the node cap. Return `(node, component)` as a relation. Delete the rest.

Only CT's incremental catalog uses CC refresh today (`ct:packages/congress_api/src/congress_api/retention/native_features.py:1179-1237`), so the wrapper has no consumer after the switch.

##### 2.2 Export (C3)

**Writer core (Repurpose).** The parent stream (`pipeline.rs:445-669`) already:

- writes one Parquet file through `ArrowWriter`;
- hashes while writing (`HashingFile`, `export.rs:658-697`, BLAKE3);
- caps rows per row group (`:537-544`);
- refuses an oversized footer (`:623-631`, `:652-657`);
- accumulates facet counts (`facets.rs`), browse ranges and unnested child tables (`child.rs`: sorted by parent key then ordinal, with its own writer, `:240-301`);
- folds sparse columns (`ReadingsFoldSpec`, `src/export.rs:36-98`).

Writer properties are built in one place (`pipeline.rs:672-702`).

**Required changes**, each against D §8.1 or A §10.2:

1. **Flush on row count only.** Today it also flushes on `memory_size()` and `in_progress_size()` (`pipeline.rs:605-616`, `child.rs:357-363`) and sets `set_max_row_group_bytes` (`:681`). These depend on upstream batch boundaries, so they break byte determinism across thread counts and spills.
2. **Re-batch input to the pinned write batch.** Today batches are split by bytes (`storage::split_oversized_batch`, `pipeline.rs:556`).
3. **Per-file and per-column settings:**
   - `filename` with dictionary off and `DELTA_BYTE_ARRAY`;
   - offset index on every leaf for `detail`, `occurrences` and `recoveries`;
   - a 1,024-row page limit and 1,024-value write batches. Today: 1 MiB pages, write batch 256, offset index disabled unless page-index columns are named (`:687-691`).
4. **Refuse non-unique sort keys.** There is no check today (`:152-191`).
5. **Several outputs from one plan.** Today a parent file plus list-unnest children. The release needs `list`, `detail`, `links`, `occurrences`, `recoveries`, `meetings` and `url_state` with different orders.
6. **SHA-256 and MD5 while writing** (BLAKE3 today), a pinned `created_by` (precedent: `http/ipc.rs:507`), and row-range shards.
7. **Facets** over `List` columns and over non-hidden rows only. `facets.rs` handles scalar columns only.
8. **Fold shape.** See §4.6.

**Inputs (Replace).** `build_joined_export_dataframe` (`pipeline.rs:256-442`) joins field groups of one dataset by occurrence identity. The target feeds the writer from the job's SQL instead.

**Lifecycle shell (Keep for news_lake and the committee explorer).** That is `ExportSpec` with its channel, authority and protection record (`pipeline.rs:73-98`), host custody (`host.rs`) and protected remote stages (`remote.rs`). In the target, `validation.rs` (footer, field IDs, row count, sampled decode) is the part worth lifting.

**Slice reader (Dormant, 474 lines).** It arrived in `c937ef8` and `2ffa105` ("multi-group sorted/filtered/folded/faceted ExportSpec", ss-6gwu, ss-yjvy) to read a child row range through the PageIndex. Its only caller is a test (`tests/exports.rs:1793`). **Proposed use:** the engine-side oracle for plan C3's "hyparquet page reads on the output". It can show that the offset and column index of `detail`, `links` and `occurrences` select the right page before the canary runs.

##### 2.3 Lake appends (C2) and table properties

**`storage::append` (`storage.rs:858-929`).** Commits a fast append through `GuardedCatalog`. iceberg-rust 0.10.1's snapshot actions send `UuidMatch` and `RefSnapshotIdMatch` (`~/.cargo/registry/.../iceberg-0.10.1/src/transaction/snapshot.rs:519-522`), so A §8.1's commit requirements are already met. On a transient error it reloads, and accepts the commit if its own files landed in the next sequence number (`:913-925`). A real conflict (a lost race with Basin maintenance) returns immediately (`:876-878`). A §8.1's reload, recompute-work-list, re-append loop is missing, and it needs the job to re-plan, so it belongs to the job runner, not `append`.

**`write_batches_inner` (`storage.rs:359-659`).** A bounded rolling writer with partition fan-out. It needs:

- the remote caps removed (`:376-390`: files capped at 2 MiB, row groups at 2,048 rows and 2 MiB). They came in `b4b827d`, whose message records no measurement; M1.3 decides;
- D §6 row groups (131,072 rows for `captures`, 65,536 for the other tables);
- a 128 MB target file size.

**Table properties.** `storage.rs:132-140` sets `gc.enabled=false` and `write.metadata.delete-after-commit.enabled=false` on **every table at creation** (used at `catalog.rs:398`, `storage/tables.rs:275,340,769`). D §6 wants both `true`, plus `write.target-file-size-bytes` and zstd level 3, neither of which is set. `catalog.rs:1134` and `:1163` flip `gc.enabled` true then false again, but only inside `replace_baseline_snapshot`. Its only caller is lifecycle baseline compaction (`catalog.rs:857,950`; `retention/compaction.rs:156`), not every commit.

**Table creation.** Data tables are created as per-version candidates whose metadata the engine writes and registers (`storage/tables.rs`, `storage.rs` `register_candidate`). The target has five long-lived tables created once with D §6 properties and appended to forever, and there is no generic "create if absent with properties" job.

##### 2.4 Reads (C1) and pins

**Provider (`query.rs:29-160`).** `query::table` and `query::occurrences` wrap an Iceberg table as a DataFusion `TableProvider` with file-level pruning, but stream files through one partition (`NativePartition`; "Streams captured files sequentially", `:94`). That limits scan parallelism for the model's wide joins.

Two options, to be decided by measurement in M2:

- add partitioning to the existing provider;
- adopt a maintained provider. `iceberg-datafusion` is not in `Cargo.lock` today.

**Pins (`storage/pinned.rs`).** `open_pin` loads a table from an exact metadata file and BLAKE3 digest, and refuses when the metadata's current snapshot differs from the pin (`:111-118`). A §10.3.1 pins snapshot IDs and must keep reading them after Basin compaction has moved the head. That needs a scan at a snapshot ID, not equality with the current snapshot.

**Context and resources.** `budget.rs:86-120` already gives one `SessionContext` with `FairSpillPool` (half of `memory_bytes`), a scratch path, a batch size and `target_partitions = compute_threads`. That meets C6. `RemoteCatalog` (`storage/remote.rs:180-385`) connects Basin over REST, retries 429 and 5xx on reads, and passes commit requirements through unchanged (`:359-364`).

##### 2.5 Release upload (C5)

`RemoteObjects::upload_file` (`objects.rs:555-636`) streams 8 MiB multipart chunks, create-only, and hashes BLAKE3. In production builds it skips readback after upload. In test builds it re-reads every upload (`object_io.rs:258-262`): a test/production divergence. On a conflict it re-reads the whole object (`verify_if_present`, `object_io.rs:263-268`).

A §10.3.4 and §13.5 want instead one create-only PUT with `Content-MD5`, and on a 412 one HEAD comparing the ETag to the expected MD5. `create_bytes_by_key` (`objects.rs:534-541`, single `write_with … if_not_exists`) is the right base. It needs `Content-MD5` added and the release-size limit lifted (it is capped at `max_metadata_bytes`, `:491-495`).

**Keep unchanged (plan §8):**

- the scope check (`objects.rs:931-937`, scope `key()`);
- `if_not_exists` on every write (`:537`, `:582`);
- the expiring, digest-verified exact-key delete actor (`:168-218`).

##### 2.6 Lifecycle-only families after the switch

These were measured against the consumer list in the preface. After CT's incremental catalog goes, nothing calls them.

**Backfill (6,140 src, 7,105 tests).**

- **Where it is used today:** only CT's `raw_storage.py`, `native_features.py`, `catalog_raw_updates.py` and `raw_catalog.py` call it.
- **Coupling:** it reaches `pipeline.rs`, `release_check.rs`, `verification.rs`, the retention inventory and `corrections/records.rs` (14 `backfill::` references outside the module).
- **Measured:**
  - `engine/backfill/**`: 8,130 lines, of which 5,538 are source and 2,592 tests;
  - `engine/intake.rs`: 602;
  - integration tests: 4,513 (`backfill.rs`, `backfill_dependencies.rs`, `completed_backfill_plan.rs`, `continuous_backfill*.rs`, `cutover_admissions.rs`, `scalar_bindings.rs`, `scalar_dependency_reads.rs`).

**Schema evolution (806 + 766), dependency corrections (662 + 886), evidence updates (1,014 + 1,599).** CT-only callers today. Keep `src/evidence.rs` (139 lines): the export pipeline imports its constants (`pipeline.rs:28`).

**Comparison is not cut.** `/changes` is served by `engine/comparison.rs:197`, and news_lake's `changes_batches` uses it.

**Retention inventory, owners and removal (Unclear).** Today's consumer of `/retention/inspect` and `/retention/removal/plan` is CT's `native_capacity.py`, deleted at the switch. But news_lake's `compact_lifecycle` goes through `retention/compaction.rs:125-170`, which calls `reference_objects` (`retention/inventory.rs:49`) and `plan_succession_checkpoint` (history, `:136-138`).

To decide, we need: which inventory and owner records `compact_lifecycle` and ordinary Build and Update protections read, and whether news_lake can live with "selected release plus reader pins" reclaim (the greenfield review's §4 proposal).

`Strict<T>` (plan §8 keep list) lives in `retention/inventory/strict.rs`. Its only users are in `inventory/expand.rs:696-795`, so it lives or goes with the inventory. The target has no job for it; `deny_unknown_fields` (128 sites) already gives strict decoding for job specs.

**`BackendCapability` (`engine.rs:211-231`).** It splits source field groups from local-only field groups. The target has no field groups, so it stays only while the lifecycle store does.

##### 2.7 Interface (C7)

`main.rs` has about 70 subcommands, all lifecycle operations (`:120-520`). `http.rs:44-192` registers 77 routes. About 10 are aliases: `/run-plans` and `/runs/plan` for `/plan`; `/runs` and `/runs/run` for `/run`; three spellings each of continuous-backfill and its plan; `/exports` beside `/exports/run`; `/compact` beside `/compactions/run`.

There is no declarative job spec with inputs, SQL, outputs and export settings. What can be lifted:

- clap;
- `serde(deny_unknown_fields)`;
- structured refusals with stable codes (`error.rs`);
- JSON results on stdout (`main.rs:1339-1360`).

##### 2.8 Dormant code

- **`examples/r2_catalog_probe.rs` (307), `r2_objects_probe.rs` (182), `r2_candidate_probe.rs` (687).** They came in `0ee2823`, `559f4aa` and `07fd332` (2026-10-10), "qualify maintained R2 and Basin catalog adapters" and "qualify create-only R2 objects". **Use:** the seed of the M1 Basin harness (plan §5.1). They already open Basin over REST and make create-only writes against the real provider.
- **`examples/comments_codec.rs`, `comments_scan.rs` (176).** From `14b83f1`, "diagnose Comments batch memory and encoding", for the old 10M-Comments workload. No target use.
- **`examples/news_poll_scale.rs` (224).** From `1849990`, the succession-archive growth probe. It goes with history.
- **`profile_tests.rs` (497).** Manual profiling, excluded from CI. No target use.
- **Export slice reader.** See §2.2.
- **`engine/aggregation/udaf.rs` `FirstValueBy` and `CollectDistinctWithProvenance` (595).** Live for the committee explorer. For the target, DataFusion's `first_value(x ORDER BY …)` already expresses "first in saved-file order" (D §7.5), so measure before reusing.

#### 3. Repurpose opportunities

Ranked by target work saved. Savings are *est.* lines of new Rust avoided.

1. **Export writer core → C3.** Streaming writer, footer bound, child tables, facets, fold, single settings builder (`pipeline.rs:445-702`, `child.rs`, `facets.rs`, `parent.rs`, `export.rs:658-697`). Saves *est.* 1,500-2,000 lines. Changes: the eight items in §2.2.
2. **Storage write path → C2.** `write_batches_inner` (`storage.rs:359-659`), `append` (`:858-929`), `batch.rs`. Saves *est.* 600-800 lines (rolling writer, partition fan-out, bounded buffers, unknown-commit reconciliation). Changes: drop the remote caps, add D §6 settings, add the work-list conflict loop in the job runner.
3. **Reads → C1.** `query.rs` provider, `pinned.rs`, `RemoteCatalog` and `budget.rs`. Saves *est.* 800-1,000 lines. Changes: scan at a pinned snapshot ID; multi-partition scans, or a maintained provider (measure in M2).
4. **Release upload → C5.** Remote scope and create-only primitives (`objects.rs`), with `create_bytes_by_key` as the upload base. Saves *est.* 300 lines. Changes: Content-MD5, single PUT at release size, 412 → HEAD of ETag, no BLAKE3 readback.
5. **CC kernel → C4.** `DisjointSet` and the budgeted streaming scan (`topology.rs:31-280`). Saves *est.* 150-250 lines. Changes: u32 IDs, node cap, a plain relation in and out, no ID formula.
6. **CLI chassis → C7.** clap, `deny_unknown_fields`, `error.rs` refusal codes, JSON output (`main.rs:1339`). Saves *est.* 300 lines.
7. **Volatile-function refusal → determinism.** `sql_validation.rs:169-220` refuses clock and random functions, exactly A §10.2's "no timestamps or run-specific values". Saves *est.* 50 lines and one class of nondeterminism bug.
8. **Export output checks → C3.** `export/validation.rs`: footer, field identity, row count, sampled decode. Saves *est.* 200 lines.
9. **Slice reader → C3 evidence.** `pipeline/slice.rs` as the engine-side PageIndex oracle (§2.2). Saves *est.* 200 lines of test harness.
10. **Partition transforms → readings partitions.** Identity partitioning in `partitioning.rs` and `tables::validate_partition_spec` (`storage.rs:393`) give D §6.2 and §6.3 their `(parser, parser_version)` and `catalog_version` partitions with no new code.

#### 4. Rule conflicts (code vs spec)

Either side may be right. Each item names both.

1. **Table properties.** `gc.enabled=false` and `delete-after-commit=false` at creation (`storage.rs:132-140`) vs D §6 `true` and `true`. The engine's choice protects lifecycle snapshots its own retention planner tracks. The target hands expiration to Basin.
2. **Writer settings.** 2 MiB files and ≤2,048-row groups on remote (`storage.rs:376-390`) vs D §6's 128 MB files and 131,072 / 65,536-row groups. Plan M1.3 is the decider.
3. **Row-group flushing.** The export flushes on bytes as well as rows (`pipeline.rs:605-616`, `:681`; `child.rs:357-363`) vs D §8.1 "flushed on row count only" and A §10.2.
4. **No sort-key uniqueness.** The engine sorts with no uniqueness refusal (`pipeline.rs:152-191`) vs A §10.2 "every sort key MUST be unique, or the export refuses".
5. **Digests.** BLAKE3 everywhere (`export.rs:658-697`, `objects.rs:511,588`, `pinned.rs:97`) vs SHA-256 and MD5 in the manifest (D §8.1) and Content-MD5 on upload (A §10.3.4). MD5 does not appear anywhere in `src/`.
6. **Fold shape.** `List<Struct<field: Utf8, values: List<Utf8>>>` (`src/export.rs:36-38`) vs D §4 `list<struct<field, value>>`, one value per element with the field repeated.
7. **Multipart upload and readback.** `objects.rs:577-584` (8 MiB parts), full re-read on conflict (`object_io.rs:263-268`), and a re-read after every upload in test builds only (`:258-262`) vs A §7.1 / §10.3.4 (single PUT, no multipart, one HEAD of the ETag) and A §13 (no test-only paths). The raw-body rule in A §7.1 binds Python writers, but the release upload rule binds whoever publishes.
8. **`document_id` in the engine.** `connected_components.rs:23-36` builds compact JSON with `serde_json::to_vec(&("bodies", list))` and hashes it with the hand-written SHA-256. The serialization matches D §3 and §7.5, but A §13 forbids the formula in the engine. There are two semantic gaps:
   - the engine uses every body token in the component, while D §7.5 uses only the logical body keys of **real files**;
   - with no bodies and no row keys, the engine hashes `"{file}:{row}"` physical locations (`topology.rs:252-256`), an ID that changes whenever files are rewritten. D §7.5 has no such case.
9. **CC limits.** `usize` parents and a byte-budget refusal (`topology.rs:31-75, 224-232`) vs A §13.4's 32-bit IDs and node-count refusal.
10. **Pins.** Current snapshot must equal the pin (`pinned.rs:111-118`) vs reading pinned snapshots after maintenance moved the head (A §10.3.1, §8.7).
11. **Dropped requirements.** In detached mode `GuardedCatalog::update_table` drops the commit requirements (`catalog.rs:1347-1356`) and relies on the SQL catalog's compare-and-swap. A §8.1 says every commit MUST carry its requirements. Today this affects lifecycle baseline compaction only, but on REST it removes the guard.
12. **The lifecycle store itself vs A §13 MUST NOT.** A lifecycle store that duplicates Iceberg bookkeeping (`catalog.rs`), table maintenance (`engine/compaction.rs`, `retention/compaction.rs`) and resume machinery (phases, restore points, recovery receipts) all exist. Plan §7 keeps news_lake on them. The engine cannot conform to A §13 while news_lake stays on DocSpec. Either A §13 needs a "parked consumer" carve-out or news_lake has to move first.
13. **Test-only production paths.**
    - `test_hooks.rs` is always compiled (`engine.rs:84-85`);
    - `stop_after` threads a fault-injection argument through 56 production call sites;
    - 167 test-util cfg lines in 46 files, and 60 `not(feature = "test-util")` production-only branches;

    All of this is against A §13 and §15.7. Plan B11's ratchet covers only CT's `PYTEST_CURRENT_TEST`.
14. **Application identifiers in the engine.** The consumer dataset-name prefixes `raw-`, `catalog-`, `obs-` and `source-observations-` appear in 4 files (§1 row) vs A §15.7.
15. **Interface size.** 77 routes and about 70 subcommands vs A §13.7's thin job-spec CLI.

#### 5. Capabilities missing (build from scratch)

1. **C1 job spec inputs.** Register Basin tables at pinned snapshot IDs, Parquet files and registry files in one context.
2. **C2 conflict loop.** Reload, recompute the work list, re-append only missing rows, at most three retries.
3. **C3 pieces:**
   - per-column encodings and dictionary toggles;
   - `data_page_row_count_limit`;
   - re-batching to a pinned write batch;
   - unique-key refusal;
   - several outputs per plan;
   - SHA-256 and MD5 while writing (`sha2` 0.10.9 / 0.11.0 and `md-5` 0.10.6 / 0.11.0 are already transitive in `Cargo.lock`);
   - pinned `created_by`;
   - row-range shards;
   - the release manifest (`files[]` with sha256, md5, size, rows, row_range, shard);
   - **byte-determinism tests.** None exist: `tests/exports.rs` and `src/engine/export/tests.rs` contain no determinism or byte-equality test.
4. **C4.** Dense u32 IDs, a node cap, and a generic relation interface.
5. **C5.** Single-PUT upload with Content-MD5; ETag check on 412.
6. **C7.** The declarative job spec and its CLI.
7. **C8 URL functions: none exist.** No SQL URL function, no percent-decoding, no RFC 3986 resolution. `url` 2.5.8 is transitive in `Cargo.lock`, but it implements the WHATWG URL Standard, which differs from RFC 3986 §5 on backslashes and special-scheme normalization, so the RFC 3986 §5.4 vectors must decide whether it can be used.
8. **Compact-JSON encoding in SQL (a spec gap).** `source_id` is the SHA-256 of the compact JSON of `[logical body key, filename, source_url]` (D §3, §7.4). Filenames and URLs need escaping (`"`, `\`, U+0000-U+001F). DataFusion 53 core has `sha256` but no JSON-array encoder, and no `datafusion-functions-json` is in the lockfile. A §13.8 lists only URL functions. Either add a generic compact-JSON scalar function to the engine (generic, not policy) or compute `source_id` in a producer. Byte parity with `bipartite.py:165` depends on this choice.
9. **Long-lived lake table creation** with D §6 properties (§2.3).
10. **Facet counts** over list columns and filtered rows, written into the manifest.

#### 6. Delete-table corrections (docspec-rs row)

**The plan's numbers reproduce exactly.** These are the git-tracked file lines of the original WS9 table (`git show 0e83c71e:docs/plans/simplification-plan-20261024.md`, WS9 steps 2, 4, 5, 7, 8, 9):

| Item | Plan | Measured |
|---|---:|---:|
| Retirement planners (src + unit tests) | 5,547 | 5,547 |
| Restore (`src/restore*`, `engine/restore*`) | 3,042 | 3,042 |
| Dagster adapter | 1,583 | 1,583 |
| Provider suites | 3,792 | 3,792 |
| `cli_args.rs` | 203 | 203 |
| `sha256.rs` | 114 | 114 |
| Date transforms (`partitioning.rs:94-169`, `:335-360`) | 102 | 102 |
| **Certain total** | **14,383** | **14,383** |
| Succession (`engine/history`) | up to 2,101 | 2,101 |

**What the plan misses inside its own items.** Measured:

| Missed | Lines |
|---|---:|
| Retirement integration tests (`availability_retirement`, `compaction_retirement*`, `grant_retirement_transport`, `operation_retirement*`, `phase_retirement*`) | 3,189 |
| Retirement HTTP handlers (`http/retention.rs`, less the inspect and plan handlers if kept) | up to 389 |
| Restore integration tests (`tests/restore.rs`, `restore_catalog.rs`) | 1,200 |
| Succession integration test `tests/succession.rs` | 566 |
| **Corrected plan items** | **≈ 19,727 certain** (14,383 + 3,189 + 1,200 + up to 389 + about 566 from the history conditional made exact) |

Succession also has a coupling the plan does not name: history is not standalone. `compact_lifecycle`, which news_lake uses, calls `plan_succession_checkpoint` (`retention/compaction.rs:136-138`). History can go only after lifecycle compaction stops depending on it.

**Families the plan does not list at all.** These have no consumer once CT's DocSpec callers are gone. Consumers were checked against news_lake and the committee explorer.

| Family | Lines | Note |
|---|---:|---|
| Backfill and continuous backfill, with intake fences | 13,245 | 8,130 + 602 + 4,513; coupled, measure at cut |
| Schema evolution | 1,572 | |
| Dependency corrections | 1,548 | |
| Evidence-update operation | 2,613 | |
| CC lifecycle wrapper | *est.* 1,565 src | plus unsplit tests |
| `test_hooks.rs` | 179 | plus 56 `stop_after` sites at cut |
| HTTP alias routes | ≈ 10 | |
| C0 deferred commits and dataset predicates | *est.* 133 | |
| **Subtotal** | **≈ 20,855** | *est.* items included |

**Conditional (Unclear).**

- **Retention inventory, owners, removal and `storage/removal.rs`.** 7,080 src (6,525 + 555) and 7,342 tests (5,739 + 1,603), if news_lake's lifecycle compaction is reworked.
- **The aggregation UDAFs.** 2,112 lines, if the committee explorer stops using DocSpec.

**Do not cut.** `engine/comparison.rs`: news_lake's `/changes` uses it. The plan does not list it, correctly.

**Keep-list corrections (plan §8):**

- **ConnectedComponents.** Only the kernel (*est.* 414 lines) serves the target. The rest (*est.* 1,565 plus `sha256.rs`) is a Replace, and it carries the `document_id` formula that A §13 forbids.
- **`Strict<T>`.** It is retention-inventory code. It survives only if the inventory does.
- **`BackendCapability`.** Lifecycle-only.
- **Remote scope, create-only writes and the delete actor.** Keep. The upload path beside them uses multipart and BLAKE3 readback, which the target forbids for releases.

**`catalog.rs:1163` correction (plan C0).** The plan says the engine resets `gc.enabled=false` "on every commit". It does so on every lifecycle baseline compaction (`catalog.rs:950` → `:1163`). The property that matters is set to `false` at the creation of every table (`storage.rs:132-140`), so C0 must change `table_properties()`, not only `:1163`.


## 5. Cross-cutting

### 5.1 Where today's code implements a rule the specs define differently

Either side may be right; each needs a spec edit or an owner decision. Grouped by layer (CR = raw writer, CM = readings and model, CS = releases, site and engine) and ranked within each group by impact on raw data, then users. The package section holds the evidence.

**Raw writer and receipts (A §7, D §5)**

| # | Today's code | Spec | Evidence |
|---|---|---|---|
| CR1 | Every response header is recorded (twice), with no allowlist and no cookie filter | Eight allowlisted headers; no cookies or authorization (A §7.2, §14; D §5.2) | `transport/http.py:92-122`; `source_capture.py:68-70,104-111`; `source-fetch/main.rs:163-176`; `raw_archive.py:115-116` (4.2, 4.4) |
| CR2 | API keys travel in query strings; capture refuses such URLs, and the B16 fetchers strip them by hand | No rule for credentials in URLs; B16 sends these fetches through the raw writer | `transport/congress.py:9`; `archive_links.py:19,56-57`; `committees.py:23-29` (4.2; 6.2 K1) |
| CR3 | Bodies over 64 MiB are cut off (cap in five places) | Nothing is cut off (A §7.1) | `rust_fetch.py:134`; `source_capture.py:42`; `raw_sync.py:215`; `cli/raw_sync.py:186`; `capture-raw-sources.yml:343,346` (4.2, 4.3) |
| CR4 | A 412 triggers a download and comparison | A 412 is `unchanged`, no HEAD, no comparison (A §7.1) | `raw_sync.py:412-415`; `body_files.py:137-148`; `corpus_recovery/transfer.py:40-45,129-134` (4.1, 4.2, 4.4) |
| CR5 | Every body is gzipped to `<sha>.gz`, PDFs and ZIPs included | Bare `<sha>`; `Content-Encoding: gzip` only for compressible types (A §7.1) | `body_files.py:116-127`; `raw_archive.body_payload`; `transfer.py:109-120` (4.1, 4.4) |
| CR6 | The physical key is guessed from a format | The suffix is recorded (`stored_suffix`, verification records; D §7.5) | `body_keys.py:50-66`; `catalog-v6.ts:24-48` (4.1, 4.3) |
| CR7 | A body's SHA-256 is taken after transfer decoding | "SHA-256 of the original response bytes" (A §7.1) is ambiguous | `source-fetch/main.rs:177-249` (6.2 K5) |
| CR8 | Archive expansion has limits (64/64/128 MiB, 1,024 members, depth 1), Office stays whole, `rtfd` expands | "Archive members are separate entries"; no limits; ZIP fingerprint assumes members exist | `archive_members.py:17-28`; `raw_archive.py:120-178` (4.1) |
| CR9 | Recovery receipts sit at `receipts/documents/import/<run>`, carry `download_state` and local paths | Date-shaped keys; those fields are forbidden (A §7.2, D §5.2) | `dispatch_corpus_recovery_import.py:187`; `assemble.py:92-94`; `prepare_corpus_recovery_source_records.py:167` (4.4) |
| CR10 | No code writes `prior_access_category` | An unmapped category fails the build (D §7.8) | `git log -S` finds it only in docs (4.4) |

**Readings and the model (D §6–7)**

| # | Today's code | Spec | Evidence |
|---|---|---|---|
| CM1 | IDs: several source triples per capture row (Content-Disposition, final URL, query names, local path); `document_id` bodies exclude HTML and `binary`; filenames percent-decoded | One effective filename per row; real-file bodies incl. HTML; decoding and the `source_url` choice unspecified; A §9.1 claims byte-for-byte ID parity | `index/sources.py:119-145`; `bipartite.py:236-253`; `sources.py:30-35` (4.1 §3.1) |
| CM2 | Sniff falls back to the server's media type | MUST NOT use the media type (A §8.3) | `document_links.py:195-203`; `capture_inspection.py:87-146` (4.1, 4.2) |
| CM3 | Links are resolved and filtered at parse time | Every link as written; the model resolves (D §6.2, §7.2) | `document_links.py:124-160`; `archive_links.py:242-245` (4.2) |
| CM4 | Congress.gov JSON `meetingDocuments` links reach capture; Next.js and JSON-LD links are read | JSON readings carry no links; links come from link elements only | `archive_links.py:102-196`; `page_content.py:8-65` (4.2; 6.2 K9) |
| CM5 | Wrappers known: `web.archive.org`, `webarchive.loc.gov`, LIS t2GPO, `chrome-extension://`, `mailto:`, `ttps://`, concatenated URLs | Proofpoint, rs6.net, exit.asp, `web.archive.org`, `webharvest.gov` (one form) | `archive_links.py:20-23,66-99`; `source_aliases.py:7-22`; `webharvest_committee_map.py:26-65` (4.2, 4.4) |
| CM6 | `download`, `download=1`, `download=true` are dropped when grouping endpoints | `download=1` selects a different file and is kept (D §7.2) | `bipartite.py:20-51` (4.1 §3.2) |
| CM7 | Only HTTP 200 counts as success for capture; outcome names differ | `good_fetch` is 200–299; six outcomes (D §5.2, §7.3) | `capture_inspection.py:37-41`; `raw_sync.py:31-33` (4.2) |
| CM8 | House committee codes use `hl` for Intelligence and select committees; joint and commission codes sit in the House table; two-letter codes exist | `'hs' \|\| lower(code)` | `matching/house.py:33-34`; house-naming guide (4.2, 4.4) |
| CM9 | House XML: removed elements dropped (`remove-date`); witness documents grouped; labels from the group description; `meeting-id` = type prefix + event ID | No `remove_date`; grouping ancestors omit `witness-document`; event ID parsing unspecified | `house_documents.py:72-131`; `house_evidence.py:50-116`; `records.py:483` strips only `HMKP` (4.1, 4.2) |
| CM10 | `witness-list` XML is a document | "Witness records" are source records (D §7.3) | `document_evidence.py:209-212` (4.1) |
| CM11 | METS (`metadata/pkg/<id>/mets.xml`) is a source record; error pages recognized at two error URLs | Source-record roots omit METS; no error-URL rule | `index/schemas.py:437-470` (4.1) |
| CM12 | PDFs need `%%EOF` or a readable structure; challenge pages detected by body markers | Any complete 2xx PDF is real; error signs read only title, heading, text size | `capture_inspection.py:77-99` (4.1; 6.2 K14–K15) |
| CM13 | Link context follows redirects and skips feeds and sitemaps; labels also from XML descriptions, paragraphs, headings | `linked_from` matches the endpoint's `url_key` only; keeps `text`, `doc_type`, `add_date` | `document_sources.py:143-229,494-544` (4.1 §3.4) |
| CM14 | Generated probe URLs are not re-scheduled unless independently linked | Every requested URL is rechecked at its family interval (D §7.7) | `capture_url_admission.py:14-27`; `raw_archive.py:244-254` (4.1) |
| CM15 | Recheck by meeting age (7 / 28 / 365 days) | One interval per family (D §7.1, §7.7) | `acquisition/refresh.py:1-17` (4.2) |
| CM16 | Kinds also from House XML type codes, PDF covers and Senate headings | Kinds from filename readings and reviews only | `house_documents.py:42-56`; `document_cover.py:8-9`; `senate_page.py:151-305` (4.1, 4.2) |
| CM17 | Senate meetings come from title/date association; GPO MODS carries event IDs; Congress.gov uses `nochamber` | Senate inventories as a body source; MODS omitted; chamber values unspecified | `acquisition/senate.py:1-20`; `gpo_hearings.py:166`; `meetings.py:43` (4.2) |
| CM18 | `measure_keys` often lack a congress; `member_bioguide_id` is also emitted | `{congress}-{type}-{number}`; two bioguide sources named | house-naming probes (4.4) |
| CM19 | Error and challenge words include "just a moment", "session verification", "rate limit reached", "request not accepted" | Six generic words | `corpus_recovery/html.py:13-16` (4.4) |
| CM20 | `accepted.json` `kind` is the file type | Provenance `recoveries.kind` is a display kind (D §5.3) | `filename_recoveries.py:11` (4.4) |

**Releases, site and engine (A §10–13, D §8)**

| # | Today's code | Spec | Evidence |
|---|---|---|---|
| CS1 | Release prefix is a random uuid4; the manifest carries `published_at`; every upload is read back; a 412 counts as success unchecked | Content-digest release ID; content-only manifest; Content-MD5; 412 → one HEAD (A §10.2–10.3) | `publish_viewer_r2.py:475-482,525-534`; `client.py:162-178,344-348` (4.3) |
| CS2 | Public links use the 64-hex `source_id`; old catalogs are pinned forever | 16-hex link key through `links.parquet`; only live and last-good releases are sure to exist | `publication.ts:31-35,91-105` (4.3) |
| CS3 | Rows decoded as objects; no offset or column index reads | Column-by-column arrays; `useOffsetIndex`, `usePageIndex` (A §11.1) | `catalog-v6.ts:188` (4.3) |
| CS4 | WAF blocks `/receipts/*` and `/indexes/*`; one credential for every job | Everything public; separate tokens (A §11.7, §14) | `apply_r2_edge_rules.py:359-372`; workflows (4.3) |
| CS5 | Date labels "Retrieved …"; recovery labeled by format | A §11.6 labels; D §7.8 display kind | `filename-presentation.ts:455-466,531-533` (4.3) |
| CS6 | Engine pins are optional, binary may come from `PATH`, only a darwin digest | Pinned by revision and digest, checked before storage access (A §12) | `docspec_client/client.py:312-314`; `binary.py:43-45`; `models.py:16-25` (4.4) |
| CS7 | Engine: `gc.enabled=false` at table creation; 2 MiB / 2,048-row remote caps; byte-based row-group flushes; no unique-key refusal; BLAKE3 only; fold `field, values[]`; multipart + readback; `document_id` in the engine; `usize` CC with byte budget; pins require current snapshot; requirements dropped in detached mode; lifecycle store; test-only paths; consumer dataset names | D §6, §4, §8.1; A §8.1, §10.2, §10.3.1, §13, §15.7 | 4.5 §4 (15 items) |

**Spec issues found while inventorying** (not code conflicts): A §11.5 would open unpacked archived HTML in the site's origin (4.3 §4.10); A §10.3.3 does not fix the release-ID serialization (4.3); D §7.4 does not say which URL is `source_url` or whether the last segment is decoded (4.1 §3.1); `source_id` needs compact JSON in SQL, which A §13.8 does not list (4.5 §5.8).

### 5.2 Capabilities the target needs that exist nowhere today

**Raw writer**
- Header allowlist and cookie redaction; credential stripping for recorded URLs (4.2).
- Hashing (SHA-256, MD5) and sniffing while streaming in the fetcher (4.4).
- Streaming Zyte bodies, or an acknowledged size ceiling (4.2).
- Verification-record writer for `provenance/verification/` (B13, weekly check).
- Provenance writer for `provenance/<kind>/<ts>.jsonl` with supersession by `id`, including `recoveries`, `url_variants` and `reviews` (4.4).
- A writer of `prior_access_category` for corpus_recovery imports, or a registry rule for its absence (4.4).
- P B7 code identity (git tree hash + `uv.lock` digest, refusing uncommitted code) on recovery-import lines (4.4).
- The weekly maintenance job: LIST joined to recorded keys, re-hash of bodies without a creating line, 25-body sample, orphan report, release retention, shared concurrency group (4.3).

**Lake**
- The `captures` ingest: date-prefix listing, anti-join on receipt keys, older-shape mapping, line-only rows.
- Generic HTML reading facts: `title`, `heading`, `text_bytes`, `link_count`, `link_text_bytes`, `content_date`; a generic `group_path` (4.2).
- The `fingerprint` producer: NFKC normalized-text digest; ZIP member-hash digest from `captures`.
- The `filename_readings` producer around house-naming (4.4).
- Committee and meeting producers with completion rows; `meeting_ref` from Congress.gov URLs (4.2).
- Long-lived Iceberg table creation with D §6 properties; the work-list conflict loop (4.5).

**Model**
- `url_key`: unwrap registry, strip-list, `www.`/port/trailing-slash/percent normalization. No code exists in any package (4.2).
- RFC 3986 reference resolution and percent-decoding as SQL functions (C8); compact JSON in SQL for `source_id` (4.5).
- ConnectedComponents over 32-bit IDs with a node cap (4.5).
- The 13 registries as versioned files with sample tests; today seeds exist for about 5 (§2 item 20). A committee-code registry (`hs`, `hl`, joint, two-letter codes) does not exist in either direction (4.4).
- Model profile, completeness gate, input identity (D §7.1, §8.3).
- **Golden vectors for `source_id` and `document_id`: none exist today** (4.1 §3.1).

**Releases and site**
- Multi-output deterministic export with per-column settings, row-count flushes, unique-key refusal, SHA-256 and MD5, shards, facet counts over list columns and non-hidden rows, the manifest; byte-determinism tests (none exist) (4.5).
- Content-digest release ID, `inputs/<digest>.json`, `status.json`, flip with `previous_release_id` (4.3).
- Reader: column decoding in a worker, offset- and page-index reads, link-key routing with a not-found notice, hidden documents, `meetings`, shards, hearing filter (4.3).
- Node canary with a heap budget; CI contract test with a pinned headless browser (Playwright is not a dependency) (4.3).

### 5.3 Engine-first duplicates: Python doing what docspec-rs does or should do

| Python code | What it duplicates | Fate |
|---|---|---|
| The whole Python catalog: `BipartiteUnionFind` (`index/bipartite.py:99-141`), SQLite working state (`catalog_staging.py`), joins and grouping across `index/*` and `catalog_*` | the model SQL plus engine CC (A §9, §13.4) | Replace |
| `compute_document_id` four times: `bipartite.py:197-205`, the streaming SQLite variant `:295-309`, `connected_components.rs:23-36`, and `native_features.py:1036-1177` (a Python copy of the engine's CC transform, used when the engine lacks the variant) | one formula in the model SQL | Replace; golden vectors from the Python original |
| `raw_storage._merge_states` and `docspec_client.apply_update_merge_spec` (`specs.py:476-692`) | the engine's update merge | Replace with the raw index |
| `document_links.http_url` + `remove_dot_segments` (`:51-94`) | RFC 3986 resolution, which A §13.8 assigns to the engine | keep only as a fetch-time guard and as a source of conformance vectors |
| `acquisition/recovery_queue.completed_from_tables` | table scans in Python | Replace |
| `filename_exports.compute_facet_entries` (duplicates `docspec_client.facet_summary`), `compute_browse_ranges` (recomputes Parquet statistics), the v6 preparer, `compact_readings` (Basin's job) | engine export and Basin compaction | Replace / F0 only |
| `ConditionalManifestPublisher` uploads release files from Python | the engine's create-only remote boundary (A §13.5, P §8) | decide which side uploads |
| `docspec_client` pure-Python BLAKE3; the client's Python merge when the engine lacks `merge` (`client.py:734-752`) | engine digests and merges | Replace |
| `corpus_recovery` `index_rows`, `preservation.py` | capture rows and selection comparison | Replace (ingest replaces it) |
| `news_lake/storage/docspec/incremental.py` (1,120), the pyiceberg stack (1,624) | incremental derivation and Iceberg writes | parked (P §7) |
| `tests/e2e/harness/parquet_oracle.verify_unique_keys` | uniqueness in a Python set | if reused, do it in the engine or pyarrow |

### 5.4 Dormant code and proposed uses

| Code | Lines | Why it exists (history) | Proposed target use |
|---|---:|---|---|
| `retention/catalog/`, `raw/`, `review/` facades | 112 | `e4b3216b` decomposition; zero importers | the package layout for what survives: `raw/` for the raw writer, `review/` for the provenance review writer (4.1 §7) |
| `retention/docspec_host.py` | 20 | shim after `bdc40971`; tests only | none; point tests at `docspec_client` |
| `acquisition/documents.py` + `transport/document_probe.py` | 112 | `43f112ef` bounded landing-page probe | labeling aid for P §5.3's sample; pre-check before each B14 re-fetch; its fixtures seed the file-shape registry (4.2) |
| house-naming `archive/tools/` | 1,502 | `aa3bd2aa` moved the frozen-vs-current filename metadata diff tools aside | the review step before the model profile moves to a new `catalog_version` (4.4) |
| house-naming `bill_codes.py` | 49 | GovInfo bill types | validate `measure_keys` types; split `BILLS-…` stems for `gpo_package_id` (4.4) |
| `scripts/incremental_boundary_proof.py` | 261 + 55 | ct-l5q1 spike; its test checks the fixture only | none; delete with row 1 (4.4) |
| `viewer_publication/compact_readings.py`, `compact_reviews.py` | 366 + 332 | `f2fea711` | `deduplicate_reading_table`'s keep-latest-by-PK logic as a fixture helper for D §10 invariant 1 (4.3) |
| docspec-rs `export/pipeline/slice.rs` | 474 | ss-6gwu, ss-yjvy child-range reader; a test is its only caller | engine-side oracle for C3's page reads before the canary (4.5) |
| docspec-rs `examples/r2_*_probe.rs` | 1,176 | `0ee2823`, `559f4aa`, `07fd332`: R2 and Basin qualification | seed of the M1 Basin harness (4.5) |
| docspec-rs `profile_tests.rs`, Comments and news-poll probes | 897 | old workloads | none |
| The `streamed-recovery` CLI route | — | `e4b3216b`; unreachable, raises `TypeError` | fix it for B14 or delete it (4.2) |

### 5.5 Unclear: what would settle each

- **docspec-rs retention inventory, owners and removal** (7,080 + 7,342): which records news_lake's `compact_lifecycle` reads (4.5).
- **docspec-rs `storage/remote/namespaces.rs`** (167 + 251): whether anything but the lifecycle store uses namespace generations (4.5).
- **Committee explorer** (site 7,970 + 1,373; weekly retention 2,154; `publish-explorer.yml`; `update-data.yml`): survive beside the archive, or be absorbed by `meetings.parquet`? P §7 says re-scope first.
- **The 86 published assistant reviews**: migrate to provenance `reviews` (`kind_override` on body link keys) or drop (4.3 §2.11, 4.1 §5).
- **hyparquet 1.31.2**: does it expose `useOffsetIndex` and `usePageIndex`? `node_modules` is absent in the worktree (4.3).
- **Who uploads release files**: Python or the engine (4.3).
- **P B12**: do the old capture path's raw writes depend on the wrong `stored_sha256` index rows? If not, drop B12 (6.4 S8).
- **Do Congress.gov or GovInfo response bodies echo the request URL with its API key?** Bodies are stored whole and public (6.2 K1).
- **How many documents are linked only from Congress.gov JSON, Next.js data or JSON-LD?** Measure before the switch (5.1 CM4).
- **How many of today's 1.68M source files come from Content-Disposition, final-URL or query-parameter names?** Measure before E3/E4 (5.1 CM1).


## 6. Lessons

Today's system was built by trial and error, much of it by AI. It holds hard-won knowledge and real over-engineering. This section separates the two.

**Sources.** `git log` in the worktree (1,065 commits; the 108 fix, repair, restore, rollback, regression and revert subjects are listed in `fork-lessons-mistakes/fixcommits.txt`), file churn, `docs/reviews/`, `docs/adr/`, `docs/plans/`, `docs/experiments/`, `.tickets/`, the code and its tests, and docspec-rs history.

**Evidence rule.** Closed tickets and closure notes were used only as leads, never as evidence; an October audit found they often overstate what landed. Every lesson is confirmed by a commit SHA or a file:line. Items marked "(audit)" quote a figure measured by the 2026-10-24 ticket audit that was not re-measured here.

**Ranking.** Impact on the archive's raw data first, then on users, then on effort. The index below gives the final order across all sources; the detail follows, with stable IDs (M = mistake, K = knowledge, O = over-engineering, S = the same pattern in the specs).

### 6.0 Ranked index

**Mistakes not to repeat**

| Rank | Lesson | Do the specs prevent it? | ID |
|---:|---|---|---|
| 1 | Receipts are a permanent public log, and the writer copies everything into them: all headers (cookies included), local file paths, API keys in URLs | Mostly (A §7.2, §14, D §5.2). **Gap:** no rule for credentials in URLs; decide about older receipts before the bucket lock | M1 |
| 2 | Raw deletion and overwrite were reachable by default (`delete_gzip`, `put(immutable=False)`, "unknown means reclaimable") | Largely (lock, P B3, A §10.3.7). **Gap:** B13 must state "no delete"; a "no Python path deletes raw" test | M2 |
| 3 | Production ran different code from tests and skipped verification exactly on raw data (local-file substitutions, self-verification, 75 test-only branches, engine fast paths by dataset name) | A §13, §15.7. **Gap:** B11 covers only `PYTEST_CURRENT_TEST`; misses `source_capture_inputs.py:61-74` and the engine | M3 |
| 4 | The engine pin was checked against its own descriptor, and is still only half pinned | A §12. **Gap:** a Linux digest in the one application pin | M4 |
| 5 | Human recovery decisions lived in one overwritable JSON file under a derived prefix | Yes (A §7.3, D §5.3, P B8); two sources of truth remain (S3) | M5 |
| 6 | A derived index dropped facts (status, mode, bodiless lines), then became the source of truth | Yes (D §6.1, A §8.2, P D1) | M6 |
| 7 | A rule change rewrote the raw index in place | Yes (D §7.1, A §4.2) | M7 |
| 8 | A space optimization replaced a raw digest with a boolean, and code invented the missing value; tests asserted the bug | Yes (D §6.1, §10 inv. 2, A §7.4). **Gap:** say `stored_md5` is the sent Content-MD5, never derived | M8 |
| 9 | A fixed 64 MiB cap cut off 201 bodies, because bodies were buffered in memory | Yes (A §7.1, P B2, B14) | M9 |
| 10 | A wiring commit shipped a CLI route that cannot run (`streamed-recovery` raises `TypeError`), on the cut-off recovery path | No. **Fix:** every job command gets a smoke test through its real entry point | M18 |
| 11 | The physical body key was guessed at read time, so links pointed at objects that do not exist | Yes (D §5.2, §7.5, §10 inv. 10) | M10 |
| 12 | Tests agreed with themselves (invented engine schemas, a WAF simulator stricter than the deployed rule, tests that asserted a digest bug) | Partly (A §15.5). **Gap:** callers test against the real engine result | M11 |
| 13 | A meeting-ID parser handled one of three House prefixes, because its fixture was invented | No. **Fix:** D §6.5 parse rule + an S fixture with `HHRG`, `HMKP`, `HMTG` | M17 |
| 14 | Hand-listed code fingerprints went stale after a refactor | For writers (A §7.2, P B7). **Gap:** D §7.1 must define parser versions as digests (S5) | M12 |
| 15 | The reader dropped the live format, and verification aimed at a dead host | Mostly (A §11.4, §10.3.5). **Gap:** canary reads through the shipped origin constant | M13 |
| 16 | Code grew while it was being retired (retention 3,003 → 27,799 lines in 23 days) | Partly (P §2, §3). **Gap:** a CI line budget on packages scheduled for deletion | M14 |
| 17 | Optimization was built before the alternative was measured, on samples too small to show the cost | Yes (A §5, P §3, M1.3) | M15 |
| 18 | Process: tickets written after the work, self-grading, unreviewable bundled commits | Yes (P §3) | M16 |

**Hard-won knowledge to carry forward**

| Rank | Knowledge | Spec status | Target home | ID |
|---:|---|---|---|---|
| 1 | API keys never reach a receipt or a stored URL | **LOST** | raw-writer rule; refusal-matrix test | K1 |
| 2 | Fetch-scope safety: private hosts, credentials, per-hop redirect checks, media excluded | Partly | capture-scope registry; fetcher rule | K2 |
| 3 | Publisher politeness (docs.house.gov blocks bursts; 1.2 s pacing, 60 s after a 403; retry statuses) | Partly | fetcher rules + pacing test | K3 |
| 4 | When to fall back to Zyte and how to record it; 206 or `Content-Range` means incomplete | Partly | fetcher rules; D §5.2 `complete` | K4 |
| 5 | Body identity is the content-decoded entity | Partly | A §7.1 wording | K5 |
| 6 | Archive expansion: `rtfd` expands, Office stays whole, limits, duplicate member names | **LOST** | A §7.2 rule; D §6.2 ZIP fingerprint; S fixture | K6 |
| 7 | `Retry-After` and GovInfo ZIP generation (wait at least 30 s) | Partly | fetcher rule; add `retry-after` to the allowlist | K7 |
| 8 | Recheck by meeting age; failures never become permanent absences | **LOST** (age bands) | recheck-interval registry | K8 |
| 9 | Generated probe URLs are evidence, not a schedule | **LOST** | capture-scope registry or `url_state` rule | K33 |
| 10 | Link discovery outside `<a>`: Congress.gov JSON, Next.js data, JSON-LD, calendar APIs | **LOST** | parser rules; D §7.7 queue | K9 |
| 11 | Crawler traps and form safety (WordPress month calendars, never submit forms) | **LOST** | capture-scope registry exclusions | K10 |
| 12 | Building House meeting-XML addresses (joint and rescheduled hearings) | Partly | B16 fetcher rule; S fixture | K11 |
| 13 | Congress.gov API quirks (112th floor, `nochamber`, XML fallback on 500, 2-day relist overlap, detail endpoint has no congress) | Partly | B16 fetcher rules; D §6.4–6.5 | K12 |
| 14 | Format sniffing learned from bad bodies (binary-preamble PDFs, `rtfd` at `.pdf` URLs, XML without declaration, BOMs) | Partly | `sniff` parser rules and tests | K13 |
| 15 | PDF and image completeness checks | **LOST** | `sniff` records a PDF tail check; D §7.3 | K14 |
| 16 | Challenge and soft-error pages that look like documents (body markers, House 200 error sentence) | Partly | error-words registry + a body-marker list; S fixtures | K15 |
| 17 | Records and error pages recognized by URL (GovInfo METS/MODS/PREMIS, listings, summaries, Congress.gov v3, two error URLs) | Partly | source-record roots (+ METS); API registry; error-URL list | K32 |
| 18 | 29 human-reviewed labels on saved responses | **LOST** | P §5.3 sample; a provenance verdict | K16 |
| 19 | URL wrappers and repairs seen in real links (LIS t2GPO, `chrome-extension://`, `mailto:`, `ttps://`, concatenated URLs, `webarchive.loc.gov`, real Web Harvest forms) | **LOST** (most) | URL-wrapper registry; parser rule | K17 |
| 20 | Filename evidence beyond the URL: Content-Disposition (`filename*` first), query-parameter names, the final URL, legacy paths | **LOST** | header allowlist + D §7.4 rule, or an explicit decision to drop | K29 |
| 21 | How a URL basename is decoded (strict UTF-8, `+` literal, decode once) | **LOST** (unspecified) | D §7.4 rule; golden vectors | K30 |
| 22 | Which HTML elements are links, and safe parsing | Partly | `html`/`xml` parser rules | K18 |
| 23 | House meeting XML specifics (`remove-date`, `witness-document`, description labels, event-ID prefix, witness lists) | **LOST** | `xml` parser rules; D §6.2 grouping list | K19 |
| 24 | Link context follows redirects and never comes from feeds or sitemaps | **LOST** | D §7.10 join rule | K31 |
| 25 | Committee code forms (`hl`, joint, commission, two-letter) | **LOST** (rule wrong) | committee-code registry | K20 |
| 26 | Recovery kinds (eight exact strings) and the recovered copy's timestamp basis | Partly | recovery-kind registry; `timestamp_basis` | K21 |
| 27 | Document kinds from publisher XML type codes and content | **LOST** | D §7.5 facet rule; S fixture | K22 |
| 28 | Recovered filenames for legacy cache names | **LOST** | provenance record via P B8 | K23 |
| 29 | GovInfo and GPO metadata (package IDs, ingest dates, errata, MODS event IDs) | Partly | `meeting_ref` from MODS; `content_date` rule; S fixtures | K24 |
| 30 | Senate site knowledge (listing routes, attachment pages, no event IDs) | Partly | capture-scope and file-shape registries; S fixtures | K25 |
| 31 | Which date on a page is the document's | Partly | `content_date` parser rule | K26 |
| 32 | Classifying recovered HTML content | Partly | S fixtures; P §5.3 strata | K27 |
| 33 | Mirrors and genuine versions (real cases) | Partly | S fixtures | K28 |
| 34 | A version is a digest of code and data (three working examples) | Partly | D §7.1 rule | K34 |

**Over-engineering not to port**

| Rank | Pattern | Reason still holds? | Signal to keep | ID |
|---:|---|---|---|---|
| 1 | Five raw write entry points, each with its own `immutable` flag and different 412 semantics | Needs yes, flag no | one prefix policy checked before I/O (P B3) | O1 |
| 2 | A raw-ingest exclusion gate with quarantine copies | No (no list will exist) | hide through a review, never at intake | O2 |
| 3 | Custody, proof and read-back machinery that duplicates Content-MD5 and ETags | Partly | verify once at the platform boundary; check ETags weekly | O3 |
| 4 | A hand-built raw index with hash-prefix routing and copy-on-write leaves | No | `url_state`; never hash-partition an append-only table | O4 |
| 5 | The engine's lifecycle store with its own retention and GC | Only for parked news_lake | durable per-step commits | O5 |
| 6 | Fault injection and consumer fast paths threaded through production engine code | Crash tests yes, threading no | kill a real process at a real commit boundary | O6 |
| 7 | The Python incremental catalog (≈ 10,600 lines with its adapters) | No | incremental only where per-item work is expensive | O7 |
| 8 | The `document_id` formula in four implementations, including a Python copy of the engine's CC transform | No | one formula in the model SQL, golden vectors from the original | O15 |
| 9 | The publication journal, resume and attempt route, plus a second route | No | a rerun is the resume | O8 |
| 10 | docspec_client fallbacks that change what a request means | No | retry transport errors only | O9 |
| 11 | A Python re-implementation of the engine export | No | its feature list becomes C3's acceptance list | O10 |
| 12 | Shims, a module-class hack, import-time monkeypatching | No | none in code | O11 |
| 13 | Copies and facades left by the decomposition (`index/sources.py` repeats `records.py`; three facades with zero importers) | No | none in code | O16 |
| 14 | Hand-written edge infrastructure (WAF allowlist, whole-phase ruleset PUTs) | No | CORS, cache, CSP, `?filename=` | O12 |
| 15 | Duck typing and swallowed errors as capability negotiation | No | typed interfaces, `deny_unknown_fields` | O13 |
| 16 | Capture doing interpretation and publication | No | capture records facts; the model classifies | O14 |

**The same patterns in the target specs and plan:** S1 the effective-filename rule defined twice; S2 the real-file rule evaluated twice, so the gate checks against itself; S3 recovery facts from two sources with no mismatch rule; S4 two completion mechanisms; S5 versions not defined as digests; S6 `status.json` has no named reader; S7 the keep list keeps two things the specs remove; S8 the plan does work on layers it deletes (B12, B9); S9 derivable or unused `captures` columns; S10 the engine's MUST NOT list conflicts with parked news_lake; S11 A §9.1 promises byte-for-byte ID parity that D's derivations cannot deliver.


### 6.1 Mistakes not to repeat: detail


#### M1. Receipts are an immutable public log, and the writer copies everything into them

**Evidence:**
- `transport/http.py:92-122` (`response_metadata`) records every response header twice, as `response_headers` and as `response_header_items`. It also records `final_url` exactly as fetched.
- The Rust worker does the same (`packages/source-fetch/main.rs:163-176`).
- `retention/raw_archive.py:115-116` puts the whole response dict, plus `links`, into the receipt record.
- Nothing on the main capture path drops `Set-Cookie` or `Authorization`. Only three side scripts filter them: `scripts/webharvest/webharvest_recovery.py:32`, `webharvest_committee_map.py:260` and `webharvest_index_remaining.py:220`. The same policy exists in three places, and not in the one that matters.
- Recovery imports copy local batch rows into receipts. `scripts/corpus_recovery/prepare_corpus_recovery_source_records.py:129` reads `row['body_path']`, and `:167` stores `acquisition=row` in the receipt's evidence.
- The same leak was already fixed once, in `accepted.json`: `742add03` reports "793 of 24,028 rows … evidence fields (body_path with local file paths …)", and adds "The object is also publicly readable, exposing those local paths".
- Congress.gov fetches put the key in the query string (`transport/congress.py:9`: `params={..., "api_key": api_key}`). P B16 routes exactly these fetches through the raw writer.

**Root cause.** "Keep everything" was applied to request metadata as well as to bodies. And there is no single raw-writer boundary where a field allowlist could live.

**Do the specs prevent it?** Mostly:
- A §7.2 and D §5.2 allowlist eight headers, forbid cookies and authorization, and forbid `response_header_items`, provider metadata and local paths in import lines.
- A §14 repeats the header rule.

**Gaps:**
- Neither spec covers credentials in URLs. D §5.2 should require that `requested_url`, `url`, redirect URLs and `prior_attempts[].url` have credential query parameters (`api_key`, `key`, `token`, …) removed before the line is written, as a registry the raw writer checks.
- `recovery_evidence.acquisition` should be an explicit field allowlist, not "mixed".
- **Owner decision before the bucket lock (P B1).** Older receipts may already hold cookies and local paths. Under the lock they become permanent, and `r2.dev` serves every key (A §11.7).

#### M2. Raw deletion and overwrite were reachable by default

**Evidence:**
- **Deleting the canonical body.** `migrate_pdf_bodies_to_uncompressed(delete_gzip=True)` deleted the `.gz` body whenever a `.pdf` copy merely existed, without checking that copy. It was at `retention/raw_storage.py:315,330` at `54a68ac7^`, added in `4ed77e3f` and removed in `54a68ac7`. Its guard was a duck-typed `hasattr(store, 'delete')`.
- **Overwrite by default.** `R2Store.put(..., immutable=False)` (`retention/r2.py:338`) and `LocalStore.put(..., immutable=False)` (`retention/catalog_cache.py:84`) do a plain overwrite for any key outside `indexes/`.
- **Unknown means reclaimable.** The Python retention planner classifies every object it cannot match as reclaimable (`retention/native_capacity.py:495-540`). The engine type it parses says the opposite: "unmatched objects are not authorized for removal" (docspec-rs `src/model/retention.rs:87-93`).

**Root cause.** Safety rested on per-call flags and on callers remembering them. The destructive path was the default, and the protective one was opt-in.

**Do the specs prevent it?** Largely:
- A §7.4: the bucket lock;
- P B3: one refusal matrix before any I/O, then the `immutable` flag is deleted;
- A §10.3.7: only maintenance deletes, and only release prefixes; publish MUST NOT delete.

**Gaps:**
- P B13 should state that the PDF-copy job contains no delete call.
- The ticket audit's guard test, "no Python path can delete under the raw prefixes", is not in P B3 or B11. Add it.

#### M3. Production ran different code from the tests, and skipped verification exactly on raw data

**Evidence in congressional-tech:**
- When more than 512 URLs are requested and the row count matches, `retention/raw_storage.py:654-672` serves raw state from a hard-coded local file, `output/incremental-updates-20261019/adoption-inputs/state.parquet`, and swallows any error (`except Exception: pass`).
- `retention/source_capture_inputs.py:61-74` substitutes `.cache/docspec-catalog/captures-0.parquet` for remote capture batches when its row-group sizes match.
- `retention/catalog_adoption.py:134-137` verifies only in tests. In production it sets `actual = expected`, so the source is checked against itself.
- There are 75 `PYTEST_CURRENT_TEST` branches in 26 modules (`git grep`). They came from the ct-2ukk performance commits `017eb2cc`, `e4b3216b` and `f5e8fe1b` (Oct 23–24).

**Evidence in the engine:**
- In production builds only, release checks skip input verification for datasets named `raw-`, `catalog-`, `obs-` and `source-observations-` (`src/engine/release_check.rs:83-93, 225-231`), via `97373eb` "enable initial-build fast paths for source-observations-*". Test builds always verify.
- 52 `cfg(all(not(test), not(feature = "test-util")))` attributes (my grep; the audit counted 60).
- 57 `stop_after` fault-injection sites outside test files.

**Root cause.** Performance pressure was met by special-casing production, and row-count or row-group equality was treated as identity. The tests could not see either.

**Do the specs prevent it?**
- A §13 forbids "test-only production paths".
- A §15.7 ratchets "no test-only branches in production code".

**Gap:** P B11's ratchet names only `PYTEST_CURRENT_TEST` in CT. Extend it to:
- hard-coded `output/` and `.cache/` paths in production modules;
- `cfg(not(test))` / `not(feature = "test-util")` in the engine. Track C has no item for this beyond C0's predicate removal.

#### M4. The engine pin was checked against itself, and is still only half pinned

**Evidence:**
- Hosted setup accepted any engine whose descriptor matched its own bytes. `54a68ac7`: "a stale but self-consistent artifact passed (the Oct 20-24 failure class)". Hosted capture failed from Oct 21 to Oct 24 (audit).
- The fix compares only the revision (`.github/scripts/setup-native-runtime.py:55-59`). The Linux SHA-256 still comes from the descriptor. `QUALIFIED_DOCSPEC_RUNTIME` pins only a darwin digest (`packages/docspec_client/src/docspec_client/models.py:16-25`).

**Root cause.** A digest supplied by the thing being checked.

**Do the specs prevent it?** A §12: "pinned by revision and digest and MUST be checked before any storage access". **Gap in P:** add the Linux digest to the application pin, and keep that pin in one place.

#### M5. Human decisions lived in one mutable file under a derived prefix

**Evidence:**
- `viewer-publications/recoveries/accepted.json` is a single document replaced with `If-Match` (`packages/corpus_recovery/src/corpus_recovery/mappings.py:14, 44-80`).
- It holds one row per `original_url` (`:20-26`, which raises on a duplicate URL), and baseline rows cannot change (`:30-32`).
- The audit counted 12,431 recoveries that existed nowhere else. They were backed up to `provenance/recoveries/` on 2026-10-24.

**Root cause.** Decisions were treated as publication state. They were written where derived files live, and could be lost on a rewrite.

**Do the specs prevent it?** Yes:
- A §7.3 and D §5.3: append-only provenance, with supersession by `id`;
- P B8: reconcile `accepted.json` with the receipts.

**Gap:** see S3 below. Two sources of recovery truth remain.

#### M6. A derived index dropped facts, then became the source of truth

**Evidence:**
- `CAPTURE_SCHEMA` (`retention/raw_schemas.py:11-33`) has no `mode`, `outcome` or `requested_url`, and no recovery columns.
- It has rows only for `captures[]` entries, so a line with no body has no row.
- Consequences (P B15, D §6.1, D1):
  - the 5,587 recovery imports of 2026-10-15 read as fetches;
  - about 1.04M bodiless lines lost their status;
  - 2.7M rows carry no time.
- The catalog read this index rather than the receipts.

**Root cause.** A projection made for one consumer was then trusted by every consumer.

**Do the specs prevent it?** Yes:
- D §6.1 puts the line fields on every row and adds line-only rows;
- A §8.2 adds the rebuild-equivalence check;
- P D1 compares the new table against the old index and blocks on facts that exist only in the old one.

#### M7. A rule change rewrote the raw index

**Evidence.** `upgrade_source_rules` evolves the raw-state schema and publishes it with no old/new comparison (`retention/catalog_raw_updates.py:308-357`; `raw = raw_storage.publish(prepared_state)` at `:353`). `cli/raw_sync.py:68` exposes it as `--upgrade-source-rules`.

**Root cause.** Interpretation and raw bookkeeping shared one mutable structure.

**Do the specs prevent it?** Yes:
- D §7.1: "a registry change rewrites nothing in the lake";
- A §4.2: append or replace, never update;
- only raw writers touch raw.

#### M8. A space optimization replaced a raw digest with a boolean, and the code invented the missing value

**Evidence:**
- `f2fea711` (ct-v9ua) replaced the index's `stored_sha256` with `is_stored`. It bundled seven tickets, all created in the same commit.
- `raw_values._to_legacy_capture_table` and the body lookup in `raw_storage` then filled `stored_sha256` with the content digest whenever `is_stored` was true. That is wrong for every gzip body.
- Fixed in `54a68ac7`, whose message says: "Tests that encoded the false premise now require the digest".
- Receipts and bodies were never affected. Index rows from Oct 22–24 may still be wrong (audit).

**Root cause.** An unmeasured byte-shaving change to a raw-adjacent schema, in a mega-commit, with tests that asserted the bug.

**Do the specs prevent it?** Yes:
- D §6.1 takes `stored_md5` from the creating line;
- D §10 invariant 2 and A §7.4's weekly LIST compare every body's ETag with it, which is exactly the check that catches this class.

**Gap:** D §5.2 should say that `stored_md5` is the Content-MD5 sent with that PUT and is never derived. The ingest-mapping sample in P D1 should include a gzip body.

#### M9. Fixed 64 MiB cap: the fetcher kept cut-off bodies as evidence

**Evidence:**
- The Rust fetcher writes the partial body and marks it `complete=false` (`packages/source-fetch/main.rs:220-233`).
- The cap is a default in `transport/rust_fetch.py:134` and `acquisition/raw_sync.py:215`, and the workflow passes `--max-file-mib 64` (`.github/workflows/capture-raw-sources.yml:346`, fork).
- The cap exists because the memory reservation is about 3× the body size (`acquisition/raw_sync.py:36-42`).
- A §7.1 counts 201 bodies cut off at exactly 64 MiB.

**Root cause.** Bodies were buffered in memory, so memory set the maximum file size.

**Do the specs prevent it?** Yes: A §7.1 requires spooling and "Nothing is cut off", and D §7.3's `good_fetch` requires `complete`. P B2 and B14 cover the fix and the re-fetch.

#### M10. The physical body key was guessed instead of recorded, so links pointed at missing objects

**Evidence:**
- `physical_body_object_key` picks `.pdf` or `.gz` from a media type or filename guess (`retention/body_keys.py:51-66`).
- The site guesses the same way (`catalog-v6.ts:24-48`, fork).
- 261,055 `.pdf` copies do not exist yet (P B13), so a guessed `.pdf` link 404s.

**Root cause.** Where a body physically lives was inferred at read time rather than recorded at write time.

**Do the specs prevent it?** Yes:
- D §5.2 `stored_suffix`;
- D §7.5 `suffix()`, which reads records and makes no guess;
- D §10 invariant 10;
- the plan keeps the golden tests.

#### M11. Tests agreed with themselves

**Evidence:**
- **Retention planner.** It was tested against an invented engine schema, with `path`, `protected` and `status` fields (`packages/congress_api/tests/test_native_capacity.py:280-290`). The real type is `objects: [{object, blocker}]` (docspec-rs `src/model/retention.rs:80-99`). The production caller passes only `(native, dataset)` (`cli/raw_sync.py:436`). So objects the engine protects would have been classified as reclaimable.
- **WAF.** Its Python simulator was stricter than the deployed rule (audit), and the fix came only after `/exports/*` was blocked in production (`3df0d3b3`).
- **Stored digest.** Tests asserted stored digest = content digest (mistake 8).

**Root cause.** Fakes built from guessed responses, checks that encode the assumption under test, and no contract test against the real engine output.

**Do the specs prevent it?** Partly. A §15.5 requires a contract test with the real site.

**Gap:** nothing requires Python callers to be tested against the pinned engine's machine-readable result (A §13.7). Add to A §15 or P C7: callers test against the real binary or a schema generated from its serde types. No hand-written engine fakes.

#### M12. Hand-listed code fingerprints went stale after a refactor

**Evidence:**
- `source_update_requirements` hashes a hand list of module files (`retention/source_update_proof.py:14-23`). The list includes `document_index.py`.
- `e4b3216b` turned `document_index.py` into a 60-line shim (`retention/document_index.py:1-58`) and moved the code to `retention/index/*.py`, which is not hashed. Cached interpretations therefore survive changes to that code.
- `9e0f8a1a` admits that `evidence_fingerprint` "is recorded per reading but never compared".
- The release fingerprint also omits publisher modules (audit).

**Root cause.** Code identity was assembled by hand.

**Do the specs prevent it?** For writers, yes: A §7.2 uses the commit plus the lockfile digest, and P B7 applies it to recovery imports.

**Gap:** D §7.1 does not say how `parser_version`, `sniff_version`, `catalog_version` and the ingest-mapping version are computed (see S5). If they are typed strings, this staleness returns to `readings`.

#### M13. The reader dropped the live format, and verification aimed at a dead host

**Evidence:**
- `3089e771` deleted the v5 decoder (`catalog-v5.ts`, 664 lines) while the live catalog was v5.
- `ce1ff7ef`: the publisher's probes, `pipeline_status` and the preflight allowlist "still named the worker, so publishes would verify against a dead host".
- The public viewer has returned 404 at the custom domain since Oct 24 (audit).

**Root cause:**
- the format change shipped publisher-first;
- the origin host was hard-coded in at least three places.

**Do the specs prevent it?** Mostly:
- A §11.4: the reader accepts the current and previous `schema_version`, and changes ship reader-first;
- A §10.3.5: a canary over HTTPS.

**Gap:** A §10.3.5 should require the canary to read through the exact pointer URL and origin the site ships with (one constant), not a separately configured host.

#### M14. Code grew while it was being "retired"

**Evidence.** `congress_api/retention` measured 3,003 lines (Oct 1, `63ca8f59`), 8,377 (Oct 17, `12bc7db0`), 18,366 (Oct 20, `ab68f546`), 26,005 (Oct 22) and 27,799 (Oct 24). Method: `git ls-tree` at each date plus `wc -l`. Shims kept old import paths alive (O11).

**Root cause.** Each new path was added beside the old one, and the old one was kept "for compatibility".

**Do the specs prevent it?** Partly:
- P §2: build beside, switch, then delete whole;
- P §3: before and after `wc -l` in every deleting PR;
- P Track F's done criteria.

**Gap:** nothing fails when a module scheduled for deletion grows. A CI line budget on those packages would make the ratchet mechanical.

#### M15. An optimization was built before the alternative was measured, and measured on samples too small to show the cost

**Evidence:**
- The incremental grouping attempt could not bound a deletion that splits a group (`docs/experiments/incremental-catalog-20261019/README.md`, ct-si9g counterexample). Its evidence sits in the gitignored `output/` of the primary checkout.
- A full metadata-only rebuild had already run in 613.7 s (`docs/raw-source-pipeline-review.md:257-263`).
- The grouping optimizations were measured on 10,211 rows, while the cost was a 43.8 GB SQLite file over 1.67M rows (`docs/experiments/catalog-rebuild-performance.md`).
- In the engine, the remote 2 MiB / 2,048-row caps (`src/storage.rs:376-390`, from `b4b827d` and `f1043af`) shipped as "perf" with no baseline.

**Root cause.** Optimization started without a real-data baseline or a decision rule.

**Do the specs prevent it?** Yes:
- A §5: recompute the model each run;
- P §3: baseline on real data and the decision rule first; evidence under `docs/`, never in `output/`;
- P M1.3 measures the caps; P C0 reverts them.

#### M16. Process: tickets after the work, self-grading, unreviewable commits

**Evidence:**
- `f2fea711` creates seven tickets in the same commit as their code. One of them, ct-v9ua, caused mistake 8.
- `f213503a`: "address CS 300 Professor punch-list for A+".
- `55ba3479` had to restore modules that the merge `8221566d` silently reverted.
- The audit found closing notes citing commits and hashes that do not exist.

**Root cause.** Proposals were written to fit finished work, and big bundled merges went in without review.

**Do the specs prevent it?** Yes. P §3 requires the ticket before the first commit, one conceptual move per PR, acceptance criteria tied to observable behavior, and evidence committed under `docs/`.


#### M17. A meeting-ID parser handled one of three House prefixes, because its fixture was invented

**Evidence:**
- `retention/index/records.py:483`: `event = root.get("meeting-id", "").removeprefix("HMKP")`, added in `3f4eeab1` (2026-10-03, "Rebuild document tables from retained sources").
- The test added in the same commit uses `meeting-id="HMKP1"` (`git show 3f4eeab1`, the witness-list fixture).
- Real publisher XML carries three prefixes, the meeting type followed by the event ID: `HHRG106245`, `HMKP106292`, `HMTG100431` (fixtures under `packages/congress_api/tests/fixtures/meeting_inventory/`). `matching/house.py:36` already maps meeting types to all three.
- Effect: hearings and meetings (`HHRG`, `HMTG`) never get a numeric event in the old index, so their documents lose the meeting context that event joins supply.

**Root cause.** A fixture written to fit the code rather than sampled from the publisher; the same rule lived in two modules, one of them wrong.

**Do the specs prevent it?** No. D §6.5 says `event_id` is "the meeting ID shared by docs.house.gov, Congress.gov and the committee explorer" but not how to parse it. **Fix:** a parser rule (strip the value of the `meeting-type` attribute, or `^H[A-Z]{3}`) and an S fixture with all three prefixes (P §5.3).

#### M18. A wiring commit shipped a CLI route that cannot run, on the cut-off recovery path

**Evidence:**
- `cli/raw_sync.py:469` calls `download_ranges(archive, args.selected_urls or (), fetch=fetcher.fetch)`. The signature is `download_ranges(client, url, path, *, size, last_modified, ...)` (`acquisition/streamed_recovery.py:31-40`), so the call raises `TypeError`.
- Added by `e4b3216b` (2026-10-23, "decompose docspec_client and retention, wire Wave-2C CLIs, break cycles"), a large bundled commit.
- `test_streamed_recovery.py` (359 lines) calls the function directly; nothing exercises the route a job would use.
- `streamed_recovery` is the only code that has stored bodies far above 64 MiB, which is exactly what P B14 needs.

**Root cause.** Wiring was done in a bundled refactor, and tests covered functions, not the commands jobs run.

**Do the specs prevent it?** No. A §12 says "the same commands run locally or in CI" but nothing requires that each command runs in a test. **Fix:** P §3 or A §15 adds one smoke test per job command through its real entry point (capture, publish, maintenance, backfill, recovery import).


### 6.2 Hard-won knowledge to carry forward: detail


#### K1. API keys must never reach a receipt or a stored URL: LOST (raw, permanent)
- **Evidence:**
  - The capture scope refuses any URL whose query has `api_key`, `apikey`, `key`, `token`, `access_token` or `authorization` (`ca/parsers/archive_links.py:19,56-57`). It also refuses credentialed authorities (`ca/parsers/document_links.py:75`, `'@' in url.netloc`).
  - Committee detail URLs are rebuilt without their query, "without query credentials" (`ca/acquisition/committees.py:23-29`).
  - GovInfo paging re-adds the key on every request, because "nextPage already carries the paging params, minus the key" (`ca/acquisition/gpo.py:302-304`).
  - Error text keeps exception class names only, "never exception messages containing secrets" (`ca/transport/http.py:76-89`, `:137-138`).
  - Zyte: "Authentication stays on the request and must not be written into receipts" (`ca/transport/zyte.py:30-36`, commit 237013c7).
- **Why it matters:** Congress.gov (`transport/congress.py:8-9`) and GovInfo put the API key in the query string. P B16 routes the committee and meeting fetches through the raw writer, which records `requested_url` and `url` (D §5.2). The raw prefixes sit under an indefinite bucket lock (A §7.4), so a key written once can never be removed.
- **Target home:** a raw-writer rule, A §7.2 and §14. Strip or refuse credential query parameters before writing `requested_url`, `url`, `redirects[]` and `prior_attempts[]`. Send keys as a header where the API allows it (api.data.gov accepts `X-Api-Key`). Add a refusal-matrix test for P B3.
- **Spec status: LOST.**
  - A §7.2 and §14 forbid only cookies and the `authorization` header.
  - D §7.2's strip-list covers trackers, not credentials.
  - Unverified, so check before B16: whether Congress.gov or GovInfo response bodies echo the request URL with its key. Bodies are stored whole and readable publicly.

#### K2. Fetch-scope safety: private hosts, credentials, redirect hops, media: Partly
- **Evidence:**
  - **Host refusals:** the scope refuses `localhost`, `metadata.google.internal`, `api.zyte.com`, the API hosts, `*.local`, `*.internal` and non-global IP literals (`ca/parsers/archive_links.py:45-62`).
  - **Media:** video and audio files are never captured (`archive_links.py:18,28`; `ca/retention/capture_inspection.py:87-88`).
  - **Playlists:** only subtitle playlists and segments are followed, "never audio or video segments" (`archive_links.py:249-268`).
  - **Redirects:** every hop is re-checked against the scope, with at most 6 hops and an `excluded_redirect` error (`ca/transport/source_capture.py:124-164`).
  - **Odd authorities:** IPv6 zone IDs, IDNA hosts and ports are validated, and control characters are refused, because "urlsplit silently removes control characters; do not repair an authority by deleting bytes" (`ca/parsers/document_links.py:66-94`).
  - **Windows Media:** `video/x-ms-wvx` redirector files are not video (`ca/retention/saved_responses.py:36-37`).
- **Tests:** `ca-tests/test_capture_url_admission.py:88-108` pins 15 hostile archive-replay forms, including `web.archive.org.evil.example`, `:8443`, `127.0.0.1`, `user:pass@` and `?token=`.
- **Target home:**
  - the capture-scope registry (D §7.1) for media extensions and host refusals;
  - a fetcher rule (A §7.1) for the per-hop re-check and private-IP refusal;
  - the URL test vectors move as they are.
- **Spec status: Partly.** D §7.7 has a capture-scope registry of URL patterns. Nothing says redirects are re-checked per hop, that private addresses are refused, or that media is excluded.

#### K3. Publisher politeness and blocking: Partly (code survives, specs silent)
- **Evidence:**
  - **Measured block:** "docs.house.gov refused 389 requests in 17 seconds and 137 at five/second" (`ca/transport/http.py:3-7`; `ca/transport/zyte.py:2-4`, "refuses a client for about 90 seconds").
  - **Gaps:** direct starts are spaced 1.2 s on docs.house.gov and 0.2 s elsewhere (`http.py:129`). A House 403 pauses that host for 60 s (`:185`).
  - **Retries:** retryable statuses are 202, 403, 408, 429, 500, 502, 503, 504 and 520 (`:188`). Backoff is 2^(n+1) s.
  - **Capture limits:** 60 file starts per second and 80 workers (`ca/transport/rust_fetch.py:134`; `.github/workflows/capture-raw-sources.yml:345`). A rate limiter shares one file-start budget across redirects and fallback (`packages/source-fetch/main.rs:4,27-60`).
  - **Bot challenges:** c-span.org answers a plain client with a challenge (`zyte.py:2-3`).
  - The policy matrix is in `packages/congress_api/README.md:191-214`.
- **Target home:** fetcher rules (A §7.1). The fetchers survive (P §2), so the code carries this. Add the measured docs.house.gov limit to the pacing test (`ca-tests/test_http_policy.py`).
- **Spec status: Partly.** A §16.1 says capture is "bounded by politeness to sources" and stops there. Nothing stops a rewrite from dropping the docs.house.gov rule.

#### K4. When to fall back to Zyte, and how to record it: Partly
- **Evidence:**
  - **No fallback:** for `saved`, `excluded_media`, `size_limit`, `resource_limit` and `unsupported_format`, for a known dead route that already has a queued fallback, or for an `excluded_redirect` (`ca/transport/rust_fetch.py:259-282`).
  - **Fallback:** on challenge, timeout, request failure, invalid documents, and HTML with no document links (outcome `html`).
  - **Earlier tries:** the direct try is kept as `prior_attempts` (`:281`).
  - **Two statuses:** Zyte's own status stays separate from the publisher's, so "provider errors never masquerade as publisher HTTP" (`ca/transport/source_capture.py:64-122`; `ca/acquisition/house_sites.py:71-72`; commit 237013c7).
  - **Budget:** base64 inflates bodies 4/3 (`source_capture.py:71`; `rust_fetch.py:199`).
  - **Partial bodies:** a 206 or a `Content-Range` header means incomplete on both transports (`source_capture.py:115-117,152-154`).
- **Target home:** fetcher rules (A §7.1). D §5.2 already has `transport` and `prior_attempts`. The 206 rule belongs in D §5.2 `complete`.
- **Spec status: Partly.** D keeps the fields, but not the fallback decision or the 206 rule.

#### K5. Body identity is the content-decoded entity: Partly
- **Evidence:** `packages/source-fetch/main.rs:177-249`.
  - The fetcher copies `Content-Encoding` and `Content-Length` before decoding, because "reqwest's automatic decoders remove the original Content-Encoding and Content-Length fields".
  - It hashes and stores the decoded bytes. An unknown encoding gives `complete=false` with `unsupported_content_encoding`.
  - A declared `Content-Length` over the limit is refused before reading (`oversized_identity_response`, `:130,192-201`).
- **Target home:** a raw-writer rule (A §7.1). State that `sha256` is taken over the entity after transfer `Content-Encoding` is removed, so a CDN that switches compression does not create a new body.
- **Spec status: Partly.** A §7.1 says "the SHA-256 of the original response bytes", which can be read either way.

#### K6. Archive expansion rules: what becomes a member entry, and the limits: LOST
- **Evidence:**
  - **What expands:** ZIP and Apple FileWrapper (`rtfd`) bodies are expanded into member captures, and only after a complete `saved` outcome (`ca/retention/raw_archive.py:120-178`).
  - **Office files stay whole:** Office Open XML and ODF packages are never expanded, detected by suffix, media type or a `[Content_Types].xml` root member (`raw_archive.py:132-138`; `ca/retention/archive_members.py:148-163`). The test `ca-tests/test_archive_member_capture.py:101-110` pins a `.docx` sent as `application/octet-stream`.
  - **Limits:** archive 64 MiB, member 64 MiB, total 128 MiB, 1,024 members, central directory 1 MiB, nesting depth 1 (`archive_members.py:18-28`).
  - **Refused forms:** stored and DEFLATE only; ZIP64, multi-disk and encrypted members are refused (`:116-122,197-205`).
  - **Names:** duplicate member names stay distinct by `entry_index` (`:166-175`). Unsafe names are flagged, not used as paths (`:142-145`).
- **Why it matters:** about 34,000 HTML members sit inside ZIPs (D §7.3). If Office packages were expanded, `word/document.xml` members would become XML "documents". D §6.2 computes the ZIP fingerprint from member hashes in `captures`, so a ZIP over 64 MiB has no member rows and gets no fingerprint. Now that "nothing is cut off" (A §7.1), large GovInfo package ZIPs will arrive, and ZIP storage is 286 GB (A §5).
- **Target home:**
  - a raw-writer rule (A §7.2): which containers expand, Office excluded, limits, and a recorded refusal status;
  - D §6.2: what a ZIP fingerprint is when members were not expanded;
  - an S fixture: a ZIP with two entries of one name and different bytes, which otherwise becomes an "edition-ambiguous endpoint" under D §7.5, because the endpoint `(context_url, member_path)` has no entry index.
- **Spec status: LOST.** A §7.2 and §8.3 say only that "archive members are separate entries".

#### K7. Retry-After and GovInfo ZIP generation: Partly
- **Evidence:** `ca/transport/rust_fetch.py:22-65`.
  - It parses every `Retry-After` header separately, because "an HTTP date itself has a comma", and takes the longest: "Multiple valid hints occur on GovInfo generation responses".
  - It rejects values over 128 characters.
  - A GovInfo 503 on `/content/pkg/*.zip` whose body says "the zip file you have requested is being generated" waits at least 30 s: "GovInfo's generation page asks for 30 seconds while its header says 15".
  - `retry_later` is scheduled at that delay (`ca/retention/raw_archive.py:446-447`).
- **Data:** 25,236 GovInfo 503 "retry later" pages, about 14 KB each, are stored today (`docs/reviews/2026-10-24-design-review/iceberg-parquet-rereview-rev4.md:228-229`).
- **Target home:** a fetcher rule: retry within the run after the stated delay. Add `retry-after` to D §5.2's header allowlist, so the receipt shows why the line is `retry_later`.
- **Spec status: Partly.** D §7.7 makes retryable outcomes due at the next run, which is safe. D §5.2's allowlist drops the header, and nothing keeps the in-run wait.

#### K8. Recheck timing by age, and failures never become absences: LOST (age rule)
- **Evidence:**
  - **Age schedule:** "Check recent meetings weekly, meetings up to two years old every 28 days, and older meetings annually. A changed source revision is due immediately"; a late XML revision puts an old meeting back on the fast schedule (`ca/acquisition/refresh.py:1-17`).
  - **Today's raw capture:** transient failures retry after 1 day; 404, 410 and link-less HTML after 7 days; `saved` is terminal (`ca/retention/raw_archive.py:433-447`, `NON_DOWNLOAD_OUTCOMES` at `:54-55`).
  - **No false absences:**
    - "Errors never become confirmed absences" (`ca/transport/http.py:6`).
    - An empty Senate 200 is retried, because "converting them to empty text turns a temporary outage into a permanent negative row" (`ca/transport/senate.py:17-47`).
    - "Wait seven days after a new meeting before a once-only probe, so a scheduled future meeting cannot acquire a permanent negative answer" (`ca/matching/captions.py:21-23`).
    - "A run budget pauses the queue; it never declares unvisited pages complete" (`ca/acquisition/house_sites.py:1-7`).
- **Target home:** the recheck-interval registry (D §7.1). Today it is keyed by `(family, interval)` only; it needs an age band, or a family split into recent and old meeting pages. Add a test that no outcome produces a permanent negative.
- **Spec status: LOST for age bands.** D §7.7 rechecks every URL at one interval per family, so it either refetches old pages too often or catches documents added to recent hearings late. The no-permanent-negative rule is carried, because `failed` rows recheck at the family interval.

#### K9. Discovery that lives outside `<a>` tags: JSON, Next.js and calendar APIs: LOST (affects what gets captured)
- **Evidence:**
  - **Congress.gov JSON:** `meetingDocuments` and `witnessDocuments` URLs reach capture only through `json_links` (`ca/parsers/archive_links.py:102-196`, seeds at `ca/cli/raw_sync.py:48-58`).
  - **Next.js sites:** event pages carry their document links in `__NEXT_DATA__`, `pageProps.event`, including `ComponentElementLink {route, label}` objects "rendered ... stored as data rather than HTML (for example an event's hearing memorandum)" (`ca/parsers/page_content.py:8-42`; fixture `ca-tests/fixtures/meeting_inventory/house-energycommerce-event.html`).
  - **JSON-LD:** `Event` objects (`page_content.py:45-65`).
  - **Committee discovery** also reads WordPress REST (`/wp-json/wp/v2/...`), the ASP.NET `eventslisting.aspx?Timeframe=All` list, a POST `/api/events` calendar API, and `Sitemap:` lines in `robots.txt` (`ca/parsers/committee_discovery.py:179-237`).
- **Target home:**
  - parser rules: the HTML parser reads `__NEXT_DATA__` event data and JSON-LD; JSON readings record links for the Congress.gov meeting shape;
  - D §7.7: the queue reads them.
- **Spec status: LOST.** D §6.2 records links only for HTML and XML, from link elements. A document listed only in Congress.gov JSON or in Next.js data would never be queued. Measure the count before the switch.

#### K10. Crawler traps and form safety in discovery: LOST
- **Evidence:**
  - "WordPress month calendars have unbounded previous/next months. Their event archives, REST indexes and sitemaps enumerate actual entries" (`ca/parsers/committee_discovery.py:148-149`).
  - "Never submit search boxes, email forms, or POST form actions" (`:159-160`).
  - "Drupal also uses views-row for footer office addresses" (`:77-78`).
  - A site-wide alert's relative link can inherit `/hearings/` from any parent page (`:141-143`).
  - 404 and 410 are a "recorded unavailability, not a transient transport failure" (`ca/acquisition/house_sites.py:157-158`).
  - Tests: `ca-tests/test_house_listing_identity.py` ("layouts that defeated generic heading/link scans").
- **Target home:** exclusion entries in the capture-scope registry (D §7.1), such as calendar prev/next month routes, with samples from those tests.
- **Spec status: LOST.** D §7.7 queues every in-scope link target from every good page, so a month-calendar link chain grows the queue without end.

#### K11. Building House meeting-XML addresses (B16 fetcher): Partly
- **Evidence:** `ca/matching/house.py:8-39`.
  - Addresses are built from filename prefix, Congress, committee and day; meeting type maps to `HHRG`, `HMKP` or `HMTG`.
  - "A joint hearing is filed under one of its committees and a rescheduled one under either day (108754 is Homeland Security's record, filed under Armed Services' AS26)".
  - "A document's directory preserves the original date even if the meeting was rescheduled."
  - Test: `ca-tests/test_meeting_inventory.py:41-42`.
- **Target home:**
  - a fetcher rule for the P B16 meeting-inventory fetcher, so this function moves with it;
  - an S fixture for dates: a rescheduled hearing whose files carry the original date. D §7.5 takes `document_date` from `filename_date` first, so these documents show the original day, not the hearing day.
- **Spec status: Partly.** A §8.6 names "the House and Senate meeting inventories". Neither spec says how they are found.

#### K12. Congress.gov API quirks for committee and meeting records: Partly
- **Evidence:** `ca/acquisition/meetings.py`.
  - Meeting records start at the 112th Congress (`:40`).
  - Chambers are `house`, `nochamber` and `senate`, where "nochamber = joint committees and commissions" (`:43`). XML says `joint`, which maps to `nochamber` (`:125-127`).
  - "Some historical endpoints fail JSON serialization but serve XML": only on HTTP 500, fetch `format=xml` and check that the identity matches the endpoint (`:114-129`).
  - Pagination that repeats or does not advance is refused (`:89-97`).
  - Relisting overlaps `updateDate` by 2 days, because historical records are corrected in any Congress (`:46,63-64`).
  - Senate meeting records begin in June 2019 (`ca/parsers/senate_page.py:40`).
  - "The detail endpoint has no Congress parameter ... never apply its current status/type to historical Congress-specific list values" (`ca/acquisition/committees.py:77-79`). Duplicate codes on a page are refused (`:63-65`).
- **Target home:**
  - fetcher rules for B16;
  - D §6.4: committee names come from the Congress-scoped list responses (`/committee/{congress}`), never from the detail endpoint;
  - D §7.5 or §6.5: the `chamber` values, including `nochamber`.
- **Spec status: Partly.** D §6.4 and §6.5 define the tables but not these rules.

#### K13. Format sniffing learned from bad bodies: Partly
- **Evidence:** `ca/parsers/document_links.py:164-204` and `ca/retention/capture_inspection.py:71-150`.
  - HTML is identified before trusting a claimed PDF type.
  - "Binary-preamble" PDFs (`%PDF-` after up to 1 KB of non-markup bytes) are recognized (commit 9e0f8a1a; test `ca-tests/test_document_recovery_gaps.py:42-64`).
  - XML with no declaration and no XML headers is still XML, for example House floor schedules: "Infer XML only from a complete parse" (commit 459ff12a; fixture `ca-tests/fixtures/raw_source_floor_schedule.xml`).
  - An XML parse whose root is an HTML tag is HTML.
  - BOMs and UTF-16 BOMs are handled; so are `WEBVTT` after a BOM, `#EXTM3U`, legacy OLE, `{\rtf` and `rtfd`.
  - A `.docx` is distinguished from a ZIP by `[Content_Types].xml` (`ca/retention/archive_members.py:148-163`).
  - Fixtures: two Congress.gov "PDF" URLs that serve Apple FileWrapper bytes (`ca-tests/fixtures/capture-failures/README.md`, `sources.json`: `HHRG-117-BA00-20210204-SD004.pdf`, `HHRG-118-WM00-Wstate-GreenblattJ-20231115.pdf`).
- **Target home:** the `sniff` parser rule (D §6.2) and its versioned tests. Drop today's media-type fallbacks (`document_links.py:195-203`; `capture_inspection.py:111,131-133,146`), as A §8.3 requires.
- **Spec status: Partly.**
  - D §6.2's format list has no `rtf` or `rtfd`, so those fall into `other`.
  - A FileWrapper "PDF" would be listed as an unopenable `other` document, unless item 6 expands its inner file.

#### K14. PDF and image completeness checks: LOST
- **Evidence:**
  - A PDF is accepted only with `%%EOF` in its last 8 KB or a readable structure; otherwise it is `invalid_document` (`ca/retention/capture_inspection.py:95-99`).
  - Binary-preamble PDFs must also be readable (`:96-97`; test `ca-tests/test_document_recovery_gaps.py:61-64`).
  - Missing EOF stays a truncation failure (`ca-tests/test_pdf_reader_recovery.py:18`).
  - Images are decoded once (`capture_inspection.py:89-94`).
  - Real malformed-but-valid PDFs are fixtures: `malformed-text-array.pdf.gz` and `numeric-operand.pdf.gz` (`ca-tests/fixtures/capture-failures/sources.json`).
- **Why it matters:** a server can send a truncated PDF with a matching `Content-Length`, so HTTP completeness alone does not prove the file is whole.
- **Target home:** the `sniff` parser records a PDF tail check, such as `pdf_eof boolean` in `readings.fields`, and D §7.3 requires it for a PDF real file. Keep the two malformed fixtures as tests that must stay real files.
- **Spec status: LOST.** D §7.3 makes any complete 2xx PDF a real file.

#### K15. Challenge and soft-error pages that look like documents: Partly
- **Evidence:**
  - **Challenge markers** in the first 8 KB: `cf-chl-`, `<title>just a moment`, `verify you are human` and `<title>access denied` (`ca/retention/capture_inspection.py:77-86`).
  - **Error titles** treated as error pages (`ca/retention/document_evidence.py:241-246`):
    - `Not Found | Committee Repository | U.S. House of Representatives`
    - `Page Not Found | GovInfo`
    - `U.S. Senate: 404 Error Page`
    - `403 Forbidden`
  - **Recovery titles:** `session verification`, `rate limit reached` and `request not accepted` (`packages/corpus_recovery/src/corpus_recovery/html.py:12-16`).
  - **A House 200 error page:** "what the repository serves, with a 200, when its page cannot show a meeting: 'There was an error retrieving data for this meeting'" (`ca/parsers/house_documents.py:16`; the comment and its use are in commit 3108a6d8). The constant is now unused.
  - **docs.house.gov soft 404:** HTML "Not Found" pages with HTTP 200 at PDF URLs (commit 1be257b0, `house-docs-https-sample-outcome-20261016.json`).
  - **Short block pages:** a congress.gov Cloudflare 520 (7,347 B), a 62-byte "Service Unavailable", and CBO, GAO and DOL block pages (`docs/reviews/2026-10-24-design-review/iceberg-parquet-rereview-rev4.md:240-243`).
- **Target home:**
  - the error-words registry (D §7.1), with each title above as a tested sample;
  - a second registry list for body markers (`cf-chl-`, "verify you are human", the House meeting error sentence), because these are not in a title or heading;
  - S fixtures for each.
- **Spec status: Partly.**
  - D's words (not found, forbidden, error, access denied) catch the four titles.
  - Not caught: "just a moment", "verify you are human" and `cf-chl-` script markers on a page over 2,048 text bytes, and the House meeting error sentence in the body. The PDF-URL soft 404s are carried by `file_shaped`.

#### K16. Human-reviewed decisions about saved responses: LOST
- **Evidence:**
  - `ca/retention/saved_response_reviews.json` holds 29 reviewed `(url, body_key)` rows, measured with the project venv. Categories:

    | Category | Rows |
    |---|---:|
    | `usable_html` | 9 |
    | `soft_404` | 6 |
    | `unrelated_replacement_page` | 3 |
    | `unrelated_landing_page` | 3 |
    | `javascript_shell` | 2 |
    | `document_preview_shell` | 2 |
    | `language_selection` | 1 |
    | `download_interstitial` | 1 |
    | `publication_landing_page` | 1 |
    | `generic_homepage_fallback` | 1 |

  - Each row carries a `review_basis`. `saved_responses.py:13-57` applies them: "An identified error page remains an error page through redirect aliases."
- **Target home:**
  - the P §5.3 hand-labeled sample, where these 29 rows are ready-made labels;
  - provenance: either a review verdict that says a body is not a document, or `url_variants` and recovery records.
- **Spec status: LOST.** D §5.3 review verdicts (`hide`, `duplicate_of`, `title_override`, `kind_override`) target link keys. None says "this body is an error or landing page". No plan step migrates the file. A `soft_404` at a non-file URL would become a real document.

#### K17. URL wrappers and repairs seen in real publisher links: LOST (most)
- **Evidence:**
  - **LIS-to-GPO wrapper:** `lis.gov/cgi-lis/t2GPO/<url>`, unwrapped only when the inner URL is `gpo.gov/fdsys/pkg/...` (`ca/parsers/archive_links.py:77-85`).
  - **Concatenated file URLs:** split only when every part is an allowed file URL (`:86-99`). The commit is 018e4cf5 ("Recover malformed publisher URLs before capture"); its tests are `ca-tests/test_capture_url_admission.py:147-215` (repairs) and `:176-190` (refusals).
  - **Other wrappers:** `ttps://`, `mailto:https://`, and `chrome-extension://<32 chars a–p>/<url>`, which is Adobe Acrobat's viewer prefix (`efaidnbmnnnibpcajpcglclefindmkaj`) pasted into hrefs (`ca/retention/source_aliases.py:7-22`; `packages/viewer_publication/tests/test_filename_aliases.py:55-79`).
  - **Library of Congress replays:** `webarchive.loc.gov/all/<14 digits>[id_]/<url>` (`archive_links.py:20-23`; commit 3729bde2).
  - **Web Harvest replays:** `webharvest.gov/congressNNNth/<ts or 3>/<url>` with explicit-scheme, single-slash (`https:/host`) and omitted-scheme forms (`scripts/webharvest/webharvest_committee_map.py:15,32-46`; tests `scripts/webharvest/tests/test_webharvest_committee_map.py:21,104-126`).
  - **democrats-transportation:** a broken `/download/<slug>&download=1` route is retried as `?download=1`, but only after a 404 or 410 on that host (`ca/parsers/document_links.py:33-48`; tests `ca-tests/test_committee_download_wrappers.py:91-167`).
- **Target home:**
  - the URL-wrapper registry (D §7.1/§7.2) for LIS, `chrome-extension`, `mailto:`, `ttps://`, `webarchive.loc.gov` and the real Web Harvest forms;
  - a parser rule for concatenated hrefs, which yield several targets from one `href`;
  - `url_variants` provenance, or a fetcher rule, for the democrats-transportation fallback;
  - the listed tests are ready registry samples.
- **Spec status: LOST, apart from Wayback and Web Harvest.** D's wrapper list names Proofpoint, rs6.net, exit.asp, `web.archive.org` and `webharvest.gov/<collection>/<ts>[modifier]/<url>`. That Web Harvest pattern misses the `/3/` selector and the scheme-less forms.

#### K18. Which HTML elements are links, and safe parsing: Partly
- **Evidence:** `ca/parsers/document_links.py:97-161`.
  - Links come from `<a href>`, `<link rel=alternate>` typed PDF or XML (commit 9e0f8a1a), `<object data>`, `<embed src>`, `<iframe src>` and `<meta http-equiv=refresh>`.
  - Signals for a download: the `download` attribute, the WordPress `wp-block-file__button` class, and labels like "click here" or "PDF".
  - RSS, Atom and sitemap feed links are excluded.
  - A page's links to itself are context, not documents (`ca-tests/test_circular_document_links.py`).
  - Surrounding spaces are trimmed, but spaces inside a URL are kept, because "Spaces in publisher filenames remain valid path data" (`:67-74`).
  - XML is parsed with `resolve_entities=False, no_network=True` (`ca/parsers/archive_links.py:226-228`; `capture_inspection.py:118-120`).
  - The Senate reader needs UTF-8, but "Keep generic links from HTML with another encoding" (`archive_links.py:208-215`).
  - Nested embedded data is limited to depth 12 and 4 MiB (`ca/parsers/page_content.py:25,38`).
- **Target home:** parser rules for the `html` and `xml` readings (D §6.2): the element set, the `tag` values, entity-safe XML, and decoding by declared charset with replacement so the reading still completes. The listed tests become reading tests.
- **Spec status: Partly.** D §6.2 says "every link ... with its `href` as written" and has a `tag` column, but does not define which elements count. A reading that fails on encoding has no role and gives no links (D §7.3).

#### K19. House meeting XML specifics: LOST (four rules)
- **Evidence:**
  - **Removed elements:** "Removed elements stay out", applied at the panel, witness, document and file levels through `remove-date` (`ca/parsers/house_documents.py:4-5,72,82-106,125`).
  - **Witness documents** are grouped under `witness-documents/witness-document` (`:100-106`).
  - **Labels:** `file` elements carry `doc-url` and no text; the label is the group's `description` (`:123-131`).
  - **Meeting IDs:** `meeting-id` is the meeting-type prefix plus the event ID: `HHRG106245`, `HMKP…`, `HMTG100431` (fixtures `ca-tests/fixtures/meeting_inventory/house-formats.xml:2`, `house-multiple-files.xml:2`). `ca/retention/index/records.py:483` strips only `HMKP`. That is a latent bug, passed to list 1.
  - **XML is authoritative:** "An audit of 5,594 pages found every page document and the same 15,012 witnesses in XML" (`house_documents.py:4`).
  - **Witness lists:** a `witness-list` XML is treated as a document, a `committee-meeting` XML as a source record (`ca/retention/document_evidence.py:209-212`).
- **Target home:**
  - parser rules for the `xml` reading: add `remove_date` to the link struct, take the group description as `text`, and parse the event ID by stripping the 4-letter prefix;
  - D §6.2 grouping ancestors: add `witness-document`;
  - D §7.3 source-record roots: decide whether `witness-list` is a record or a document.
- **Spec status: LOST.** D's grouping list is `li`, `tr`, `meeting-document` and `document`. Its link struct has no `remove_date`, so removed renditions would still group and give meeting refs. D's source-record registry lists "witness records" as metadata, the opposite of today's rule.

#### K20. Committee code forms: LOST (rule is wrong for `hl`)
- **Evidence:**
  - "House codes: hs for standing committees, hl for Intelligence and the select committees (hlig00 is IG00)" (`ca/matching/house.py:33-34`; test `ca-tests/test_meeting_inventory.py:41-42`).
  - Congress.gov uses `nochamber` for joint bodies (`ca/acquisition/meetings.py:43`).
  - Senate system codes map to sites (`ca/parsers/senate_page.py:22-26`) and to Senate Recording Studio player codes (`ca/parsers/senate_player.py:19-26`).
  - MODS committee codes are not always lowercase (`ca/parsers/gpo_hearings.py:115`). Related items in MODS "are cited laws/bills and must not contribute committee ownership" (`:103-106`).
- **Target home:** a new committee-code registry (D §7.1) from house-naming code to Congress.gov system code, with `hl` entries and joint or commission entries. Its samples come from these files.
- **Spec status: LOST.** D §7.5's rule `'hs' || lower(code)` maps `IG00` to `hsig00`, which names no committee.

#### K21. Recovery kinds and when a recovered copy was captured: Partly
- **Evidence:**
  - **Eight kinds:** the Oct 15 receipts carry eight `prior_access_category` values (commit 871e5c9d, `docs/reviews/2026-10-24-design-review/iceberg-parquet-rereview-rev4.md:255-266`):

    | Kind | Count |
    |---|---:|
    | `recovered_document` | 5,154 |
    | `requested_content_in_official_hearing` | 341 |
    | `official_updated_revision_available` | 49 |
    | `official_introduced_bill_counterpart` | 8 |
    | `official_recorded_votes_available` | 8 |
    | `requested_content_in_official_report` | 7 |
    | `official_complete_statement_text_available` | 5 |
    | `official_alternate_amendment_available` | 5 |

  - **Not written by code:** no code in the repository writes these values (`git log -S` finds them only in docs).
  - **Timestamp basis:** corpus_recovery picks a recovered copy's time from one of five sources, records which, and refuses when none is established (`scripts/corpus_recovery/prepare_corpus_recovery_source_records.py:140-162`). The five, in order:
    1. render time, kept apart from snapshot time because "rendering time and the original archive snapshot time describe different bytes";
    2. the Wayback 14-digit index time;
    3. an existing exact-body capture;
    4. a sealed package-member capture;
    5. the transport receipt time.
- **Target home:**
  - the recovery-kinds registry (D §7.1/§7.8) with these eight exact strings;
  - a decision on whether `requested_content_in_official_report` is an excerpt, like the hearing kind, or "official report", a substitute;
  - D §5.2 `recovery_evidence`: add `timestamp_basis`.
- **Spec status: Partly.** D maps the categories by description. Its "official report" substitute may or may not mean `requested_content_in_official_report`. corpus_recovery imports carry no category at all, so the rule "an unmapped category MUST fail the build" fails them.

#### K22. Document kinds from publisher context, not only from filenames: LOST
- **Evidence:**
  - Kind order today: the filename; then content (a `witness-list` root, or a witness-statement cover); then the document type from trusted source occurrences (`ca/retention/index/schemas.py:170-182,246-276`).
  - House XML type codes map to kinds (`ca/parsers/house_documents.py:42-56,109-113`), "when its file is only numbered (HHRG-113-IF03-20130319-SD007.pdf, 'Transcript')" (`:26-27`).
  - Senate heading-derived kinds come from `ca/parsers/senate_page.py:151-305`.
  - The rule is documented in `packages/house-naming/FILENAME_PATTERNS.md:58-66`.
- **Target home:** D §7.5 facets. Add a model rule that fills an empty filename kind from the saved file's linking XML `doc_type` (already in D §6.2's link struct) or its reading. Add an S fixture with a numbered `-SD007` file labeled "Transcript".
- **Spec status: LOST.** D takes facets only from `filename_readings`, plus reviews. Numbered House files lose their kind, which P E4 will show as a parity difference.

#### K23. Recovered filenames for legacy cache names: LOST
- **Evidence:**
  - Legacy House cache keys (`re.sub(r'\W+','_', url.split('/meeting/')[-1])`, `ca/retention/document_evidence.py:125-127`) are mapped back to the publisher basename only when forward-encoding known URLs gives exactly one name (`:360-377`).
  - Filename extraction then uses that name (`packages/house-naming/FILENAME_PATTERNS.md:74-79`).
  - Numeric `.none` cache markers are capture state, not documents (`document_evidence.py:262-283`).
- **Target home:** provenance (D §5.3), as `url_variants` or a recovered-name record written once by P B8. Alternatively, a documented rule in the D §6.3 producer.
- **Spec status: LOST.** D §7.4 uses "the recovered name if provenance says so", but no provenance kind or plan step writes recovered names.

#### K24. GovInfo and GPO metadata: Partly
- **Evidence:**
  - **Package IDs:** `CHRG-118hhrg57177` gives Congress 118, chamber h, jacket 57177 (`ca/parsers/gpo_hearings.py:14-15`).
  - **Ingest date:** for hearings before about 2009, GovInfo's ingest date "is when GPO digitized old records, not when the transcript first came out" (`:36-39`).
  - **Errata** are filed as separate packages (`:49`), for example `CHRG-110shrg41912-err.htm` (`ca/matching/reviewed_committees.py:125`).
  - **Multi-day volumes:** the first day is the start. Appropriations volumes print several hearings under one title (`gpo_hearings.py:51-55,128,206-231`).
  - **Event IDs:** MODS carries meeting event IDs (`:166`; `ca/models/gpo.py:104`).
  - **File locators:** "Read actual METS file locators without guessing filenames from package IDs" (`ca/parsers/gpo.py:108-112`).
- **Target home:**
  - meeting refs: D §7.5 `meeting_ref` from a MODS record whose reading lists the package, as one more source like the House meeting XML;
  - a `content_date` parser rule: never take GovInfo ingest or modified dates;
  - S fixtures: an errata package and an Appropriations volume.
- **Spec status: Partly.** D §7.5 `meeting_ref` omits MODS, so GovInfo hearing prints get no meeting ref.

#### K25. Senate site knowledge: Partly
- **Evidence:** `ca/parsers/senate_page.py`.
  - **Listing URLs:** nine forms (`:30-32`).
  - **Hearing-page URLs:** four forms (`:36-37`).
  - **Drug Caucus attachments:** `/media-center/files/` attachment pages lead to the real file (`:905-908`).
  - **Business meetings** are recognized in the URL and listing title (`:50`).
  - **Title prefixes:** rescheduled, postponed and cancelled (`:911-913`).
  - **Site chrome:** a line on more than five of a site's pages belongs to the site (`:43`).
  - **No event IDs:** Senate pages carry none; association uses the page's own date and at least half the rarity-weighted title subject, and ambiguous ties stay unlinked (`ca/acquisition/senate.py:9-15`).
  - **Download landing pages:** about 4,900 Senate `/download/<slug>` pages, saved with no media type, while the real PDF came from `?download=1` (`docs/reviews/2026-10-24-design-review/iceberg-parquet-rereview-rev4.md:229-230`).
- **Target home:**
  - the capture-scope registry for listing and hearing routes;
  - the file-shape registry, which should add `/media-center/files/`. Today's route list is `ca/parsers/document_links.py:11`: `/download/`, `/media-center/files/`, `/wp-content/uploads/`, `/_cache/files/`, `/imo/media/doc/`, `/services/files/`, `/sites/*/files/`, `files.serve`;
  - S fixtures.
- **Spec status: Partly.** D's narrow file-shape list carries `/download/` and `download=1`, so landing pages are handled. Senate documents get no `meeting_ref`, because A §8.6 sources Senate meetings from inventories that carry no event ID and D §6.2 forbids body-external association.

#### K26. Which date on a page is the document's: Partly
- **Evidence:**
  - Senate date forms: "6/12/2019", "06.12.19", "June 12, 2019", "Wednesday, March 11th, 2026", "Jun 24, 2026", "2019-06-12". Two-digit years pivot at 35 (`ca/parsers/senate_page.py:56-57,876-892`).
  - "Publication dates are only ranking hints, never evidence of a proceeding's date" (`ca/acquisition/senate.py:6-7`). "Read a proceeding's own displayed title/date; publication dates are excluded" (`senate_page.py:917-924`). Test: `ca-tests/test_house_listing_identity.py:116`.
  - In house-naming, `transcript-07282103` is not July 28, 2103, and "two-digit years never acquire a century" (`packages/house-naming/FILENAME_PATTERNS.md:166-172`).
  - GPO day-header layouts are recorded at `ca/parsers/gpo_hearings.py:206-231`.
- **Target home:** a `content_date` parser rule (D §6.2): only the proceeding's own labeled date qualifies; publication, posted and continuation dates never do. Use these tests as fixtures.
- **Spec status: Partly.** D says only "null unless exactly one date qualifies", without saying what qualifies.

#### K27. Classifying recovered HTML content: Partly
- **Evidence:** `packages/corpus_recovery/src/corpus_recovery/html.py:9-56`.
  - Drupal document bodies sit in `field-name-body`.
  - "No prepared statement" is a real historical House page, not an empty one.
  - Printed hearing transcripts in HTML are recognized by the markers "hearing before", "serial no." and "printed for the use of the committee".
  - Other categories: an attachment page with links; a substantial body of at least 100 words with a title.
- **Target home:** S fixtures and P §5.3 labeled-sample strata (short legitimate pages, attachment pages).
- **Spec status: Partly.** P §5.3 asks for short real pages and landing pages as strata, but not these concrete cases.

#### K28. Mirrors and genuine versions (fixtures): Partly
- **Evidence:**
  - "Congress.gov mirrors House files under a different URL" (`ca/matching/house.py:47-48`). The mirror is not always byte-equal, as the FileWrapper fixtures in item 13 show.
  - Two genuine publisher versions (`docs/reviews/2026-10-24-design-review/iceberg-parquet-rereview-rev4.md:244-247`):
    - Education and Labor committee rules: the Jan 2007 draft vs the Dec 2007 GPO print, 81% the same text;
    - `BILLS-112hr1063ih`: identical text; GPO re-processed the PDF with iText in Jan 2023.
  - Six Ways and Means 2-page hearing-advisory excerpts recovered for `?type=document&p=` links (commit 871e5c9d).
- **Target home:** S fixtures:
  - a docs.house.gov original and its Congress.gov mirror, both with equal bytes and with a wrapper;
  - an iText re-processed copy, which should join by `same_text`;
  - a draft and its print, which should stay separate.
- **Spec status: Partly.** P §5.3 lists mirror and edition fixtures in the abstract; these are the real cases.


#### K29. Filename evidence beyond the URL's last segment: LOST

- **Evidence:** `retention/index/sources.py:119-145` (`source_names`), from `43f112ef` (2026-10-01). One capture row yields a filename from each of:
  - the `Content-Disposition` header, preferring `filename*` (RFC 2231) over the fallback (`disposition_filename`, `:86-103`);
  - the URL path basename of the context URL **and** of the final URL (`:131-136`);
  - query parameters named `filename`, `file`, `name`, `document` or `attachment` whose value has a document extension (`url_document_names`, `:38-54`);
  - a retained local path when nothing else names the body, unless it is a bare hash (`:137-142`).
- **Why it exists:** publishers serve files from endpoints such as `download.aspx?file=report.pdf` or name them only in the header. The docstring: "Keep header, URL, and local-only spellings distinguishable."
- **Target home:** add `content-disposition` to D §5.2's header allowlist (raw-writer rule; it is gone forever from receipts written without it) and extend D §7.4's effective-filename rule, or record an explicit decision to drop these names. Either way, measure how many of today's 1.68M source files come from these sources before E3/E4.
- **Spec status: LOST.** D §7.4 uses only the recovered name, the member basename or the URL's last segment.

#### K30. How a URL basename is decoded: LOST (unspecified)

- **Evidence:** `url_filename` (`index/sources.py:30-35`) unquotes the path basename with `errors="strict"` and keeps `+` literal ("'+' in a path remains a literal plus"); query names are decoded once by `parse_qsl` ("do not decode twice", `:47-48`).
- **Why it matters:** `source_id` hashes the filename (D §7.4). A different decoding changes every affected ID and the `(filename, source_url)` join to `filename_readings`.
- **Target home:** a D §7.4 rule and golden vectors that include `%20`, `+` and non-UTF-8 escapes.
- **Spec status: LOST.** D says "the URL's last segment" only.

#### K31. Link context follows redirects and never comes from feeds or sitemaps: LOST

- **Evidence:** `retention/index/document_sources.py`: a redirect transfers a URL's occurrences to its final URL (`_add_transfer`, `:183-206`, basis `publisher_redirect`); RSS, Atom and sitemap pages never pass context (`collection_url`, `:143-148`; `transfer_occurrence`, `:151-161`).
- **Why it exists:** publisher pages link the pre-redirect URL; feeds list everything and would label every document with a feed title.
- **Target home:** D §7.10 `linked_from` matches a link's resolved target against both `requested_url` and `url` of the occurrence's fetch rows, and excludes pages whose `xml_root` is a feed or sitemap (`rss`, `feed`, `urlset`, `sitemapindex`).
- **Spec status: LOST.** D §7.10 matches the endpoint's `url_key` only (the `context_url`).

#### K32. Records and error pages recognized by URL: Partly

- **Evidence:** `retention/index/schemas.py:437-470`, before house-naming runs:
  - `www.govinfo.gov/metadata/pkg/<id>/{mods,premis,mets}.xml` are source records;
  - `api.govinfo.gov/collections/<C>/<timestamp>` is a collection listing; `api.govinfo.gov/packages/<id>/summary` a package summary;
  - `api.congress.gov/v3/{hearing,committee-meeting,bill}/…/<n>` are API records;
  - `docs.house.gov/committee/Error/Error.aspx` and `www.govinfo.gov/error` are error pages (the targets of failed redirects).
- **Target home:** the API-endpoint registry already covers the two API hosts; add METS to the source-record roots (D §7.1 lists MODS and PREMIS only); add the two error URLs as error-page entries (by URL, since a redirect target's body may pass the text-size test).
- **Spec status: Partly.**

#### K33. Generated probe URLs are evidence, not a schedule: LOST

- **Evidence:** `retention/capture_url_admission.py:14-27`, used at `raw_archive.py:244-254`: a URL that exists only because a probe guessed it (`generated_xml_probe`) is not scheduled again unless an independent publisher link names it. Commit `f461f40e`: "require independent publisher links before reopening excluded generated probes."
- **Why it matters:** probe families (for example the `.xml` path guesses in `docs/youtube-coverage/research/data/xml_path_family_samples.csv`) produce many 404s. D §7.7 keeps one `url_state` row per requested URL and rechecks it at its family interval forever, which spends politeness budget on guesses.
- **Target home:** a capture-scope exclusion for probe families, or a `url_state` rule: a requested URL whose only `source_context.observations` are probe guesses is not rechecked after a 404 or 410.
- **Spec status: LOST.**

#### K34. A version is a digest of its code and data: Partly

- **Evidence:** three working examples:
  - `retention/index/metadata.py:488-497` `parser_fingerprint`: house-naming's `.py` and `.json` files plus the `extract` wrapper's source;
  - `retention/document_evidence.py:38-53` `evidence_fingerprint`: the reader modules plus the Poppler and Pillow versions;
  - `retention/document_recovery.py:19-20` `recovery_fingerprint`: the module's own bytes.
- **Why it matters:** the hand-listed alternative went stale (M12).
- **Target home:** D §7.1: `parser_version`, `sniff_version`, `catalog_version` and the ingest-mapping version are digests of their code, data and tool versions (S5).
- **Spec status: Partly.** D §7.1 defines the SQL and registry versions as digests, not the parser versions.

#### Lost by the specs (no registry, rule or fixture carries them today)

1. Credential query parameters (`api_key`) kept out of receipts and stored URLs (item 1). This is the only item where a mistake is permanent under the bucket lock.
2. Archive expansion policy: rtfd members, Office packages kept whole, the size and member limits, ZIPs over the limits, and the duplicate-entry endpoint (item 6).
3. Age-banded recheck intervals (item 8).
4. Link discovery from JSON (Congress.gov `meetingDocuments`), Next.js `__NEXT_DATA__`, JSON-LD and calendar APIs (item 9).
5. Crawler-trap and form exclusions in the capture scope (item 10).
6. PDF tail or readability check before a PDF counts as a real file (item 14).
7. Body-text challenge and error markers beyond title words (item 15, part).
8. The 29 human-reviewed response labels in `saved_response_reviews.json` (item 16).
9. LIS-to-GPO, `chrome-extension://`, `mailto:`, `ttps://`, concatenated URLs, `webarchive.loc.gov` and the real Web Harvest forms (item 17).
10. House XML `remove-date`, the `witness-document` grouping ancestor, description labels, and the event-ID prefix (item 19).
11. The `hl` committee codes and joint or commission codes (item 20).
12. Document kind from publisher XML type codes and from content (item 22).
13. Recovered filenames for legacy cache names (item 23).
14. Meeting refs from GovInfo MODS and for Senate documents (items 24, 25).


Added by the parent pass: K29 filename evidence beyond the URL, K30 basename decoding, K31 redirect-aware link context without feeds, K33 generated probes (all LOST); K32 records by URL and K34 versions as digests (Partly).

#### Already carried (checked, no action)

- **Placeholders:** the empty body (`e3b0c442…`) at 2,817 Senate playlist URLs and the 57-byte caption at 87,161 URLs. D §7.3 handles them with `bytes > 0` and the k = 100 placeholder rule.
- **HTML at file-shaped URLs:** Senate `/download/<slug>` landing pages and docs.house.gov soft 404s at PDF URLs are handled by D §7.3 `file_shaped`.
- **Query parameters:** trackers are stripped and every other parameter is kept, with measured evidence that `download`, `file_id` and `docid` select different files (D §7.2; the final review's parameter table).
- **Status:** non-2xx GovInfo "retry later" pages (25,236) are excluded by `good_fetch`.
- **Cut-off bodies:** the 64 MiB cut-off copies are never real files, and capture retries them (A §7.1; P B14).
- **Recovery imports** are labeled evidence with a synthetic 200 (A §7.2; D §7.8).
- **Import-run dates** come from the import-run registry (D §7.4).
- **Older receipt field names** `original_path` and `source_file` are mapped (D §5.2).
- **Filename rules** stay in house-naming, which survives. That includes host-qualified local conventions such as `TT` and `SFR` (`packages/house-naming/FILENAME_PATTERNS.md:136-150`), which is why D keys filename readings by `(filename, source_url)`.


### 6.3 Over-engineering not to port: detail


Each item gives the reason it was built, and whether that reason still holds. Where it does, the signal to keep is named, even though the code goes.

#### O1. Five raw write entry points, each with its own `immutable` flag

**Evidence:**
- `R2Store.put` (`retention/r2.py:338`);
- `put_pdf_body` (`:400-405`);
- `put_file` (`:407+`);
- `AsyncBodies.put` (`:151-165`);
- `LocalStore.put` (`retention/catalog_cache.py:84`);
- plus recovery's `GuardedStore` (`packages/corpus_recovery/src/corpus_recovery/transfer.py:82`).

They have different 412 semantics:
- bodies return `False` (`r2.py:386`);
- two index prefixes compare by reading the object back (`:388-391`);
- everything else raises.

**Why it was built.** Each writer met a real need: async capture, streaming large files, PDF public headers, local runs.

**Does the reason still hold?** The needs do; the per-call flag does not. **Signal to keep:** one namespace policy keyed by prefix and checked before any I/O (P B3). For bodies, 412 means "unchanged" (A §7.1).

#### O2. A raw-ingest exclusion gate, with quarantine copies

**Evidence:**
- `retention/raw_storage.py:75-236` (162 lines, per P B4). It loads `accepted-files.json`, quarantines payloads and raises `ExcludedBodyError`.
- It is wired into `R2Store.put` (`r2.py:370-372`) and `LocalStore.put`.

**Why it was built.** ct-te1p's deferred-body review, to keep objectionable bodies from being ingested or published.

**Does the reason still hold?** No. The owner decided no list will exist (P §3). **Signal to keep:** if hiding is ever needed, use a `reviews` `hide` (D §7.9). Never filter at raw ingest; raw stays complete.

#### O3. Custody, proof and read-back machinery that duplicates Content-MD5 and ETags

**Evidence:**
- **Caller-supplied digests.** `VerifiedFile` accepts a digest from the caller (`packages/congress_shared/src/congress_shared/custody.py:42-62`); 48 references in 13 files.
- **Read-backs.** `checked_put` reads every write back in full (`transfer.py:26-46`). The recovery body loop does a GET before each PUT, then decompresses and compares (`transfer.py:129-136`).
- **Capture.** It re-downloads the whole existing body on every 412 (`acquisition/raw_sync.py:412-415`). Over half of body-bearing attempts hit an existing body (A §7.1).
- **Process-global caches.** `retention/source_update_proof.py:26-29` and `catalog_batches.py:247-248` hold proof caches; 93a63e1d fixed "cache poisoning".
- **BLAKE3.** It is used throughout the engine and client. The Python package is undeclared, so locked CI runs a pure-Python fallback, about 380–1000× slower (audit).

**Why it was built.** To guard against a file changing between hashing and handing it to the engine, and to resolve PUTs whose acknowledgment was lost ("Do not repeat an uncertain PUT; reconcile its exact bytes read-only", `transfer.py:27`).

**Does the reason still hold?** Partly. Uncertain PUTs still happen, but create-only PUT plus Content-MD5 answers them: a retry returns 412. **Signals to keep:**
- verify bytes once, at the platform boundary (Content-MD5 on a create-only PUT);
- record the digest from the write;
- check ETags in the weekly LIST (A §7.1, §7.4, §10.3.4).

**Conflict:** P §8 keeps recovery `checked_put` "unchanged". See S7.

#### O4. A hand-built raw index: hash-prefix routing, route pages and copy-on-write leaves

**Evidence:**
- `retention/partition_routing.py` (215), `raw_state_routes.py` (160), `raw_changes.py` (89), `raw_capture_pages.py` (133), and most of `raw_storage.py` (1,446).
- Every touched leaf is read and rewritten whole (`raw_storage.py:1141-1170`).
- Keys are hash-distributed, so "only changed leaves" means most leaves. The audit measured about 1.3 GB rewritten, about 512 new datasets and about 770 route PUTs per run (syem and czsd).

**Why it was built.** Point lookups (does this body exist? what is this URL's state?) without loading 1.3M rows, on an engine whose updates are copy-on-write (iceberg 0.10.1 has no delete files). Introduced in `755181bc` and `7f5d04c8`.

**Does the reason still hold?** No:
- body existence is answered by the content-addressed key and a create-only PUT;
- URL state comes from the release's `url_state` (D §7.7);
- lake tables are append-only.

**Signals to keep:**
- one `url_state` row per requested URL, latest fetch wins;
- never hash-partition an append-only table to make updates small.

#### O5. The engine's lifecycle store, with its own retention and garbage collection

**Evidence:**
- About 35 string-keyed lifecycle families, 8 cloned retirement planners, restore points, a succession archive, and a retention inventory (7,080 source + 7,342 test lines, fork).
- `gc.enabled=false` and `delete-after-commit=false` on every table (docspec-rs `src/storage.rs:132-140`); compaction resets `gc.enabled` (`src/catalog.rs:1127-1134`).
- Churn: `src/engine/retention/inventory.rs` 37 commits, `src/engine/backfill.rs` 42.

**Why it was built.** A generic engine with resumable phases and owner-protected retention, for several consumers.

**Does the reason still hold?** Not for the archive: Basin maintains the tables, the archive only appends, and A §13 forbids engine maintenance and resume beyond per-step commits. It does still hold for parked news_lake (S10). **Signals to keep:**
- durable per-step commits (owner decision 2026-10-24);
- retention means Basin expiration plus release retention driven by the pointer.

#### O6. Fault injection and consumer fast paths threaded through production engine code

**Evidence.** `test_hooks` is always compiled (`src/engine.rs:84-85`); 57 `stop_after` sites outside test files; consumer dataset-name predicates (M3).

**Why it was built.** Crash-recovery tests at every phase boundary, and faster initial builds for one consumer.

**Does the reason still hold?** The crash-recovery need does. **Signal to keep:** test crash recovery by killing a real process at a real commit boundary in integration tests, not through production parameters (A §13, §15.7).

#### O7. The Python incremental catalog

**Evidence:**
- About 27.8k lines in `retention/`: `catalog_*` (22 modules), `source_update_proof`, `catalog_qualification`, the adoption modules (`raw_adoption`, `raw_readings_adoption`, `catalog_adoption`), eleven process-global caches and five proof registries.
- Plus `scripts/incremental_boundary_proof.py`.

**Why it was built.** The full Python rebuild took hours and a 43.8 GB SQLite file, so O(change) updates looked necessary.

**Does the reason still hold?** No:
- A §5 measured a narrow relational proxy at 3.7 s and grouping at 1–2 s;
- incremental connected components could not bound deletions (M15).

**Signal to keep:** incremental work only where the per-item work is expensive. That means anti-join work lists for `readings` and `filename_readings` (A §8.1), and a model recomputed whole.

#### O8. The publication journal, resume and attempt route, a second route, and hand-listed release identity

**Evidence:**
- `packages/viewer_publication`: `attempt.py` (346), `resume.py` (50), `reconciliation.py` (84), with continuation, local and plan modules. Fork-measured at 2,682 source + 2,180 test lines.
- A second route, export-pins (`filename_exports.py`, 1,254 lines).
- Release identity from hand lists (`viewer_publication/release_identity.py`, audit).
- First commits: `8395c614` "Resume publication workflows from one validated original-attempt record" and `dbfe389b`.

**Why it was built.** Preparation took hours, so a failed publish had to resume from a prepared GitHub artifact.

**Does the reason still hold?** No. Model plus export takes seconds, and the release is immutable with one If-Match flip. **Signals to keep:**
- a rerun is the resume (A §12);
- create-only upload, with a 412 checked by one HEAD (A §10.3.4);
- a failure leaves the previous release live.

#### O9. docspec_client fallbacks that change what a request means

**Evidence** (`packages/docspec_client/src/docspec_client/client.py`):
- On an "unknown field" error it silently drops `partition_by` (`:516-521`).
- It quietly drops partition columns missing from the table (`:461-464`).
- On `operation_conflict` it re-encodes with legacy row-group sizing (`:523-533`).
- It downgrades `SET_UNION` to `MAX` for non-list columns (`:660-663`).
- When the engine lacks `merge`, it loads the whole base table and merges in Python (`:734-752`).
- The audit counted three copies of the submit/retry logic (`client.py:445-578, 619-797, 842-915`).

**Why it was built.** To run against several engine revisions (version skew) and survive transient errors.

**Does the reason still hold?** No. One pinned engine is checked before any storage access (A §12), behind a thin job-spec CLI (A §13.7). **Signal to keep:** retry only transport errors before submission (`:507-512` already does this), and refuse everything else.

#### O10. A Python re-implementation of the engine export

**Evidence:**
- The v6 preparer: 17 modules, 3,294 source lines (fork).
- `filename_exports.py` facet, fold and occurrence flattening (`:285-620`, fork).
- Python per-row facet loops (`filename_exports.py:504-546`, fork).
- Objects scale as O(rows × columns), *est.* 3+ GB (audit).

**Why it was built.** The engine export lacked folds, facets and child tables at the time.

**Does the reason still hold?** No. A §13.3 and P C3 make the export an engine capability. **Signal to keep:** the list of features it needed (fold, facets over list columns, child ranges) becomes C3's acceptance list.

#### O11. Compatibility shims, a module-class hack and import-time monkeypatching

**Evidence:**
- `retention/document_index.py:47-58` replaces its own module class so that `setattr` forwards to eight submodules.
- `retention/raw_storage.py:50-72` monkeypatches `raw_state_routes.due_time` and `.priority` at import.
- Forwarding shims: `retention/docspec.py`, `retention/docspec_host.py`, `viewer_publication/cli.py:4`, and `news_lake/storage/docspec_backend.py`.
- P counts shims and legacy formats at 2,064 + 1,058 lines.

**Why it was built.** To keep tests and callers that patch module internals working after the `e4b3216b` decomposition.

**Does the reason still hold?** No. **Signal to keep:** none in code. Tests should exercise behavior, not import paths. M12 shows the hidden cost: a shim silently broke a fingerprint.

#### O12. Hand-written edge infrastructure

**Evidence:**
- A WAF path allowlist, plus a Python simulator stricter than the deployed rule (audit).
- `apply` PUTs the zone's whole phase entrypoint rulesets (`packages/viewer_publication/src/viewer_publication/apply_r2_edge_rules.py:271-285`), replacing any other rules in that phase.
- `verify_live_edge` requires 403s on `/receipts/*` and `/indexes/*` (fork).

**Why it was built.** To keep raw and index paths off the custom domain.

**Does the reason still hold?** No: `r2.dev` serves every key and everything is public (A §11.7, §14). **Signal to keep:** CORS, cache headers, CSP and the `?filename=` rule (fork: about 570 of 722 lines stay).

#### O13. Duck typing and swallowed errors as capability negotiation

**Evidence:**
- 76 `hasattr(` calls in `retention/` src;
- 8 `except Exception: pass` in `retention/`;
- examples: `hasattr(store, 'delete')` guarded the gzip deletion; `hasattr(native, 'inspect')` and `hasattr(native, 'inspect_retention')` (`native_capacity.py:453, 481`); `hasattr(raw_storage, 'evolve_state_schema')` (`catalog_raw_updates.py:338-339`).

**Why it was built.** Each function accepted fakes and several store types without a declared interface.

**Does the reason still hold?** No. These branches hide contract mismatches (M11). **Signal to keep:** typed interfaces, and `deny_unknown_fields` on both sides of the engine boundary (P §8 keeps it in the engine).

#### O14. Capture doing interpretation and publication

**Evidence:**
- Capture parses during fetch (`acquisition/raw_sync.py:288-293, 422-439`, fork).
- `RETRY_OUTCOMES` includes `html`, `challenge`, `parse_failed` and `unsupported_format` (`raw_sync.py:31-33`), so capture decides what counts as a document.
- Acquisition once called the catalog in a `finally` (`docs/raw-source-pipeline-review.md:15-22`, since moved to a separate workflow job).

**Why it was built.** To avoid re-reading bodies, and to publish right after capture.

**Does the reason still hold?** No. Parsing happens once per body and parser version in the lake (A §8.3), and capture and publish are separate jobs with separate credentials (A §12). **Signal to keep:** capture records facts (status, sniffed format, suffix, MD5); the model classifies.


#### O15. The `document_id` formula in four implementations

**Evidence:**
- `retention/index/bipartite.py:197-205` (`compute_document_id`);
- a streaming SQLite variant for large components (`bipartite.py:295-309`) that rebuilds the same compact JSON by hand;
- docspec-rs `src/engine/connected_components.rs:23-36`, with a hand-written SHA-256;
- `retention/native_features.py:1036-1177`, a Python copy of the engine's whole ConnectedComponents transform, used when the engine answers "unknown variant" (`:1233-1237`). Added in `580b802b` ("unified union-find").

**Why it was built.** Staged engine adoption, an engine version that might lack the transform, and components too large for memory in the 43.8 GB SQLite era.

**Does the reason still hold?** No. One pinned engine is checked before storage access (A §12), grouping runs over 32-bit IDs with a 16 MB parent array at 4M nodes (A §9.3), and A §13 keeps the formula out of the engine. **Signal to keep:** one formula, in the model SQL, checked by golden vectors generated from the Python original (P E3). A version mismatch is a refusal, not a fallback.

#### O16. Copies and facades left behind by the decomposition

**Evidence:**
- `retention/index/sources.py:234-388` repeats `capture_schema`, `capture_batches`, `_capture_tables`, `record_from_capture_row` and `add_retained_senate_pages` from `index/records.py:26-130,401-445`; `diff` finds only a blank line of difference.
- `retention/catalog/__init__.py`, `raw/__init__.py` and `review/__init__.py` (112 lines) forward to other modules and have zero importers anywhere.
- All came from `e4b3216b` (2026-10-23), which split `document_index.py` to break import cycles.

**Why it was built.** To break cycles and give the modules a layer structure without changing callers.

**Does the reason still hold?** No: the copies serve no caller the originals do not, and the facades serve none. **Signal to keep:** the layer names (raw, review) are the right grouping for what survives (4.1 §7). A split deletes the original in the same commit.


### 6.4 The same patterns in the target specs and plan


#### S1. The effective-filename rule is defined twice

D §6.3 has the `filename_readings` producer compute the effective filename "itself", and D §7.4 derives it again in the model.

**Risk.** If the two differ, the join on `(filename, coalesce(source_url, ''))` misses. Facets go silently null, and the completeness gate still passes, because the producer's work list agrees with its own rule.

**Fix:**
- one definition, either one SQL function shared by both or a producer output keyed by capture row;
- an invariant in D §10: "every source file joins a filename reading at the pinned catalog version".

#### S2. The real-file rule is evaluated twice, and the gate checks against itself

The `fingerprint` producer's work list uses `real_files` (D §6.2; A §4.4 names this as accepted repeated work), and so does the model (D §7.3). D §7.1's gate checks that the pinned version's work list is empty. If the producer computes that list with its own copy of the rule, the gate cannot see a divergence.

**Fix:** the producer evaluates the model's own `real_files` SQL at the current snapshot. The gate recomputes the fingerprint candidates with the model's rule.

#### S3. Recovery facts come from two sources, with no rule for mismatches

D §7.8 joins `captures` import rows and provenance `recoveries` on `(url_key(original_url), body_sha256)`. Today they disagree. The audit counted:
- 12,431 recoveries only in `accepted.json`;
- 1,172 receipt recoveries missing from it;
- 269 differing bases and 57 differing recovered URLs.

**Fix:**
- state outer-join semantics;
- report orphans on each side;
- name the authority per field: the receipt for evidence and time, provenance for the decision and kind.

#### S4. Two completion mechanisms

`committee_records` and `meeting_records` use `is_completion` rows with zero-valued PK columns (D §6). `readings` and `filename_readings` use one status row per input. The committee and meeting producers are the same JSON and XML parsers whose `readings` row for that body already records that it was read (D §6.4–6.5).

**Fix:** one mechanism. Either a status row per input everywhere, or derive committee/meeting completion from the `readings` row at the same parser version. Either way, the zero-valued-PK trick and its nullable columns go.

#### S5. Versions are not defined as digests

D §7.1 makes the model SQL version and every registry version a SHA-256. It does not say how `parser_version`, `sniff_version`, `catalog_version` or the ingest-mapping version are computed. Hand-typed versions repeat M12.

**Fix:** each version is the digest of its code and data, for example the git tree hash of the parser folder plus the vocabularies passed in. House-naming's `parser_fingerprint()` (`retention/index/metadata.py:488-498`) is already a folder digest.

#### S6. `status.json` has no named reader

A §12 says "Every publish run writes `viewer-publications/status.json`", but no spec names a consumer. The repo's own rule: "a schema lands with a caller, or it doesn't land" (`docs/data-warehouse-design.md:186-187`).

**Fix:** name the reader (the weekly job, the canary report, a dashboard) or drop the file. The old consumer was `scripts/publication/pipeline_status.py`.

#### S7. The plan's keep list keeps two things the specs remove

P §8 keeps recovery `checked_put` and "recovery admission" unchanged:
- `checked_put` is the read-back pattern that A §7.1 removes (412 means "unchanged", with no comparison);
- admission checks `indexes/raw.json` identity (`packages/corpus_recovery/src/corpus_recovery/admission.py:196-229`), and the switch deletes the raw index.

**Fix:** move both to Repurpose and name the changes.

#### S8. The plan does work on layers it deletes

- **B12** repairs wrong `stored_sha256` index rows in place. That is worth doing only if the old capture path's raw writes depend on those rows. Check that first; otherwise drop B12.
- **B9** builds the weekly job against the old capture index "until D1 exists". Order B9 after D1, or base it on the LIST and receipts alone.

#### S9. Derivable or unused columns in `captures`

`publisher_requested` is determined by `mode` (always false for imports, D §5.2). `pointer` is "Informative". No derivation in D §7 reads the `h_*` header columns.

A §4.7 says "nothing derivable is stored". The cost is small in the lake, so keep each column only with a named use.

#### S10. The engine's MUST NOT list conflicts with parked news_lake

A §13 forbids lifecycle bookkeeping, table maintenance and resume machinery in the engine. P §7 keeps news_lake on the DocSpec backend, which needs all three (fork docspec, conflict 12). So the engine cannot conform while news_lake stays.

**Fix:** either A §13 gets a carve-out for parked consumers, or news_lake moves first.


#### S11. A §9.1 promises byte-for-byte ID parity that D's derivations cannot deliver

A §9.1: "The ID formulas keep today's exact inputs and serialization, so `source_id` and `document_id` match the current system byte for byte." The serialization does match (4.1 §3.1). The inputs do not:
- today one capture row yields several `(body, filename, url)` triples (Content-Disposition, final URL, query names, local path; `index/sources.py:119-145`), and D §7.4 yields one;
- today's `document_id` body set excludes HTML and `application/octet-stream` bodies (`bipartite.py:236-253`), and D §7.5 includes every real file, web pages included;
- D does not fix the basename decoding or which URL is `source_url`.

**Risk.** If P E3 generates golden vectors by running the new derivations, the vectors agree with themselves and hide the change; if E4 expects parity, it will report every affected document as unexplained.

**Fix.** Reword A §9.1 to "the same formulas and serialization"; generate E3's vectors from the Python functions on today's inputs; list "ID changes from changed inputs" as a known cause with its predicate in E4.

#### Checked and kept: these look heavy, but the reason holds

- **Weekly LIST against recorded sizes and MD5s (A §7.4).** It is exactly the check that catches M8.
- **Early skip by input identity, plus release-ID equality (A §10.3.2–10.3.3).** They catch different no-change cases.
- **The day-old guard on release retention next to the concurrency group (A §10.3.7).** It covers local runs, which A §12 cannot enforce.
- **Three physical body layouts, with a per-body HEAD of the older `.gz` (A §7.1, D §5.1).** Raw is never rewritten.
- **Link-key collision refusal (D §8.2).** One aggregation.
- **The orphan report that defers cleanup (A §8.7).** It is a good counter-example to bookkeeping.
