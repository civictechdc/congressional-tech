# Check of the bindings Note against the inventory and the code

**Subject:** `docs/plans/bindings-20261025.md` at commit `9a87e119` in `/Users/mikewolfd/Work/wt/ct-ticket-audit`, against the inventory (`docs/reviews/2026-10-24-design-review/package-inventory.md`), the specs and plan at `9a87e119`, congressional-tech code at `d9730967` (unchanged since), and docspec-rs at `d9c6719`. Read-only.

**Method.** Every file:line reference in the Note was checked mechanically: file exists, range inside the file, first and last line printed (`inv4_refs.py`, output `refs_out.txt`, both beside this file; project venv, `-I`). Then I re-read the code behind each Bind verdict and each adapter-work list, compared rows with the inventory's Keep/Repurpose items, its knowledge list (K1–K34) and its delete list, and diffed the specs and plan from `d9730967` to `9a87e119` for code facts.

**Short verdict.** The Note is the right shape and its congressional-tech references are almost all exact, but it is **not yet safe to drive the binding work as written.** Three rows say Bind where the code fails the contract they cite (so the contract work would be skipped), four docspec-rs references are wrong, the receipt cleanup is routed through a component whose contract forbids it, several adapter-work lists drop items the inventory found, and about a dozen Keep/Repurpose items and seven knowledge items have no usable home. All are mechanical to fix; §6 lists them in the order to fix them.

## 1. Accuracy

### 1.1 What checks out

- 62 congressional-tech references: every file exists and every range is inside its file, with one exception (below). Spot reads confirm the content: `r2.py:407-444` is `put_file`; `raw_archive.py:103-204` is `prepare_capture`; `raw_sync.py:298` is the replay condition; `cli/raw_sync.py:469` is the broken call; `records.py:483` is the `HMKP` strip; `matching/house.py:24-36` is the directory regex, the `hl` comment and the prefix map; `archive_links.py:19` is `SECRET_KEYS`; `http.py:129,185,188` are the gap, the 403 pause and the retry statuses.
- The coordinator's two fixes are right: `ca/parsers/file_wrapper.py` exists, and `apps/committee_youtube/src/committee_explorer/parquet.py:406-428` writes `bodies/sha256/...` under a local `stage` directory, not the raw bucket. (It also keeps a caller-supplied `sha256` when one is given, `:417-419`, so if those keys are ever bound, the body store must recompute the hash.)
- Counts reproduce: 23 incremental-catalog modules and 10,336 lines; viewer journal 3,417 + 4,066 (= 2,682 + 609 + 126 source; 2,180 + 657 + 567 + 662 tests); explorer and satellites *est.* 16,400 (7,569 + 1,441 + 1,498 + 5,878).
- `ds/storage.rs:132-141` is `table_properties()`; `ds/storage.rs:359-659` and `:858-929` are `write_batches_inner` and `append`; `ds/engine/export/pipeline.rs:687-697` is the offset-index gate; `url` 2.5.8 and `percent-encoding` 2.3.2 are in `Cargo.lock`.

### 1.2 Wrong references (with fixes)

| # | Note says | Problem | Fix |
|---|---|---|---|
| 1 | §3.3 C0: "`ds/catalog.rs:1163` resets `gc.enabled = false` **on every commit**" | False. `:1163` is inside `replace_baseline_snapshot` (`ds/catalog.rs:1115`), called only from lifecycle baseline compaction (`:950`). The per-table `false` comes from `table_properties()` at table creation. The inventory (4.5 §6) already corrected this plan claim | "`ds/storage.rs:132-141` sets `gc.enabled` and `delete-after-commit` to false on every table at creation; `ds/catalog.rs:1134,1163` flip `gc.enabled` only inside lifecycle baseline compaction" |
| 2 | §3.3 C0: remote write caps `ds/storage.rs:376-388` | Stops mid-expression; the row-group byte cap runs to `:391` | `ds/storage.rs:376-391` |
| 3 | §3.3 C3: `ds/export/pipeline.rs:445-702`, `child.rs`, `facets.rs`, `parent.rs` | No such file; the export lives under `engine/` | `ds/engine/export/pipeline.rs:445-702`; `ds/engine/export/pipeline/{child,facets,parent}.rs` |
| 4 | §3.3 C3: `HashingFile` (`ds/export.rs:658-697`) | `ds/export.rs` has 395 lines; `HashingFile` is elsewhere | `ds/engine/export.rs:658-697` |
| 5 | §3.3 C4: `ds/topology.rs:31-280` | No such file | `ds/engine/connected_components/topology.rs:31-280` |
| 6 | §3.3 C2: `batch.rs` | Ambiguous | `ds/storage/batch.rs` |
| 7 | §4 K8: `ca/acquisition/refresh.py:1-17` | File has 16 lines (the inventory's error, copied) | `:1-16` |
| 8 | §3.1 Recovery importer: `prepare_corpus_recovery_source_records.py:130-158` | Path lacks its folder; the range starts at the body read and cuts off the transport branch and the refusal | `scripts/corpus_recovery/prepare_corpus_recovery_source_records.py:136-164` |
| 9 | §3.1 Body store: "`body_files.retain_body_file` (`:105-159`)"; Receipt writer: "`bundles.separate` (`:28-117`)"; Sniff parser: "`document_evidence.document_body_fields` (`:221-248`)" | Each bare `:range` follows a different file's path, so it reads as a range in `r2.py`, `raw_archive.py` and `capture_inspection.py` | Write the paths: `ca/retention/body_files.py:105-159`, `ca/retention/bundles.py:28-117`, `ca/retention/document_evidence.py:221-248` |
| 10 | §3.4 Publish job: `packages/viewer_publication/client.py:266-391` | Path lacks `src/viewer_publication/` | `packages/viewer_publication/src/viewer_publication/client.py:266-390` |
| 11 | §7: `physical_body_object_key` "Where: the raw path"; "the fetcher chain"; engine pin "`docspec_client.verify_runtime`" | Too vague to act on | `ca/retention/body_keys.py:50-66`; the 64 MiB cap at `ca/transport/rust_fetch.py:134`, `ca/transport/source_capture.py:42`, `ca/acquisition/raw_sync.py:215`, `ca/cli/raw_sync.py:186`, `.github/workflows/capture-raw-sources.yml:343,346`; the self-descriptor check at `.github/scripts/setup-native-runtime.py:55-59` and the darwin-only pin at `packages/docspec_client/src/docspec_client/models.py:16-25` |
| 12 | §7: "The committee rule … `ca/matching/house.py:24-36` holds the right forms" | That file holds only the House `hs`/`hl` rule; the joint, commission and two-letter facts come from house-naming's committee table. And D §7.1/§7.5 now define a committee-code registry, so this is no longer a defect in anything to be bound | Delete the row, or move it to §4 K20 with both sources |
| 13 | §4 K34 lists three functions but cites two files | `recovery_fingerprint` is uncited | add `ca/retention/document_recovery.py:19-20` |

### 1.3 Wrong verdicts

| Row | Note | Should be | Why (code vs contract) |
|---|---|---|---|
| Archive expander | Bind, "None" | **Adapt** | A §7.2 at HEAD: "a refused expansion is recorded as the entry's outcome. Each member keeps its path and entry index"; D §5.2 puts `entry_index` on every `captures[]` entry. Today: member entries carry `original_path`, not `member_path`, and no `entry_index` (it sits only in `record['archive_members'][i]`, `raw_archive.py:155-179`); a refused member gets no `captures[]` entry at all, and refusals are recorded line-wide (`archive_processing`, `:150,201-203`); member links are parsed during capture (`:182-200`), which A §7.2 forbids; expansion is gated on today's `outcome == 'saved'` (`:121`) and reads the whole archive into memory (`:128`). The function also sits inside `raw_archive.py`, whose rest is deleted, so it must be lifted out. |
| C4 connected components | Bind, "The node cap refusal" | **Adapt** | A §13.4 requires 32-bit IDs and a node-count refusal; the kernel uses `Vec<usize>` parents and `String` keys (`topology.rs:32,126-127,185-221`), reads a lifecycle `ReleasePin` and requires `__docspec_file`/`__docspec_row` columns (`topology.rs:104-108`), and computes `document_id` and picks body edges by column name (`connected_components.rs:23-36`, `topology.rs:24-29`), which A §13 forbids and A §15.7 ratchets. Bind also contradicts the Note's own definition ("moves behind the component as is") when adapter work is listed. |
| Filename reader | Bind, with "a producer of 150–250 lines" | **Bind** house-naming as the parser; **Build** the producer | Same definitional clash. The producer also has to compute the effective filename from capture rows (D §6.3 work list, D §7.4's new precedence, `h_content_disposition`), make `catalog_version` a digest (D §7.1; house-naming's own `catalog_version` is the hand-typed `3.2.7`), keep the `invalid-source-url` retry (`ca/retention/index/schemas.py:485-490`), and decide `measure_keys` when congress is unknown. |
| "Kept as is" engine pieces | Bind | Move `Strict<T>` and `BackendCapability` to §6 | No target component uses them: `Strict<T>` lives in the retention inventory (`engine/retention/inventory/strict.rs`) and `BackendCapability` splits lifecycle field groups. The scope boundary, create-only writes and delete actor stay Bind, but the upload path beside them is unfit (see the missing C5 row, §2.1). |
| Publish job | Adapt | **Build, with one helper** | Only the flip helper exists. Pinning snapshots, the completeness gate, input identity, early skip, the content-addressed release ID, `inputs/<digest>.json`, `status.json` and `previous_release_id` are all new (inventory 4.3 §5). |
| Review recorder | Adapt | **Build, seeded** | What exists binds reviews to catalog group digests (`document_reviews.py:33-81`); only the 13-form list (`:18-21`) carries over. |
| Raw verifier | Build | **Build, seeded** | `.github/scripts/verify-capture-run.py`'s receipt→body checks are reusable for the R-check and the weekly LIST (inventory 4.3 §1). |

Two rows break the Note's rule "Every binding is proven by the component's contract test, never by the old code's own tests": the Archive expander's contract test is `ca-tests/test_archive_member_capture.py`, and the Sniff parser's is `ca-tests/test_document_recovery_gaps.py`. Say "cases lifted into the contract suite", or name the contract suite.

### 1.4 A design contradiction

**Receipt cleaner (§3.1) "uses the body store's conditional write".** The body store is create-only by contract (A §7.1), and plan B3's refusal matrix refuses "a write that is not create-only under `bodies/`, `receipts/` or `provenance/` … before any I/O". B0 overwrites receipts with `If-Match`. One of three fixes is needed:
1. a separate one-off receipt-rewrite adapter with `If-Match` and Content-MD5, outside the body store, deleted after B0;
2. or a refusal-matrix exception that names the receipt keys and expires when B0's verification records are complete;
3. or run B0 before B3 exists and say so in the plan's order (today it reads "B2's receipt rules, then B0, then the lock", and B3 is unordered relative to B0).

### 1.5 Adapter-work lists that drop inventory items

| Row | Missing items (inventory section) |
|---|---|
| Fetcher | Zyte bodies are base64 inside JSON and decoded in memory (`ca/transport/source_capture.py:66-122`), so "nothing is cut off" needs a streaming decode or an acknowledged ceiling (4.2 §5); only HTTP 200 counts as success today (`ca/retention/capture_inspection.py:37-41`) vs `good_fetch` 200–299; outcome names must map to D §5.2's six; the fetcher must record `sniffed_format` and `sniff_version` at fetch (A §8.3), so it calls the one sniff implementation; hashing and sniffing while streaming in source-fetch (4.4 §2.6); keep `json_links` discovery (`ca/parsers/archive_links.py:102-196`), which A §12 now requires ("follows what its fetchers discover … such as the documents an API response lists"); fix `cli/raw_sync.py:469` (only in §7) |
| Body store | Entry points missing from the routing list: `R2Store.put_pdf_file` (`r2.py:446-450`), `_Acquisition.put_body` (`raw_archive.py:362-391`, whose 412 path re-reads and compares at `:380-381`), `store_public_body` and `RawStorage.put_body` (`raw_storage.py:237-278,823-830`), recovery `checked_put` and `GuardedStore` (`packages/corpus_recovery/src/corpus_recovery/transfer.py:26-46,82`). Store the original `Content-Type` instead of `application/gzip` (`r2.py:121-123`); drop the `.pdf` side copy for new PDFs (`store_uncompressed_pdfs`, `body_files.py:149-153`). **Senate `seed_fetch` is a local layout writer like the explorer's**: it writes `bodies/sha256/<aa>/<sha>.pdf` into a local cache and the weekly-tables workspace (`ca/retention/senate.py:45-56`), and labels any binary body `.pdf`. Treat it like the explorer writer. The e2e harness is deleted with `tests/e2e` (§5), so it needs no routing |
| Receipt writer | Fields: `sniffed_format`, `stored_md5` and `stored_bytes`, writer identity (`job`, `commit`, `lockfile_digest`), `run_id` (today `source_file`), `member_path` (today `original_path`), the six-value `outcome`, the provider's status kept apart; date-shaped receipt keys (UTC write date); `Content-Disposition` and `Retry-After` in the allowlist; null member media type instead of the extension guess (`raw_archive.py:166-170`) |
| Recovery importer | Date-shaped receipt keys (today `receipts/documents/import/<run>`, `scripts/corpus_recovery/dispatch_corpus_recovery_import.py:187`); drop `download_state`, `preserve_download_state`, `source_file` (`packages/corpus_recovery/src/corpus_recovery/assemble.py:53-59,92-94`); no local paths in `recovery_evidence.acquisition` (`prepare_corpus_recovery_source_records.py:129,167`); drop `checked_put`'s read-back and the GET before each PUT (`transfer.py:40-45,129-134`); bare `<sha>` layout; admission's `indexes/raw.json` checks go (`admission.py:196-236`); `inventory.scan_receipt_history` reads `captures` (`inventory.py:139-267`); write `prior_access_category`, because D §7.8 fails the build on an unmapped category and corpus_recovery imports carry none (4.4 §2.3); B6's code identity (reuse `viewer_publication/release_identity.py` `locked_runtime`/`source_files`) |
| Engine pin check | The hosted check that compares only the revision (`.github/scripts/setup-native-runtime.py:55-59`), `check-native-runtime.py`, and the runtime publisher `packages/viewer_publication/src/viewer_publication/publish_docspec_runtime.py` (Keep in 4.3) |
| Sniff parser | Add the format values D §6.2 lists that do not exist today (`json`, `vtt`, `m3u8`, `text`, `image`, `warc`, `empty`; `docx` split from `zip`); one implementation shared with the fetcher |
| HTML and XML parsers | The generic page facts D §6.2 requires (`title`, `heading`, `text_bytes`, `link_count`, `link_text_bytes`, `content_date`, `xml_root`, and the new `text_head`) exist nowhere (4.2 §5). "Add `witness-document`" contradicts D §6.2 at HEAD, which still lists `li`, `tr`, `meeting-document`, `document`: change D first or drop it from the row |
| Committee and meeting parsers | Strip the four-letter `meeting-id` prefix (D §7.5 now says so; today's defect is `records.py:483`); `nochamber`/`joint` chamber values (`ca/acquisition/meetings.py:43,125-127`); the committee detail endpoint has no congress, so it yields a completion row (`committees.py:77-79`); `parent_system_code` fallback from `ca/matching/committees.py:11-13,53-57` |
| Fingerprint parser | Seeds exist: `ca/retention/pdf_tools.py` (bounded Poppler process; `reader_versions()` for the version digest) for the pinned PDF text extractor, and `archive_members.iter_zip_members` for D §6.2's new "read from the archive when it was not [expanded]" ZIP case |
| C0 | The plan's C0 defers to this row and names "hashing while writing, no HEAD or re-download of immutable files", which the row omits; also remove `test_hooks.rs` (always compiled, `engine.rs:84-85`), the 56 `stop_after` sites and the `cfg(not(test))` branches, since A §15.7's ratchet now covers the engine |
| C2 | Long-lived table creation with D §6 properties and row-group sizes (131,072 / 65,536 rows, 128 MB files); detached mode drops commit requirements (`ds/catalog.rs:1347-1356`), against A §8.1 |
| C3 | Fold shape: today `List<Struct<field, values: List>>` (`ds/export.rs:36-38`) vs D §4's one value per element; facets over list columns and non-hidden rows only; the release manifest; lift `ds/engine/export/validation.rs` (output checks) and `ds/engine/sql_validation.rs:169-220` (volatile-function refusal, A §10.2); the dormant `pipeline/slice.rs` as the page-read oracle |
| C8 | The `url` crate implements WHATWG URL, not RFC 3986 §5; the RFC 3986 §5.4 vectors decide whether it can be used (4.5 §5.7) |
| Reader | Lift `rangeFile` (`catalog-v6.ts:75-102`) and `compareText` (`:112-118`) before `catalog-v6.ts` is deleted; the pointer read in `publication.ts:27-49`; the schema-version set (`data-source.ts:8-12`) and `DecompressionStream` (`data-source.ts:26-29`) patterns |
| Publish job | Write `previous_release_id`; decide who uploads release files, the Python helper or the engine's create-only boundary (A §13.5) |
| PDF copier | Drop the in-memory variant (`pdf_backfill.py:132-156,226-237`) and the ZIP-member branch of `migrate_pdf_bodies_to_uncompressed` (`raw_storage.py:330-354`); drop the exclusion-gate calls (`pdf_backfill.py:170-180`); the job contains no delete call (inventory M2) |

## 2. Coverage

### 2.1 Keep or Repurpose items with no binding row

| Item | Inventory | Proposed row |
|---|---|---|
| House and Senate meeting-inventory fetchers (`ca/acquisition/house.py`, `senate.py`, `house_fallback.py`; decide `house_sites.py`, `gpo.py`) | 4.2 §2.3 | A §8.6 at HEAD still sources `meeting_records` from "the House and Senate meeting inventories, all fetched through the raw writer". The Note puts all explorer code in §6, so nothing binds these fetches. Add them as fetcher clients (Adapt), or change A §8.6 |
| **C5 release upload** (`ds/storage/remote/objects.rs`: `upload_file` uses 8 MiB multipart and BLAKE3 readback, `:555-636`; test builds re-read every upload, `object_io.rs:258-262`) | 4.5 §2.5 | Adapt from `create_bytes_by_key` (`objects.rs:534-541`): Content-MD5, single PUT at release size, 412 → one HEAD of the ETag. §3.3 has no C5 row although the plan's C table lists C5 |
| JSON parser (`json` readings, D §6.2) | — | A §6 lists it among the parsers; no row. Build (the Congress.gov models seed the committee/meeting part only) |
| `congress_shared.storage` (`R2Config`, `connect_r2`) | 4.2 §2.15 | the client under the body store's R2 adapter |
| `ca/parsers/source_family.py` | 4.2 §2.9 | Receipt writer: the receipt `family` field; recheck-interval key |
| `ca/cli/raw_sync.py` capture entry (`capture_sources`, `connect_storage`) | 4.2 §2.13 | the capture job's command (Adapt; catalog modes deleted) |
| `derive_body_key` (`ca/retention/raw_schemas.py:179-193`) and the shard check `body_key_digest` (`ca/retention/body_keys.py:11-18`) | 4.1 §2.2 | Bind (logical body key, the ID input; key validation). They were on the old plan's keep list, which is gone |
| `models/documents.DocumentLink` | 4.2 §2.11 | HTML and XML parsers: the link struct |
| `document_evidence.read_retained_body` (`:130-163`) | 4.1 §3.6 | Parsers: the body reader, with the `''` suffix and `Content-Encoding` |
| Site document pages and labels (`FilenameEvidence.tsx`, `filename-presentation.ts`, `navigation.ts`, `provenance.ts`) | 4.3 §2.3 | Reader/site, Adapt (date labels per A §11.6, recovery kind, link-key navigation) |
| Workflows: `capture-raw-sources.yml` → capture job (drop `--max-file-mib 64` at `:346`, capture-only credential); `update-data.yml` committee and meeting fetches → capture; `deploy-pages.yml`, `validate-explorer.yml` keep and gain the contract test; `.github/docspec-remote.json` (Basin catalog URI); `.github/scripts/finalize-raw-source.py` (`If-Match` status pattern) | 4.3 §7, §2.12 | Orchestration rows (A §12) |
| `scripts/webharvest` | 4.4 §2.4 | Keep, upstream of the recovery importer, and K17's samples; today it appears nowhere |
| Dormant code with proposed uses (`acquisition/documents.py` + `transport/document_probe.py`; house-naming `archive/tools/` and `bill_codes.py`; `compact_readings.deduplicate_reading_table`; docspec-rs `pipeline/slice.rs` and `examples/r2_*_probe.rs`; the `catalog/`, `raw/`, `review/` facades) | 5.4 | The Note's own rule 8 says "Dormant code gets a use or a reason before it goes", but none of these is mentioned. Add a short dormant table |
| The 86 published assistant reviews (`document-review-identities.json`) | 4.3 §2.11 | Review recorder: migrate as `kind_override` on body link keys, or drop (owner decision) |

The Note also adds components that A §6 does not list (Engine pin check, PDF copier, Receipt cleaner, ID golden vectors, F0 converter, Origin rules). That is fine for one-offs, but Origin rules (A §11.7) and the engine pin (A §12) are lasting; either add them to A §6 or mark them as configuration.

### 2.2 Knowledge items (K1–K34)

All 34 appear in §4. These are placed where the target contract cannot hold them, so seeding them as data is not enough; each needs a spec change or a decision to drop it:

| Item | §4 places it in | Problem at HEAD |
|---|---|---|
| K14 PDF and image completeness | Sniff parser rules | No `readings` field records a tail check, and D §7.3 makes any complete 2xx PDF real |
| K19 House XML: `remove-date`, `witness-document`, description labels | HTML and XML parser rules | D §6.2's link struct has no `remove_date`; the grouping ancestors omit `witness-document`; XML link `text` will be empty without the description rule. (The event-ID prefix did land, in D §7.5) |
| K22 Kinds from publisher type codes | Facet rules | D takes facets only from filename readings and reviews; no facet rule exists to seed. Plan E4 does not list it as a parity cause either |
| K23 Recovered filenames for legacy cache names | Recovery provenance (plan B7) | No provenance kind carries a recovered name (D §5.3 has `recoveries`, `url_variants`, `reviews`, `verification`), and B7 reconciles `accepted.json` recoveries, not legacy cache names |
| K24 MODS event IDs | Content-date and meeting rules | D §7.5's `meeting_ref` sources omit MODS |
| K31 Link context through redirects, never from feeds | HTML and XML parser rules | It is a model join rule (D §7.10), not a parser rule, and D §7.10 still matches only the endpoint's `url_key` with no feed exclusion |
| K17 non-wrapper repairs (concatenated URLs, `ttps://`, `mailto:`, the democrats-transportation `&download=1` route) | URL-wrapper registry | D §7.2's `unwrap` names its wrapper patterns as a definition, not as examples; concatenated hrefs yield several targets from one `href`, which needs a model rule since D §6.2 keeps `href` as written. Add the missing seed sources too: `scripts/webharvest/webharvest_committee_map.py:15,26-65` and its tests, `archive_links.py:86-99`, `document_links.py:33-48` |
| K21 Recovery kinds | Recovery-kind registry | corpus_recovery imports carry no `prior_access_category`, so "an unmapped category MUST fail the build" (D §7.8) fails all of them; the registry needs a rule for the absent category, or the importer must write one (§1.5) |

Minor placement points:
- K9's JSON-LD (`page_content.py:45-65`) belongs with the HTML parser's embedded-data links, like Next.js; the Congress.gov JSON discovery belongs with the fetcher (A §12).
- K32's METS is data in the source-record-roots registry, but D's row text lists only MODS and PREMIS; add METS there.
- The witness-list conflict (a document today, `document_evidence.py:209-212`; a source record by D §7.1's "witness records") must be settled when that registry is seeded.

These K rows lack file references the inventory has: K11 `ca/matching/house.py:8-39`; K12 `ca/acquisition/meetings.py:40,43,89-97,114-129`, `committees.py:63-65,77-79`; K18 `document_links.py:97-161`, `archive_links.py:208-215,226-228`, `page_content.py:25,38`; K21 the 2026-10-15 receipts and `prepare_corpus_recovery_source_records.py:136-164`; K23 `document_evidence.py:125-127,360-377`; K24 `gpo_hearings.py:14-15,36-55,103-106,166`, `ca/parsers/gpo.py:108-112`; K25 `senate_page.py:30-37,43,50,905-913`; K27 `corpus_recovery/html.py:9-56`; K28 `matching/house.py:47-48`; K31 `ca/retention/index/document_sources.py:143-229`; K15 also `ca/parsers/house_documents.py:16`.

### 2.3 Delete list (§5) gaps

| Missing from §5 | Size (src + tests) | Inventory |
|---|---|---|
| The second production input substitution, `ca/retention/source_capture_inputs.py:61-74` (substitutes a local `.cache/docspec-catalog/captures-0.parquet` for remote capture batches) | inside the incremental catalog | 4.1 §4; it is live until the switch, like the `raw_storage.py` one §5 removes now |
| `scripts/publication/pipeline_status.py` | 352 + 298 (keep the heartbeat checks only if capture keeps a heartbeat) | 4.3 §2.13 |
| Review publication path: `filename_reviews.py`, `apps/site/scripts/stage-document-reviews.py`, `document-review-*.json`, `reviews.ts` | 188 (+907 JSON) + 183 | 4.3 §2.11 |
| `ca/cli/document_index.py` | 71 + 2 test files | 4.2 §2.13 |
| docspec_client: the archive-only builders' test (`test_export_policy.py`, 321); the pure-Python BLAKE3 (107), which goes only by adding the `blake3` dependency; the shims (124), only after news_lake moves | — | 4.4 §2.2 |
| Docs to rewrite at the switch: `apps/site/FILENAME-VIEWER.md`, `.github/workflows/raw-source-tables.md` | 592 md | 4.3 §6 |
| Measured sizes for the "at cut" row: CLI catalog modes ≈ 155; `replay/` 346 + 980 shared; `recovery_queue.py` 139 + 58; `retained_import.py` 47 + 119; ExportPin 1,382 + 383; compaction scripts 366 + 332; `verify-capture-run.py` 323 + 497 | — | 3.2 |
| docspec-rs conditional cuts: retention inventory 7,080 + 7,342 and the UDAFs 2,112 (news_lake and the explorer) | — | 4.5 §6 |

## 3. Bind rows unfit for their contract

1. **Archive expander** vs A §7.2 and D §5.2: no `entry_index` on entries, refused members unrecorded as entries, capture-time link parsing, today's outcome gate (§1.3).
2. **C4** vs A §13.4 and §13's MUST NOT: `usize`/`String` IDs, no node cap, lifecycle-bound input, `document_id` and body-edge names in the engine (§1.3).
3. **Filename reader** vs D §6.3 and D §7.1: the parser fits; the component does not exist yet (§1.3).
4. **"Kept as is"**: `Strict<T>` and `BackendCapability` serve no component; the create-only module's upload path fails A §10.3.4 (§1.3, §2.1 C5).

The remaining Bind-like verdicts (ID golden vectors as Seed, origin rules as Adapt) are right.

## 4. Code facts in the specs and the plan

The new A §6 table, principle 8 and the plan's component framing are clean. Remaining leaks:

| Where | Text | Suggested change |
|---|---|---|
| A §13 (new) | "The engine's lifecycle store, which news_lake still uses, is outside this specification." | "Engine features this system does not use are outside this specification." |
| A §8.4; D §6.3 (`source_url`, `catalog_version`, `status`, `fields`, scalars); D §7.1 committee-codes row | name `house-naming` and describe its behavior | "the filename reader" / "the filename parser"; the binding belongs in the Note (pre-existing, but principle 8 now makes it a leak) |
| Plan B6 | "the `uv.lock` digest, refusing uncommitted changes under `packages/` or `scripts/`" | "the lockfile digest, refusing uncommitted application code" (the plan says it "names no existing files") |
| Plan D3 | "a producer that runs `house-naming`" | "a producer that runs the filename parser" |
| Plan §3 | `.venv/bin/python scripts/dev.py test <lane>`, `scripts/check` | Fine to keep: these are runner instructions, not bindings |
| Plan §1, B7, B15 | `accepted.json`, a receipt key pattern | Fine: these are raw-bucket objects (data), not code |

## 5. Verdict

The Note can drive the binding work **after one revision pass**. As written, it would:
- send the archive expander and C4 forward as Bind with no contract work, although both fail their contracts;
- route B0 through a component whose refusal matrix forbids it;
- leave the House/Senate inventory fetches, C5's release upload and the JSON parser with no owner;
- let seven knowledge items be "seeded" into places that cannot hold them.

The congressional-tech references are trustworthy (61 of 62 exact); the docspec-rs references need the four path fixes before anyone opens those files.

## 6. Fix order

1. Change the three wrong Bind verdicts (archive expander, C4, filename reader) and move `Strict<T>`/`BackendCapability` to §6 (§1.3).
2. Resolve the B0 / body-store contradiction (§1.4).
3. Fix the docspec-rs references and the C0 claim (§1.2 #1–6).
4. Add the missing rows: House/Senate inventory fetchers (or change A §8.6), C5, JSON parser, `derive_body_key` and the shard check, workflows, site pages, `congress_shared`, `source_family`, the capture CLI, webharvest, dormant uses (§2.1).
5. Complete the adapter-work lists (§1.5), starting with the receipt writer, the recovery importer and the fetcher (raw-data impact).
6. Decide each unlanded knowledge item: change D or drop it explicitly (§2.2).
7. Add the §5 gaps (§2.3) and the remaining small reference fixes (§1.2 #7–13).
8. Clean the code facts from A §13, A §8.4, D §6.3/§7.1 and plan B6/D3 (§4).
