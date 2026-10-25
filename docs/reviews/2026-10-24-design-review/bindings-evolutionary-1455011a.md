# Bindings Note: evolutionary-refactoring audit

**Subject:** `docs/plans/bindings-20261025.md` at `1455011a` (`/Users/mikewolfd/Work/wt/ct-ticket-audit`), the code it binds (congressional-tech `d9730967`, docspec-rs `d9c6719`), and the specs and plan at `1455011a`.

**Mode:** Audit, read-only. Skill: evolutionary-refactoring.

**Verdict.** The Note can drive the binding work now for most rows. Six Adapt rows would carry AI-made over-engineering or a workaround whose reason is gone; the receipt writer and recovery-importer rows sit on the first step of the plan's order of work (B2), so settle those two before B2 starts. Three dormant-code proposals are wrong, and one evidence reference dangles.

**Score: 82 / 100.**

| Area | Weight | Score | Why |
|---|---:|---:|---|
| Accuracy of references and claims | 25 | 24 | 162 of 162 references resolve and are in range; spot reads match. One dangling evidence link; three wrong dormant uses |
| Verdicts against the contracts | 25 | 19 | The last round's wrong verdicts are fixed. Six Adapt rows should be reshaped toward smaller builds (§2) |
| Coverage (rows, K items, delete list) | 20 | 18 | All 14 missing rows, K1–K34 and the delete gaps landed. Gaps: the Senate meeting source, the captures-ingest engine input, the relist watermark |
| Fitness as a working document | 20 | 15 | Adapter cells restate spec rules; adapters are not separate rows; the shared version-digest helper has no row (§3) |
| Consistency with the specs and plan | 10 | 6 | A few names in the specs are still open: the URL-wrapper definition, the Senate meeting source, A §13.1 inputs |

**Evidence.**
- `inv5_refs.py` (beside this file; project venv, `-I`) extracted every `file:lines` token in the Note, resolved each against the files git tracks in both repositories, and range-checked it: 162 of 162 resolve uniquely and are in range. Output is in `refs_out.txt`.
- I read the code behind each Adapt and Bind row named below, the spec sections each row cites, and the plan diff from `9a87e119` to `1455011a`.
- Not run: no tests, builds or network, by rule.

## 1. Did the fixes land?

All 13 reference fixes landed, along with:
- the verdict changes: archive expander Adapt; C4 Adapt; filename parser bound as is with the producer as Build; publish job Build with one helper; review recorder Build, seeded; raw verifier Build, seeded;
- the receipt rewriter outside the body store, consistent with plan B0's tool;
- `Strict<T>` and `BackendCapability` moved to §7;
- the 14 missing rows; the completed adapter lists; the delete-list gaps; the dormant table.

The K rows now land in real spec homes: `intact`, `remove_date`, `witness-document`, the publisher-kinds, URL-repairs, feed-roots and archive-limits registries, `recovered_filename`, readings `meeting_refs`, and the redirect and feed rules in `linked_from`.

### Still wrong or missing

| # | Where | Problem | Fix |
|---|---|---|---|
| 1 | Status (line 11) | "The evidence for every row is in [[INVENTORY]], by section, **and its check of this Note**." The check (`bindings-check.md`) lives in a scratch folder, not in the repository, and §9 has no reference to it | Commit the check beside the inventory and add it to §9, or drop the phrase |
| 2 | §5 Dormant: `acquisition/documents.py` + `transport/document_probe.py` → "seed for the queue's first fetch" | This would add a second fetch path (ranged GETs that follow landing pages) beside the fetcher, against binding rule 1. The model already handles landing pages (file-shape rule plus links), and the queue fetches link targets with the fetcher | A one-off labeling aid for the S sample and a pre-check before each B14 re-fetch, then delete; or delete with that reason |
| 3 | §5 Dormant: house-naming `archive/tools/` and `bill_codes.py` → "seeds for the publisher-kind and file-shape registries" | `archive/tools/` diffs filename metadata between parser versions (`compare_filename_metadata.py`: "Audit both directions of saved native filename outputs"). `bill_codes.py` holds GovInfo bill types and versions. Neither is registry content of those kinds | `archive/tools/`: the review step before the profile moves to a new `catalog_version`. `bill_codes.py`: validate `measure_keys` types and split `BILLS-…` stems in the filename-reader producer |
| 4 | §5 Dormant: `compact_readings.deduplicate_reading_table` → "the rebuild-equivalence check for `readings`" | A keep-latest dedupe (`compact_readings.py`: `to_pylist()` then dict by key) **hides** duplicate rows, so as an equivalence check it would agree with itself. It also returns the table unchanged when key columns are missing. My inventory's earlier suggestion of it as a fixture helper was wrong for the same reason | **Delete.** The check is engine SQL: PK `count(*) > 1` plus `EXCEPT ALL` in both directions between the rebuilt and appended tables |
| 5 | §3.1 Meeting-inventory fetchers | A §8.6 and D §6.5 source `meeting_records` from "the House and Senate meeting inventories", but Senate pages carry no event ID (today it comes from title/date association, `ca/acquisition/senate.py:9-15`), while D §6.5's `event_id` is required. No parser row produces Senate meeting records | Decide: drop Senate inventories from A §8.6 (Senate meetings come from Congress.gov JSON from June 2019), or define an association rule. Record the decision in the row |
| 6 | §3.2 Captures ingest, "the ingest mapping in SQL on the engine" | A §13.1 gives the engine Iceberg and Parquet inputs only; receipts are gzip NDJSON. Older shapes have mixed-type `pointer` arrays and open-ended header objects, so plain schema inference will not hold | Add a receipt input to C1: DataFusion's NDJSON reader with an explicit schema, reading the odd fields as raw strings; or a short normalizer seeded from `ca/retention/index/records.py:224-259`, chosen by a measurement in M2 or D1. Without it, someone hand-rolls a receipt parser |
| 7 | §3.2 Committee and meeting parsers, "no JSONL state" | The incremental relist (`ca/acquisition/meetings.py:56-61,77-78`: `updateDate` with a two-day overlap) keeps its watermark in that state, and the row removes the state without naming its replacement | Derive the window from the latest good fetch of the listing endpoint in `url_state`/`captures`; say so in the row |
| 8 | §4 K17 | Seeds `lis.gov` t2GPO and `webarchive.loc.gov` into "the URL-wrapper registry", but D §7.2's `unwrap` still enumerates exactly five wrapper families as its definition | Make D §7.2 read "such as" (the registry is data), or list the two |
| 9 | §4 K29 | The filename-parameters registry (D §7.1) has no seed reference | `ca/retention/index/sources.py:38-54` (`url_document_names`) |

## 2. Lens on the bound code

Each finding ties to an observed failure or change cost. **Confirmed** means the code shows it; **hypothesis** means it needs the named check.

### 2.1 Adapt rows that carry over-engineering or a dead workaround

**R1. Receipt writer binds `bundles.separate`, an offline migration helper. Delete it from the target writer; build lines from typed fetch results. Confirmed.**
- **Evidence:** `ca/retention/bundles.py:1-7`: "This is an offline migration helper, not another acquisition or normalization path." Yet it runs on every live capture (`raw_archive.py:115,171`). It walks arbitrary nested JSON, decodes base64, refuses "noncanonical base64" (`bundles.py:28-117`), and exists for state files with embedded bodies (`RawContent`).
- **Mechanism:** the target fetcher hands over a spooled file plus metadata, and D §5.2 fixes the line's shape. Keeping a generic tree walker means every new receipt field passes through pointer bookkeeping that no longer has a source.
- **Recommendation:** Receipt writer = Build, seeded from `prepare_capture`'s field list (`raw_archive.py:103-204`). Move the member loop to the archive expander. Delete `bundles.py` with the old capture path; older pointers are read by the ingest mapping in SQL.
- **Verify:** the line-schema suite run on one capture of each family.

**R2. Fetcher keeps the in-memory reservation model. Delete it; keep a disk-spool bound. Delete the classification-driven retry list. Confirmed.**
- **Evidence:** `ca/acquisition/raw_sync.py:36-42,73-107`: "Body buffer must hold three maximum file sizes plus 1 MiB"; the spool must hold 7/3 of the maximum. That is the cause of the 64 MiB cap (inventory M9). `RETRY_OUTCOMES` (`raw_sync.py:31-33`) retries `html`, `parse_failed`, `challenge` and `unsupported_format`, so capture decides what counts as a document (inventory O14).
- **Mechanism:** the row says "lift" the reservation. Lifting a formula that multiplies the maximum body size keeps the coupling that made 5 GB bodies impossible.
- **Recommendation:** with bodies spooled and gzip streamed, the only budget left is disk: in-flight files × maximum size, or a spool quota. Retries follow the six outcomes and D §7.7.
- **Verify:** a fetch-suite case with a body larger than the memory pool.

**R3. Body store binds the `R2Store` and `LocalStore` classes. Keep `put_file`'s logic; build a small store with two adapters. Confirmed.**
- **Evidence:** `R2Store.put` (`r2.py:338-398`) branches on four key prefixes (native manifests with a 128-thread pool and a 16,384-entry memory cache, `:340-375`; body results; bodies; `indexes/` with `If-Match`). The class also carries derived-file custody and a 64-worker `prefetch_immutable`. `LocalStore` (`catalog_cache.py:23-136`) carries catalog-manifest, index-selector and derived-file methods, and overwrites by default.
- **Mechanism:** binding the classes binds their accretions; the refusal matrix then has to police paths that should not exist.
- **Recommendation:** about 60–80 lines (*est.*): `put(key, file, media)` returning `stored` or `unchanged`, over boto3's `put_object(IfNoneMatch='*', ContentMD5=…)`, plus a local adapter that opens files with `'xb'`. Lift `put_file` (`r2.py:407-444`). Delete both classes with the old layers.
- **Verify:** the refusal matrix.

**R4. Recovery importer keeps RecoveryGuard and the custody machinery. Delete them; rebuild the importer as a thin client of the receipt writer and body store. Confirmed.**
- **Evidence:** `packages/corpus_recovery/src/corpus_recovery/guards.py:1-4`: "A mutable object or shared pointer must call shared_commit immediately before its conditional write." `RecoveryGuard` re-checks code pins and polls GitHub for active capture writers within 30 s of each write (`guards.py:36-60,80-149`). `checked_put` reconciles lost acknowledgments and reads back every write (`transfer.py:26-46`). The shared mutable pointer was `indexes/raw.json`, which the switch deletes.
- **Mechanism:** with create-only bodies, run-unique receipt keys and append-only provenance, nothing remains for a concurrent capture writer to corrupt. A retry of an uncertain PUT returns 412. The row as written ("Adapt corpus_recovery") would also keep a second receipt-line builder (`assemble.py`) and a second body loop (`transfer.py`) beside the bound ones, against binding rule 1.
- **Recommendation:** Recovery importer = Build, seeded:
  - keep the timestamp basis (`scripts/corpus_recovery/prepare_corpus_recovery_source_records.py:136-164`), GovInfo member handling (`govinfo.py`) and batch preparation;
  - write `mode = retained_import` lines through the receipt writer, bodies through the body store, and decisions as provenance;
  - delete `guards.py`, `acknowledge.py`, `admission.py`, `checked_put`, and `write_recovery.reconcile_lost_acknowledgment`;
  - B6's code identity replaces the pin re-checks.
- **Note:** the plan's old keep list and my own inventory kept RecoveryGuard; its reason is gone.
- **Verify:** recovery fixtures in S, plus two concurrent import runs on disjoint batches.

**R5. HTML and XML parsers adapt modules the committee explorer still imports. Build a new parser, seeded; leave the explorer's modules alone. Confirmed.**
- **Evidence:** `document_links`, `archive_links`, `house_evidence` and `house_documents` are imported by explorer code that §7 keeps: `adapters/house.py`, `parsers/senate_page.py`, `parsers/committee_discovery.py`, `parsers/committee_pages.py`, `matching/house.py`, `acquisition/house.py`. Their current contract is the opposite of D §6.2's: document-like links only, resolved, de-duplicated (`document_links.py:121-161`), host-gated routes (`:127`), and scope-filtered XML links (`archive_links.py:242-245`).
- **Mechanism:** adapting them in place either breaks the explorer or forks one function into two contracts behind flags (boolean accumulation).
- **Recommendation:** a new lxml pass of *est.* 150–250 lines that records every link as written, with `group_path`. Lift:
  - the element set (`document_links.py:97-161`);
  - `<base href>` and meta refresh;
  - embedded data (`page_content.page_trees`, `:8-42,45-65`);
  - entity-safe parser settings (`archive_links.py:226-228`);
  - the BOM strip (`ca/parsers/xml.py`);
  - House XML group selectors as generic `group_path`.

  Verdict: Build, seeded. (The JSON parser is already Build.)
- **Verify:** the parser re-run invariant plus lifted cases from `test_circular_document_links.py` and `test_document_link_resolution.py`.

**R6. C3 adapts the lifecycle export framework. Build the writer loop on the parquet crate; move facets and folds into model SQL. Hypothesis, high confidence.**
- **Evidence:** `build_writer_properties` (`ds/engine/export/pipeline.rs:672-699`) is already the parquet crate's `WriterProperties`. That type covers every per-file and per-column setting D §8.1 needs: column encodings and dictionaries, page row limits, write batch size, `created_by`, row-group row counts, offset and column indexes. The rest of the path is lifecycle export: parent/child unnesting (`pipeline/child.rs`, 424), facet accumulation (`facets.rs`, 251), field groups joined by occurrence identity, and byte-based flushes (`pipeline.rs:605-616`). D §8.1 instead makes every release file its own ordered relation, with `facet_counts` as counts over `list`, and folds as SQL struct aggregates.
- **Mechanism:** adapting means every new release file is modeled as parent and child in Rust, rather than added as one SQL relation plus one writer-settings entry.
- **Recommendation:**
  - Keep `HashingFile` (`ds/engine/export.rs:658-697`, with SHA-256 and MD5 replacing BLAKE3), the settings builder extended per column, `export/validation.rs` and `sql_validation.rs:169-220`.
  - Build the multi-output loop: re-batch to the pinned size, refuse non-unique sort keys, `ArrowWriter` into `HashingFile`, write the manifest.
  - Leave `child.rs`, `facets.rs` and `parent.rs` to news_lake.
- **This reverses my inventory's top-ranked repurpose** (1,500–2,000 lines saved). That estimate assumed the release needed child tables and facets from the export layer; D §8.1 no longer does.
- **Verify:** the C3 determinism suite on a two-output job; compare the line count of the new loop with the lifted path.

**R7. Origin rules adapt a 722-line bespoke Cloudflare API tool. Keep the rules as data; apply them with the platform tool. Confirmed.**
- **Evidence:**
  - Once the firewall rules go, two API calls remain: R2 CORS and one response-header ruleset (`apply_r2_edge_rules.py:265-288`).
  - The ruleset call PUTs the zone's whole phase entrypoint, replacing any other rule in that phase (lessons O12).
  - The Python simulator diverged from the deployed rule until `3df0d3b3` fixed `/exports/*`.
- **Recommendation:**
  - Keep `infra/cloudflare/congressional-data-r2-edge.json` and `verify_live_edge`'s live checks.
  - Apply with `wrangler r2 bucket cors` and a rule-level ruleset update, or a Terraform `cloudflare_ruleset`; measure before choosing.
  - Delete the planner and the `evaluate_*` simulators.
- **Verify:** the live-edge check after an apply leaves other zone rules intact.

**R8. Committee and meeting parsers mixes fetch loops into a lake-producer row. Split it. Confirmed.**
- **Evidence:** the row lists `ca/acquisition/meetings.py` and `committees.py` (pagination, API key, JSON→XML fallback on 500) beside `models/congress.py` and `parsers/congress.py`, and its adapter list mixes fetch items ("API key in a header") with parse items (completion rows, prefix strip).
- **Recommendation:** a "Congress.gov API fetchers" row beside the meeting-inventory row (fetcher clients, capture job), and a parser row with only the models, `meeting_from_xml` and the House XML readers.

**R9. Meeting-inventory fetchers: "no state files of their own" breaks the explorer that §7 keeps. Reshape. Confirmed.**
- **Evidence:** `acquisition/house.py` and `senate.py` write the explorer's state JSON and CSVs (`update-data.yml`), and the committee explorer is kept (§7).
- **Recommendation:** say either that the explorer's inputs are derived from raw or `meeting_records` after the switch, or that the explorer keeps writing its own outputs from the same fetch results. Otherwise the change is two synchronized edits across the archive and a parked product.

**R10. Engine pin: one policy held in three places. Keep the policy; reshape to one pin file. Confirmed.**
- **Evidence:** `QUALIFIED_DOCSPEC_RUNTIME` (`packages/docspec_client/src/docspec_client/models.py:16-25`), the hosted check (`.github/scripts/setup-native-runtime.py:55-59`) and the runtime publisher each hold part of it, and they drifted (darwin digest only; the hosted check compares only the revision).
- **Recommendation:** one committed file `{revision, sha256 per OS}` read by setup, `check-native-runtime.py` and `verify_runtime`; remove the PATH fallback.

### 2.2 Build rows that roll their own

**B1. C8 URL functions: evaluate an RFC 3986 crate before hand-writing. Hypothesis.**
- `url` 2.5.8 is WHATWG. `iri-string` implements RFC 3986 §5 reference resolution and §6.2 normalization, which are exactly A §13.8's two functions; it is not in `Cargo.lock` today.
- Run the RFC 3986 §5.4 vectors and the `http_url` golden vectors against `iri-string` first, then `url`. Write resolution by hand only if both fail.

**B2. Captures ingest:** see §1 item 6. Use DataFusion's NDJSON reader before writing a receipt parser.

**B3. C4: keep the 45-line `DisjointSet`.** `petgraph` 0.8.3 is already in `Cargo.lock` with a `UnionFind<u32>`, but swapping saves nothing material. Low priority; no change recommended.

### 2.3 Checked and kept: the reason still holds

- **Rust fetch worker and its requests-style facade** (`ca/transport/rust_fetch.py:68-131` feeding `source_capture.fetch_source`): one redirect and scope loop owns policy for both transports; the worker spools, decodes and rate-limits. Keep. The inventory path's separate retry policy (`ca/transport/http.py:137-192`) becomes redundant once the meeting inventories fetch through the fetcher. Delete it for target fetches; its status list is already seeded into the host-pacing registry.
- **Archive member preflight** (`archive_members.py`: central-directory limits before `zipfile` opens a file): `zipfile` has no pre-read limits, and bodies are untrusted. Keep, and pass the spooled file instead of bytes.
- **Custom sniffing** rather than libmagic: libmagic adds a C dependency whose output varies by version, which breaks the digest versioning in D §7.1; the irregular cases (binary-preamble PDFs, `rtfd`, HTML in XML) are local knowledge. Keep, consolidated as the Note says.
- **PDF copier:** after its adapter list, what remains is about 25 lines of streamed decompress-and-verify plus a create-only PUT. Adapt is honest.

## 3. Lens on the Note itself

**Over-built?** Mostly not. It is 200 lines, and each row owns one component. Three costs:

1. **Adapter cells restate spec rules.** Examples:
   - the Receipt writer cell lists D §5.2's field names;
   - the Body store cell restates A §7.1 (bare key, `Content-Encoding`, the older-copy check, a 412 meaning `unchanged`);
   - the C3 cell restates A §10.2 and D §8.1.

   A new receipt field or writer setting then needs the same edit in two documents. Write each item as the code fact that breaks a cited clause, for example "records every header (A §7.2)" or "names `original_path` (D §5.2)". Many cells already do this with "(today …)".
2. **§8 repeats §3.** The 64 MiB cap, the headers, the physical key, the PDF copier and the engine pin each appear in both. Keep §8 for true defects that fail today (the `TypeError`, the `HMKP` strip) and let gaps live in §3.
3. **The shared version-digest helper has no row.** D §7.1 makes every parser, catalog and ingest-mapping version a digest. K34 seeds it, but no row binds one helper, so each new parser would write its own. Add a "Version digest" row (Build, seeded from `parser_fingerprint` and `evidence_fingerprint`).

**Next-change test** (the three changes the coordinator named):

| Next change | Where it is recorded today | Edits needed | Better |
|---|---|---|---|
| A new fetcher transport (a second provider) | The Fetcher row's "Existing implementation" cell, where transports sit inline with five files and the capture command | Rewrite one overloaded cell; no place for the adapter's contract cases | One row per injected adapter, matching A §6 ("direct transport, fetching provider"): source-fetch with the `rust_fetch` facade, and Zyte. Each row names its adapter cases (spooling, decoded-entity hash, 206 means incomplete, provider status kept apart). Do the same for the body store's R2 and local-disk adapters. A new adapter is then one new row |
| A new parser | §3.2, one row per parser | One row, plus a version digest the Note does not say how to compute | Add the version-digest row (above) |
| A new registry | D §7.1's table and one §4 row ("Lands in / Seeded from") | Two, both natural | Fine as is |

**Restating the plan?** No. §6 duplicates the inventory's measured counts, which is the Note's job.

## 4. Verdict

- **Drive the work now**: the engine rows C0, C1, C2, C4 and C5; the reader, site, canary and workflow rows; the sniff, JSON, fingerprint, filename-reader and captures-ingest rows (after §1 item 6); the PDF copier; the receipt rewriter.
- **Before B2 starts** (first in the plan's order of work), settle R1 (receipt writer as Build, seeded, without `bundles.separate`) and R4 (recovery importer as a thin client, deleting RecoveryGuard and the custody machinery). Both change what B2 builds.
- **Before Tracks C and D reach them:** R5 (HTML/XML as Build, seeded) and R6 (C3 on the parquet writer). R3, R7, R8, R9 and R10 are small reshapes that can land with their rows.
- Fix §1 items 1–4 (the dangling reference and three dormant uses) in the next edit; items 5–9 need a spec or owner decision.

**Score: 82 / 100.**
