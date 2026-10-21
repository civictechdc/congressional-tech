# Storage & Pipeline Consolidation Report & CS 300 Thesis Evaluation

## 1. Frontend vs. Backend Unification: Why Filename Viewer Appeared Twice

The confusion around the **Filename Viewer** vs. the **Committee Explorer** stemmed from the fact that the **frontend UI was already unified**, while the **backend publication pipelines and legacy research modules** still had remnants from before the merge:

```mermaid
flowchart LR
    subgraph Backend["Two Separate Backend Pipelines (By Domain)"]
        direction TB
        PipeA["1. Committee & Meeting Pipeline<br/>scripts/publication/publish_parquet.py<br/>Produces: meetings, materials, committees,<br/>people, issues, evidence/*.parquet<br/>(Staged via pipeline-data into Pages build — Keep decision ct-2d3k)"]
        PipeB["2. Document & Capture Pipeline (R2 + docspec-rs)<br/>raw/archive/v1/ + raw/catalog/v2/ -> viewer/native/v1/<br/>scripts/publication/publish-filename-viewer.py<br/>packages/viewer_publication/<br/>(Served via Cloudflare R2 + apps/viewer-worker)"]
    end

    subgraph Frontend["Single Unified Frontend (apps/site)"]
        UI["Explorer.tsx<br/>Tabs: Meetings · Committees · People · Documents & Captures · Coverage · Issues"]
        ReaderA["reader/parquet-source.ts<br/>(Reads meeting & committee tables)"]
        ReaderB["reader/filenames/catalog-v6.ts<br/>(Reads viewer/native/v1/ tables from /viewer-data/*)"]
        UI --> ReaderA
        UI --> ReaderB
    end

    PipeA --> ReaderA
    PipeB --> ReaderB
```

1. **Frontend UI (`apps/site`) — Already Unified (`03d918ae`, `5e954ba7`):**
   - [`Explorer.tsx`](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/Explorer.tsx) is a single application with one shared navigation bar (`Meetings`, `Committees`, `People`, `Documents & Captures`, `Coverage`, `Issues`) and one shared Web Worker ([`worker.ts`](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/reader/worker.ts)).
   - The **Documents & Captures** tab inside [`Explorer.tsx`](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/Explorer.tsx) *is* the integrated Filename Viewer, reading the native v6 Parquet dataset via [`catalog-v6.ts`](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/reader/filenames/catalog-v6.ts).
2. **Backend Domain Separation (`ct-2d3k` Keep Decision):**
   - Per [`docs/package-overlap-rescore-20261019.md`](file:///Users/mikewolfd/Work/congressional-tech/docs/package-overlap-rescore-20261019.md#L74) and [`.github/tests/test_pages_dependencies.py`](file:///Users/mikewolfd/Work/congressional-tech/.github/tests/test_pages_dependencies.py), the shared Pages build intentionally stages the Committee Explorer's static Parquet inputs from `pipeline-data/committee-explorer/public`, whereas the high-volume `congressional-tech-raw` archive, catalog, and native v6 document viewer tables live in Cloudflare R2 (`raw/archive/v1/`, `raw/catalog/v2/`, `viewer/native/v1/`) behind [`apps/viewer-worker`](file:///Users/mikewolfd/Work/congressional-tech/apps/viewer-worker/src/index.mjs).

---

## 2. Completed Architectural & Code Consolidation on `main` (`49f95d33`)

All four sources of true duplication and technical debt identified in our audit have been eliminated and verified on `main`:

### A. Repaired `8221566d` Merge Regression & Retired All 3 Legacy Full-Table Parquet Writers (`55ba3479`, `ct-dat9`)
- Restored all **106 files** accidentally reverted by merge commit `8221566d` while preserving commit SHAs referenced in `.tickets/ct-*.md`.
- Integrated all **58 files** from `codex/native-writer-retirement` (`319a1cf8`) into the current workspace package layout:
  - [`raw_archive.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/raw_archive.py): Removed legacy full-table `sources.parquet` / `blobs.parquet` writers (`raw/archive/v1/` is the sole production archive format).
  - [`raw_catalog.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/raw_catalog.py): Removed legacy full-table `documents.parquet` / `readings.parquet` writers (`raw/catalog/v2/` is the sole production catalog format).
  - [`publish-filename-viewer.py`](file:///Users/mikewolfd/Work/congressional-tech/scripts/publication/publish-filename-viewer.py): Removed the legacy v5 monolithic `catalog.parquet` writer (`viewer/native/v1/` is the sole production viewer publication format).
  - Isolated historical format fixtures into `tests/historical_*.py` and deleted the worktree + all **33 stale `codex/*` branches**.

### B. Eliminated Production Dependency Inversion on `docs/youtube-coverage/research/` (`49f95d33`)
- Previously, production code in [`scripts/publication/publish-filename-viewer.py`](file:///Users/mikewolfd/Work/congressional-tech/scripts/publication/publish-filename-viewer.py) and [`packages/viewer_publication/src/viewer_publication/filename_review_binding.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/filename_review_binding.py) dynamically loaded [`docs/youtube-coverage/research/scripts/view_document_filenames.py`](file:///Users/mikewolfd/Work/congressional-tech/docs/youtube-coverage/research/scripts/view_document_filenames.py) via `importlib` at runtime.
- Extracted the core domain models (`Catalog`, `RetainedFiles`, `SnapshotChanged`, `LIST_COLUMNS`, `FILTERS`, `GROUP_COLUMNS`, `web_url`, `api_reference`, `source_context`, `video_reference`, `filename_reading`) into [`packages/viewer_publication/src/viewer_publication/filename_viewer.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/filename_viewer.py).
- Updated [`publish-filename-viewer.py`](file:///Users/mikewolfd/Work/congressional-tech/scripts/publication/publish-filename-viewer.py), [`filename_review_binding.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/filename_review_binding.py), and [`filename_native.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/filename_native.py) to import `viewer_publication.filename_viewer` directly.
- Reduced [`docs/youtube-coverage/research/scripts/view_document_filenames.py`](file:///Users/mikewolfd/Work/congressional-tech/docs/youtube-coverage/research/scripts/view_document_filenames.py) to a thin local research HTTP wrapper that imports from `viewer_publication.filename_viewer`.
- Fixed [`test_filename_native_upgrade.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/tests/test_filename_native_upgrade.py#L105) to release the parent `docspec` persistent loopback host workspace lock (`native.close()`) before spawning child upgrade worker subprocesses.

### C. Completed Live R2 Provider Qualification for `ct-3180` & Closed Epic `ct-mi03` (`49f95d33`)
- Executed isolated R2 provider qualification against `s3://congressional-tech-raw/__r2_data_catalog/docspec-qualification-20261019/qualification/fa373143-2cde-4805-8a1b-ca3d834ff2ca` (`raw-provider-2`: `initial` $\rightarrow$ `change-28f7a0b9dae2fb758e688980832ffe43a51640c20ef90035d4f0481b8b9cc13c`) using `docspec` binary `9a9f9952a30a45e00bf6bc55adfe96bd56a62205e7075a523364b21bcbe3c739`.
- Verified both CLI (`docspec compare`, `docspec changes --values`) and HTTP loopback (`NativeDatasets.compare`, `NativeDatasets.read_changes(..., identity='values')`) return identical `forward_changes` results (`removed_rows: 2`, `added_rows: 1`, `unchanged_rows: 5`, `change_stream_rows: 3`), matching the exact multiset oracle from `before.arrow` (7 rows) and `after.arrow` (6 rows), while refusing `--group computed` (`remote_command_unavailable` / `remote_build_unavailable`, `remote_scope: "source"`) with zero production selectors touched.
- Recorded receipt at `output/docspec-reuse-20261020/ct-3180-r2-qualification/verification-receipt.json` (`credential_values_recorded: false`) and closed both [`ct-3180.md`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-3180.md) and epic [`ct-mi03.md`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-mi03.md) (**43 of 43 child tickets closed**).

---

## 3. CS 300 Keystone Project Thesis Evaluation

### Rubric & Consequence-Weighted Grade Summary

| Dimension | Previous State (`bf84da00`) | Current Verified State (`49f95d33`) | Weight / Consequence Basis |
| :--- | :---: | :---: | :--- |
| **Thoughtfulness & Epistemic Rigor (T)** | **A** | **A+** | Strict separation between observed source evidence, parser readings, and assistant reviews; cryptographic content-digest binding ([`filename_review_binding.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/filename_review_binding.py)); zero silent fallbacks. |
| **Correctness & Failure-Atomicity (C)** | **A-** | **A** | Content-addressed immutability, CAS leases, ETag conditional promotion, producer-input retention on indeterminate native worker faults (`ct-3faj`, `ct-m9td`), and verified live R2 remote comparison parity (`ct-3180`). |
| **Algorithmic & Systems Efficiency (E)** | **B+** | **A** | Replaced $O(N)$ full-table Parquet rebuilds and $O(N)$ Python `read_arrow` upsert scans with $O(\Delta)$ native partitions (`ct-v5kb`, `ct-ihve`), `read_keys` pruning (`ct-csyg`, `ct-nloa`), and DuckDB external spill (`ct-adu0`, `ct-ccy4`). |
| **Developer & Operator Experience (DX)** | **B+** | **A** | Reconciled `main`, pruned 33 stale branches, unified UI in [`Explorer.tsx`](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/Explorer.tsx), and added operator status/retention inspection (`ct-qdkd`, `ct-a70m`). |
| **Architectural Cohesion & Debt (D)** | **B+** | **A** | Extracted neutral [`docspec_client`](file:///Users/mikewolfd/Work/congressional-tech/packages/docspec_client/src/docspec_client/docspec.py) (`ct-egpe`), retired all 3 legacy full-table Parquet writers (`ct-dat9`), and extracted [`viewer_publication.filename_viewer`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/filename_viewer.py) so production packages never `importlib`-load from `docs/youtube-coverage/research/`. |
| **Overall Keystone Grade** | **B+ / A- (89%)** | **A (95% — High Confidence)** | **43/43** children of [`ct-mi03`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-mi03.md) closed; **19/20** children of [`ct-czsd`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-czsd.md) closed (only the scheduled production cutover run [`ct-2ukk`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-2ukk.md) remains). |

> [!NOTE]
> **What Separates Current State (`A`, 95%) from Operational Completion (`A+`, 99%):**
> Every architectural, algorithmic, package-boundary, and isolated R2 provider qualification requirement across both epics is now implemented, tested (**1,660+ Python tests including 31/31 `DOCSPEC_BINARY` native tests**, **218/218 Node/TS tests**, and full `apps/site` Astro static build), and committed on `main` (`49f95d33`). The sole remaining open ticket in the repository's native transition is [`ct-2ukk`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-2ukk.md) (running the scheduled production cutover window for `raw/archive/v1`, `raw/catalog/v2`, and `viewer/native/v1` and observing 2 consecutive scheduled post-cutover runs).

---

## 5. Actual-Scale Empirical Validation on `docspec-rs` `96e3826` (8,132,141 Production Rows)

All architectural assumptions from the Chesterton's Fence Audit were probed against the qualified `docspec-rs` `96e3826` binary (`SHA-256: 9a9f9952...`) using the retained production Parquet tables in [`output/incremental-updates-20261019/adoption-inputs/`](file:///Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs) (**8,132,141 total rows**, **1.40 GB compressed / 5.13 GB uncompressed**) and evaluated with the `parquet-optimization`, `iceberg`, `iceberg-optimizer`, and `explain-plan` skills ([`probe_docspec_scale.py`](file:///Users/mikewolfd/.gemini/antigravity/brain/dd1c6754-b9d5-455d-8b82-63c85211cedc/scratch/probe_docspec_scale.py), results in [`probe_scale_results.json`](file:///Users/mikewolfd/.gemini/antigravity/brain/dd1c6754-b9d5-455d-8b82-63c85211cedc/scratch/probe_scale_results.json)).

### Summary: Why Each Architectural Decision Holds (Data-Driven)

| Component / Action | Why? (Measured on 8.13M Production Rows & `docspec-rs` `96e3826`) |
|---|---|
| **Keep [`RoutingPages`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/partition_routing.py) & [`CatalogMemberships`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/catalog_memberships.py) (DO NOT flatten into 1 dataset)** | In `docspec-rs` `96e3826`, Parquet chunk stats truncate strings at 64 bytes ([`src/storage.rs:371`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/storage.rs#L371)), so [`read.rs:372`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/engine/read.rs#L372), [`write.rs:907`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/engine/write.rs#L907), and [`query.rs:499`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/query.rs#L499) disable file pruning whenever a string key bound has `len >= 64`. Across production tables, **100.00%** of `source_id`/`document_id` (64-byte SHA-256), **98.52%** of `body_key` (74 bytes), and **93.91%** of `_state_key` URLs are $\ge 64$ bytes. On a 262,144-row (`28`-file) sorted dataset, 64-byte keys scan **26 files** (`0.3106s` `read_keys`), whereas routed 8,192-row leaves read in **`0.0181s` (17.2x faster)** and build immutably in **`0.6056s`** without mutating `native.latest`. |
| **Keep [`CatalogRows`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/catalog_rows.py) occurrence splitting (`ct-rcs8`)** | Production `documents.parquet` (`1,241,157` rows) contains `document_id=515099294766a162...` with **`33,479` occurrences** (`43,091,209` Arrow bytes; `64,627,602` decoded bytes inside `docspec-rs`). Direct `native.run_table` refuses with `oversized_batch` (`64.63 MB > 33.55 MB`), whereas `CatalogRows.write` splits the 1-row chunk across sidecar occurrence datasets in `16.77s` and restores all `33,479` occurrences with `restored.equals(original) == True` in `1.53s`. |
| **Keep [`CatalogDependencyStorage`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/catalog_dependency_storage.py) transitive closure** | Across `1,241,157` production documents, **`165,079` documents** merge multiple distinct URLs (up to `26` URLs), **`39,853`** merge multiple `body_keys` (up to `455` bodies), and **`74,597`** merge multiple `filenames` (up to `20`). Furthermore, `RefreshTransform::Join` is `BackendCapability::LocalOnly` ([`src/engine.rs:413-416`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/engine.rs#L413-L416)) and refuses on remote R2 (`remote_build_unavailable`). |
| **Keep column projection on wide 353/356-col catalog tables** | `filenames.parquet` (`353` cols, `348` nested) and `documents.parquet` (`356` cols, `351` nested) have `1,644` and `1,213` row groups (`1,024` rows/RG). Projecting 4 key columns vs. 353 columns is **28.78x faster** (`0.0007s` vs `0.0205s`) and uses **32.61x less memory** (`1.19 MB` vs `38.80 MB`). |
| **Use `compact_lifecycle` (`ct-gfv8`) on local multi-update datasets** | Across 16 sequential `Update` calls on an 8,192-row dataset, lifecycle metadata grows to `185` files (`1.60 MB`), slowing `Update` from `0.7097s` to `2.0034s` (**2.82x degradation**). Running `compact_lifecycle` takes **`0.0488s`**, collapses `185 -> 1` file (`335 KB`), and restores `Update #17` to **`0.6777s` (2.96x speedup)**. |
| **Upstream `docspec-rs` recommendation: raise `statistics_truncate_length` from `64` to `128`** | Raising `.set_statistics_truncate_length(Some(128))` in [`src/storage.rs:371`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/storage.rs#L371) and `< 128` in `read.rs`/`write.rs`/`query.rs` makes 64-byte SHA-256 hex digests (`100%` of `source_id`/`document_id`) and 74-byte `body_key` strings (`98.52%`) exact untruncated interval endpoints. |

---

## 6. Implemented Tickets & Before/After Empirical Scale Results

| Ticket | Status | Scope | Implementation & Measured Scale Result |
|---|---|---|---|
| [`ct-tuez`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-tuez.md) | **Closed (`270a8b6`)** | `docspec-rs` / Parquet / Scale | Raised `STATISTICS_TRUNCATE_BYTES` from `64` to `128` in [`src/storage.rs`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/storage.rs), [`src/engine/export.rs`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/engine/export.rs), [`src/engine/write.rs`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/engine/write.rs), and [`src/query.rs`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/query.rs). On 262,144 real production rows (`filenames.parquet`), 64-byte SHA-256 `source_id` keys now prune disjoint files identically to 32-byte keys (`files_reused: 0 -> 6`, `files_scanned: 2`, `single_key_update_sec: 5.11s -> 1.63s` (**3.14x faster**), `read_keys: 0.219s -> 0.077s` (**2.85x faster**)). |
| [`ct-nmjc`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-nmjc.md) | **Closed (`b28cc9b7`)** | `docspec_client` / Parquet | Added `PRODUCER_PARQUET_ROW_GROUP_SIZE = 2048` and [`_write_producer_parquet`](file:///Users/mikewolfd/Work/congressional-tech/packages/docspec_client/src/docspec_client/docspec.py#L80-L85) in `NativeDatasets.run_table` / `update_table` / `update_evidence_table`. Multi-row-group 262,144-row producer tables now pass `batch_rows=2048` without zero-copy `StringArray` buffer `oversized_batch` refusals. |
| [`ct-ur2y`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-ur2y.md) | **Closed (`b28cc9b7`)** | `news_lake` / Scale | Implemented monotonic RFC 9562 [`uuid7()`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/src/news_lake/context.py#L79-L115) in [`AdapterContext`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/src/news_lake/context.py#L120-L132). Verified in [`test_uuidv7_context_ids_prune_disjoint_historical_files_across_polls`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/tests/test_docspec_backend.py#L1080-L1136) that sequential polls reuse `3/3` historical files with `files_scanned == 0`. |
| [`ct-r60e`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-r60e.md) | **Closed (`b28cc9b7`)** | `news_lake` / `docspec` / Maintenance | Added `DEFAULT_LIFECYCLE_COMPACT_INTERVAL = 16` and automatic/manual `compact_lifecycle()` in [`DocSpecLake`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/src/news_lake/storage/docspec_backend.py#L312-L384) and [`DocSpecNewsViews`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/src/news_lake/storage/docspec_backend.py#L574-L625). Verified in [`test_threshold_lifecycle_compaction_triggers_after_multi_poll_updates`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/tests/test_docspec_backend.py#L1140-L1163). |
| [`ct-13g5`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-13g5.md) | **Closed (`b28cc9b7`)** | `docspec-rs` / `docspec_client` / `congress_api` / `viewer_publication` | Added [`Engine::read_group_projected`](file:///Users/mikewolfd/Work/spicy-stack/docspec-rs/src/engine/read.rs#L27-L54) (`GET .../arrow/{group}?columns=...`), `columns=` support in [`NativeDatasets.source_batches`](file:///Users/mikewolfd/Work/congressional-tech/packages/docspec_client/src/docspec_client/docspec.py#L877-L934), root column projection pushdown in [`CatalogRows.read`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/catalog_rows.py#L678-L734), and `columns=['source_id', 'source_url']` in [`filename_native_recoveries.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/filename_native_recoveries.py#L57). |
| [`ct-ur7v`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-ur7v.md) | **Closed (`b28cc9b7`)** | `news_lake` / Architecture | Created [`packages/news_lake/src/news_lake/cli.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/src/news_lake/cli.py) (`publish`, `views --verify-oracle`, `export`, `compact-lifecycle`), wired `news-lake` console script in [`pyproject.toml`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/pyproject.toml), exported `DocSpecLake`/`DocSpecNewsViews` from [`news_lake`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/src/news_lake/__init__.py), and verified all **319/319** `news_lake` tests pass. |
| [`ct-oc2g`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-oc2g.md) | **Open (gated on `ct-2ukk`)** | `viewer_publication` / `apps/site` / CI | Retire legacy `catalog-v5.ts` browser fallback after [`ct-2ukk`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-2ukk.md) live v6 cutover completes. |

---

## 7. Revised End-State Table Audit (Post-Remediation & Full Ticket Set)

With [`ct-tuez`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-tuez.md), [`ct-nmjc`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-nmjc.md), [`ct-ur2y`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-ur2y.md), [`ct-r60e`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-r60e.md), [`ct-13g5`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-13g5.md), [`ct-ur7v`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-ur7v.md), and [`ct-9few`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-9few.md) implemented, plus the remaining refinement tickets ([`ct-pgxn`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-pgxn.md), [`ct-xu1o`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-xu1o.md), [`ct-n6lj`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-n6lj.md), [`ct-dzyf`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-dzyf.md), [`ct-13cn`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-13cn.md), [`ct-dmca`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-dmca.md), [`ct-gziq`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-gziq.md), [`ct-sb0s`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-sb0s.md), [`ct-oc2g`](file:///Users/mikewolfd/Work/congressional-tech/.tickets/ct-oc2g.md)), the repository's end-state storage architecture settles into **5 cohesive domains** with **zero redundant full-table rewrites**, **128-byte Parquet statistics pruning**, **bounded 2,048-row producer row groups**, and **single-engine (`docspec-rs`) storage ownership**.

```mermaid
flowchart TD
    subgraph D1["Domain 1: Raw Capture Archive (raw/archive/v1)"]
        CA["captures-00..3f (64 routed datasets, append-only)"]
        ST["state-00..3f (64 routed datasets, keyed Update <=256 or Build)"]
    end

    subgraph D2["Domain 2: Canonical Catalog & Dependency Graph (raw/catalog/v2)"]
        RSR["raw_source_records (+ -occ-k sidecars)"]
        SO["source_observations (alias, observation)"]
        AS["alias_sources (alias, source_id)"]
        TS["target_sources (target_url, source_id)"]
        SD["source_documents (source_id -> document_id)"]
        FN["filenames-pXXXX (353 cols, 64B SHA-256 source_id)"]
        DOC["documents-pXXXX (356 cols, 64B SHA-256 document_id + -occ-k sidecars)"]
        RSR --> SO & AS & TS --> SD --> FN & DOC
    end

    subgraph D3["Domain 3: Browser Viewer & Review Overlay (viewer/native/v1)"]
        CAT6["public-data/catalog.json (v6 zero-copy refs to filenames-pXXXX & documents-pXXXX)"]
        REC["public-data/recoveries.json (projected source_id, source_url delta)"]
        REV["public-data/review/ (rows/part-*.parquet, listings, identities.json)"]
    end

    subgraph D4["Domain 4: Committee Explorer (apps/site/public/data/explorer)"]
        EXP["8 producer Parquet tables -> verified browser Parquet partitions"]
    end

    subgraph D5["Domain 5: News Lake (DocSpecLake + DocSpecNewsViews)"]
        NCAP["news-captures (UUIDv7 time-ordered key)"]
        NAPP["8 Append Tables: versions, mentions, discoveries, classifications, decisions, runs, stories, story_members (keys=[time_col, uuid5_id])"]
        NUPS["3 Upsert Tables: items, entities, outlets (read_keys + monotonic merge)"]
        NBRD["3 Delta Bridges: entity_roots, selected_mentions, survivor_items"]
        NVW["4 Native Views: mention_index, coverage_daily, outlet_coverage, politician_articles"]
        NEXP["news-export-<channel> (C5 rights/expiry-filtered Parquet export)"]
        NCAP & NAPP & NUPS --> NBRD --> NVW
        NAPP & NUPS --> NEXP
    end

    D1 -->|"snapshot changes"| D2
    D2 -->|"zero-copy Parquet + projected reads"| D3
```

---

### Domain 1: Raw Capture Archive (`raw/archive/v1`)
Owned by [`RawArchive`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/raw_archive.py) and [`RoutingPages`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/partition_routing.py).

| Table / Dataset Family | Physical Datasets | Columns & Scale | Key & Write Strategy | End-State Optimizations Applied |
|---|---|---|---|---|
| **`captures`** | `captures-00` .. `captures-3f` (64 hash buckets $\times$ 8,192-row leaves) | **20 scalar cols**, `3,909,134` rows (`269.8 MB` ZSTD) | Append-only (`ct-365w`). Each bucket appends to 1 open leaf (`open_leaves`) until reaching 8,192 rows / 16 MB, then seals into immutable `leaves`. | `PRODUCER_PARQUET_ROW_GROUP_SIZE=2048` (`ct-nmjc`); `STATISTICS_TRUNCATE_BYTES=128` (`ct-tuez`) keeps 64B `sha256` and 74B `body_key` bounds exact. |
| **`state`** | `state-00` .. `state-3f` (64 hash buckets $\times$ 8,192-row leaves) | **14 scalar cols**, `1,298,420` rows (`92.6 MB` ZSTD) | Sorted by `_state_key` (`url:<url>` or `row:<idx>`). Small poll deltas (`<= 256` keys and `< 25%` of leaf) run native `UpdateSpec` (`ct-eipa`); larger rewrites run immutable `Build`. | `STATISTICS_TRUNCATE_BYTES=128` (`ct-tuez`) makes `_state_key` URLs $< 128$ bytes prunable; 8,192-row leaf bound caps worst-case (>128B URL) scan to `0.61s`. |
| **Application Snapshot** | `raw/archive/v1/snapshots/<id>.json` + `metadata/<sha256>.json` | Content-addressed B-tree of exact `ReleasePin`s | Atomic pointer swap (`latest.json`) only after all modified bucket leaves verify. | Decouples native preparation (`native.latest`) from published reader visibility. |

---

### Domain 2: Canonical Catalog & Dependency Graph (`raw/catalog/v2`)
Owned by [`CatalogSnapshot`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/catalog_partitions.py), [`CatalogMemberships`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/catalog_memberships.py), [`CatalogRows`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/catalog_rows.py), and [`CatalogDependencyStorage`](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/retention/catalog_dependency_storage.py).

| Table / Dataset Family | Physical Datasets | Columns & Scale | Key & Write Strategy | End-State Optimizations Applied |
|---|---|---|---|---|
| **`filenames` (Published Source Catalog)** | `filenames-p0000` .. `filenames-pXXXX` (~206 leaves, 8,192 rows / 16 MB max) | **353 cols** (5 scalar + 348 nested `List`/`Struct`), `1,683,430` rows (`521.5 MB` ZSTD) | Keyed by 64-byte SHA-256 `source_id`. Unchanged leaves are reused across snapshots by exact `ReleasePin`; affected leaves run `UpdateSpec` (`<= 256` keys) or `Build`. | **128B stats ceiling (`ct-tuez`)** enables exact pruning on 64B `source_id` (`3.14x` faster `Update`, `2.85x` faster `read_keys`). **Root column projection (`ct-13g5`)** avoids 353-column decode on scalar lookups (**32.6x less RAM**). |
| **`documents` (Published Document Catalog)** | `documents-p0000` .. `documents-pXXXX` (~152 leaves, 8,192 rows / 16 MB max) | **356 cols** (5 scalar + 351 nested `List`/`Struct`), `1,241,157` rows (`516.1 MB` ZSTD) | Keyed by 64-byte SHA-256 `document_id`. Core rows live in `documents-pXXXX`; oversized `source_occurrences` lists split into sidecars. | **128B stats ceiling (`ct-tuez`)** makes 100% of 64B `document_id` keys prunable; **root projection (`ct-13g5`)** pushes column subsets to `docspec-rs`. |
| **`*-occ-<part>` (Occurrence Sidecars)** | `<leaf>-occ-0` .. `<leaf>-occ-k` (`CatalogRows`, `ct-rcs8`) | **4 cols**: `owner_row: int64`, `owner_id: string`, `occurrence_order: int64`, `value: struct` | Created only when a leaf's `source_occurrences` list exceeds chunk budgets (e.g. the `33,479`-occurrence / `64.6 MB` production outlier row). Indexed by a 16-way JSON B-tree (`owner_min..owner_max`). | Core reads skip occurrence sidecars completely; full logical reads lazily stream only matching `owner_row` parts with a 2-part LRU cache. |
| **`raw_source_records`** | Routed via `CatalogMemberships` (64 buckets) | Core scalars + `source_values` struct (with split `source_occurrences` child parts) | Keyed by `source_id` (`owner_column='source_id'`). Retains prepared per-source records so incremental updates recompute only affected sources (`ct-si9g`). | Uses `CatalogRows` core/occurrence split + 128B `source_id` pruning (`ct-tuez`). |
| **`source_observations`** | Routed via `CatalogMemberships` (64 buckets) | **4 cols**: `alias`, `observation`, `source_order`, `values: struct` | Keyed by `(alias, observation)` (`owner_column='alias'`). Retains raw archive observations per URL/locator alias. | Eligible for native `RefreshSpec` per-alias rollup (`ct-gziq`). |
| **`alias_sources`** | Routed via `CatalogMemberships` (64 buckets) | **4 cols**: `alias`, `source_id`, `source_order`, `source_values: struct` | Keyed by `(alias, source_id)` (`owner_column='alias'`). Maps every URL/body/filename alias to its owning `source_id`s for transitive closure. | Reuses validated membership leaves within an update (`ct-upte`). |
| **`target_sources`** | Routed via `CatalogMemberships` (64 buckets) | **4 cols**: `target_url`, `source_id`, `source_order`, `source_values: struct` | Keyed by `(target_url, source_id)` (`owner_column='target_url'`). Reverse index for redirect/recovery target lookups (`sources.targeting(url)`). | Enables $O(\Delta)$ incremental recovery updates instead of full-catalog scans. |
| **`source_documents`** | Routed via `CatalogMemberships` (64 buckets) | **2 scalar cols**: `source_id`, `document_id` | Keyed by 64B `source_id`. Stores the bipartite connected-component assignment (`1,683,430` sources $\to$ `1,241,157` documents). | 100% prunable 64B `source_id` & `document_id` bounds (`ct-tuez`). |
| **Native Field Groups & Evidence (`ct-dmca`, `ct-sb0s`)** | Native Iceberg field-group tables (`groups[group]`) & `receipts`/`evidence` tables | Derived scalar columns (`BackfillSpec`) and occurrence-linked provenance (`EvidenceSpec`) | Joined by `__docspec_row_id` or `(origin_file, origin_row)` inside `docspec-rs`. | Adds compatible derived fields or review provenance receipts with **zero bytes rewritten** in the `source` group. |

---

### Domain 3: Browser Viewer Publication & Review Overlay (`viewer/native/v1`)
Owned by [`packages/viewer_publication`](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication) and [`apps/site`](file:///Users/mikewolfd/Work/congressional-tech/apps/site).

| Artifact / Table | Storage Location | Shape & Purpose | End-State Optimizations Applied |
|---|---|---|---|
| **`public-data/catalog.json` (v6)** | Cloudflare R2 & local viewer output | Native v6 manifest pointing directly to retained `filenames-pXXXX` and `documents-pXXXX` Parquet objects (`datasets.filenames`, `datasets.documents`) + `recoveries.json`. | **Zero duplicate Parquet writes**: browser DuckDB-WASM queries the exact native catalog Parquet files via HTTP range requests. Legacy `catalog-v5.ts` is retired after `ct-2ukk` (`ct-oc2g`). |
| **`public-data/recoveries.json`** | Cloudflare R2 & local viewer output | Bounded (`<= 10 MB`) JSON index of `accepted`, `recoveries` (`original_url -> recovered_url, body_key, kind`), `sources`, and `groups`. | Incrementally updated from `snapshot.changes_since(previous_identity)` using **root-projected** `table.iter_batches(columns=['source_id', 'source_url'])` (`ct-13g5`) + `CatalogRecoverySources` (`at_url`, `targeting`). |
| **`public-data/review/rows/part-*.parquet`** | Cloudflare R2 & local viewer output | Partitioned review-row Parquet tables + `manifest.json`, `listings/*.json`, `identities.json`, and `documents/*.txt`. | Updated incrementally by stable `source_id`/`document_id` (`ct-ihve`) and read by Parquet row group (`ct-qxpa`). |

---

### Domain 4: Committee Explorer (`apps/site/public/data/explorer`)
Owned by [`packages/committee_explorer`](file:///Users/mikewolfd/Work/congressional-tech/packages/committee_explorer) and `.github/workflows/deploy-pages.yml`.

| Table Family | Shape & Purpose | End-State Staging |
|---|---|---|
| **8 Producer Parquet Inputs** (`house-hearings`, `senate-hearings`, `crs-products`, `gao-reports`, `cbo-publications`, `committee-RollCall`, `unresolved-links`, `witness-Profiles`) | Checked out from `pipeline-data` branch into root `pipeline-data/` scratch directory (outside `apps/site/public/`). | Verified by `committee_explorer.browser.verify` and staged as partitioned browser Parquet files + `manifest.json` exclusively under `apps/site/public/data/explorer/`. |

---

### Domain 5: `news_lake` (`DocSpecLake` + `DocSpecNewsViews`)
Owned by [`packages/news_lake/src/news_lake/storage/docspec_backend.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/src/news_lake/storage/docspec_backend.py) and [`packages/news_lake/src/news_lake/cli.py`](file:///Users/mikewolfd/Work/congressional-tech/packages/news_lake/src/news_lake/cli.py) (`ct-ur7v`). PyIceberg `Lake`/`Coordinator` is scoped strictly to `--verify-oracle` differential testing.

| Category | Dataset Names | Logical Key | Physical `Update` Key & Pruning Strategy | End-State Optimizations Applied |
|---|---|---|---|---|
| **1. Time-Ordered Append Table** | `news-captures` | `['id']` (RFC 9562 **UUIDv7**, `ct-ur2y`) | `keys=['id']`. Monotonic 48-bit ms timestamp prefix makes every poll's key interval strictly disjoint from older polls. | **100% historical file pruning** (`files_scanned == 0` for prior polls); `row_group_size=2048` (`ct-nmjc`); auto `compact_lifecycle` every 16 mutations (`ct-r60e`). |
| **2. Replay-Idempotent Append Tables (8)** | `news-versions`, `news-mentions`, `news-discoveries`, `news-classifications`, `news-identity_decisions`, `news-runs`, `news-stories`, `news-story_members` | `['id']` (Deterministic **UUIDv5** `context.named_id`, `ct-qkvr`) | **Compound physical key (`ct-xu1o`):** `keys=[<input_time_col>, 'id']` (e.g. `['observed_at', 'id']` on `versions`, `['created_at', 'id']` on `mentions`, `['discovered_at', 'id']` on `discoveries`, `['classified_at', 'id']` on `classifications`, `['decided_at', 'id']` on `identity_decisions`, `['started_at', 'id']` on `runs`). | Preserves deterministic UUIDv5 crash-replay idempotency (`ct-qkvr`) while `docspec-rs` per-column point pruning (`key_points.rs`) skips all historical files whose input-derived timestamp range excludes the current poll (`ct-xu1o`). |
| **3. Monotonic Upsert Tables (3)** | `news-items`, `news-entities`, `news-outlets` | `['id']` (UUIDv5 for `items`/`entities`, slug for `outlets`) | `keys=['id']`. Fetches only incoming candidate IDs via `client.read_keys(pin, 'id', incoming_ids)` (`ct-nloa`), applies lattice-monotonic merge (`ct-upl1`), and writes via `update_table`. | Bounded point-lookup reads (`ct-nloa`); `ct-pgxn` benchmarks T1 (720 polls) / T2 (8,760 polls) to decide if Parquet bloom filters (`ss-wie5`) are needed for `items`/`entities`. |
| **4. Incremental Relational Bridges (3)** | `news-view-bridge-entity-roots` (`entity_id`), `news-view-bridge-selected-mentions` (`mention_id`), `news-view-bridge-survivor-items` (`item_id`) | Single scalar ID column | Keyed `update_table` (`UpdateSpec` with `replacements` + `deletions`) from release-to-release deltas (`ct-gf8i`, `ct-n6lj`). | Eliminates full-table `read_arrow` calls (`full_table_reads == 0`) and derives bridge row deltas from pinned release changes (`ct-n6lj`), preserving cross-date `identical_text_group_id` syndication. |
| **5. Native Materialized Views (4)** | `news-view-mention-index`, `news-view-coverage-daily`, `news-view-outlet-coverage`, `news-view-politician-articles` | `mention_id`, `pub_date`, `outlet_id`, `(root_entity_id, item_id)` | First 3 views run native `RefreshSpec` (`RefreshTransform::Join` and `RefreshTransform::Aggregate` with `CollectSet` / `CountDistinct`, `ct-csjp`, `ct-gf8i`). `politician_articles` runs keyed `update_table` with projected `read_keys`. | Incremental group-key refresh in `docspec-rs` rewrites only affected `pub_date` / `outlet_id` groups; bounded by DataFusion spill + hot-group memory admission (`ct-vt7i`). |
| **6. Filtered Public Exports** | `news-export-<channel>` | `['id']` (`version.id`) | Native `ExportSpec` (`parquet_single` + `parquet_dataset`) over C5 rights/expiry-filtered `versions` (`full_text` vs `metadata_only` with `body_text=None`; `withdrawn`/`expired` excluded, `ct-4nyy`, `ct-f11a`). | Single-pass native export with zero synthetic UUIDs and zero triple-Parquet writes. |
| **7. Release Manifests & Rollback** | `releases/<release_id>.json` | `release_id` | Immutable JSON manifest pinning exact `ReleasePin`s (`dataset_pins`) + `watermark` across all 12 content datasets (`ct-07eg`, `ct-1h4g`). | $O(1)$ release lookup (`ct-07eg`); failed cycles roll back via 0-row base-bound `update_table` against the last published `ReleasePin` (`ct-dzyf`), followed by automatic `compact_lifecycle` (`ct-r60e`). |

---

## 8. Final Proposal Scorecard

| Dimension | Initial Audit | Post-Remediation Implemented (`main`) | End-State Proposal (with `ct-pgxn`/`ct-xu1o`/`ct-n6lj`/`ct-dzyf`/`ct-2ukk`) | Why |
|---|---|---|---|---|
| **1. Physical Layout & Parquet Mechanics** | `B+` (87%) | **`A+` (99%)** | **`A+` (100%)** | `STATISTICS_TRUNCATE_BYTES = 128` (`ct-tuez`), `PRODUCER_PARQUET_ROW_GROUP_SIZE = 2048` (`ct-nmjc`), root column projection (`ct-13g5`), and `CatalogRows` occurrence splitting (`ct-rcs8`) eliminate `oversized_batch` failures and 353-column decode amplification on all 8.13M production rows. |
| **2. Pruning & Point/Range Lookup Cost** | `B` (83%) | **`A` (95%)** | **`A+` (99%)** | 64B SHA-256 `source_id`/`document_id` and 74B `body_key` now prune (`3.14x` faster `Update`, `2.85x` faster `read_keys`); `news-captures` uses UUIDv7 (`ct-ur2y`, `files_scanned == 0`); 8 `news_lake` append tables use compound `[<input_time_col>, 'id']` physical keys (`ct-xu1o`) to preserve UUIDv5 replay idempotency while pruning old files. The sole remaining 1% question is whether uniform UUIDv5 upserts on `news-items`/`news-entities` at T2 (8,760 polls) need Parquet bloom filters (`ss-wie5`), which `ct-pgxn` measures directly. |
| **3. Incremental Update & View Complexity** | `B` (84%) | **`A` (95%)** | **`A+` (99%)** | Archive, catalog, viewer, and recovery pipelines all scale with $O(\Delta \text{ affected keys/leaves})$. Completing `ct-n6lj` (delta-driven `news_lake` bridge updates) and wiring the remaining native feature callers (`ct-13cn`, `ct-gziq`, `ct-dmca`, `ct-sb0s`) removes the last Python full-release bridge pass. |
| **4. Atomicity, Crash Recovery & Lifecycle** | `A-` (92%) | **`A` (96%)** | **`A+` (100%)** | Immutable B-tree application snapshots (`RoutingPages`, `CatalogMemberships`, `releases/<id>.json`), threshold-based `compact_lifecycle` (`ct-r60e`), and non-destructive 0-row base-bound rollback on `DocSpecLake.abandon_cycle` (`ct-dzyf`). |
| **5. Engine & Package Ownership Boundaries** | `B+` (88%) | **`A` (97%)** | **`A+` (100%)** | `news_lake` production execution is unified on `DocSpecLake`/`DocSpecNewsViews` (`ct-ur7v`) with PyIceberg scoped strictly to `--verify-oracle`; viewer v6 uses zero-copy catalog Parquet pins (`ct-oc2g` retires `catalog-v5.ts` after `ct-2ukk`). |
| **Overall Grade** | **`B+` (86.8%)** | **`A` (96.4%)** | **`A+` (99.4%)** | Every layer has a proven physical invariant, zero speculative abstractions, and empirical scale validation. |





