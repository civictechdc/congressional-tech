# Batch czsd: greenfield addendum

Lens: nothing and nobody uses this yet. Only the raw/source data in R2 `congressional-tech-raw` must
survive: body bytes, receipts and their provenance. Everything derived can be rebuilt.
This addendum supplements `czsd-verdicts.md` and does not replace it. Read-only; no network.

## New facts gathered for this pass

- **Every legacy capture row points at a receipt.** I read the retained adoption input
  `output/incremental-updates-20261019/adoption-inputs/captures.parquet` with my own script
  `czsd-receipt-coverage.py`. It has 3,909,134 rows. `receipt_key` and `receipt_line` have 0 nulls, and
  there are 2,289 distinct keys, all under `receipts/`. So the legacy capture table is *derivable from
  receipts*, provided those 2,289 receipt objects exist in R2. That last part is CANNOT-VERIFY: there is no
  network access, and the local mirror `.cache/congressional-tech-raw/` has no `receipts/`.
- **The raw-write safeguards predate the czsd epic.** `existing_body_info` dates from 2026-10-01
  (`43f112ef`). Immutable receipt batches date from 10-05 (`931500d9`). Read-back-verified recovery writes
  (`checked_put`) date from 10-15 (`a2e25550`). The czsd epic mostly changed *derived* storage: the
  capture/state tables, the catalog and the viewer.
- **Human review decisions are in git** (`apps/site/document-review-identities.json`), not only in R2.
  They are not raw source data, but they are not rebuildable either. Git keeps them safe whatever
  happens to derived storage.

## 1. Raw-data risks (most severe first)

| # | Risk | Evidence | Reachable from production today? |
|---|---|---|---|
| R1 | **Latent raw-body deletion.** `migrate_pdf_bodies_to_uncompressed(delete_gzip=True)` deletes the canonical `bodies/sha256/...gz` whenever a `.pdf` exists at the derived key. It checks only that the object exists, not its bytes (`_object_exists`, which also swallows errors). | `packages/congress_api/src/congress_api/retention/raw_storage.py:280,296-303,312-316,330-331`. Added by `4ed77e3f` (ct-te1p), inside ct-365w's module. | **No.** No caller in src, scripts or workflows (git grep). `R2Store` has no `delete` method, so `hasattr(store,'delete')` is False. Any future caller or a new `delete` method would arm it. **Delete the `delete_gzip` option.** |
| R2 | **Derived-data engine shares the raw bucket.** The DocSpec warehouse owned prefix is `s3://congressional-tech-raw/__r2_data_catalog/docspec-archive-v1`. The engine has removal and delete code. | `.github/docspec-remote.json:2`; engine deletes are scoped by code only (`spicy-stack/docspec-rs/src/storage/remote/objects.rs:722-725`, `src/engine/retention/removal.rs:1006`) | **Writes: yes. Deletes: no.** The app only *plans* removals: `native_capacity.py:543-560` runs only with a `removal_id`, and `cli/raw_sync.py:437` passes none. The credential scope of `DOCSPEC_S3_*` is CANNOT-VERIFY. If it is bucket-wide, the only fence between an engine bug and raw bodies is application code. Move the warehouse to its own bucket, or use a prefix-scoped token. |
| R3 | **PDF copy collisions are not verified.** `put_pdf_body` treats 412 as success without checking the stored bytes. The `.gz` path does verify (`raw_archive.py:381-383` → `existing_body_info` at `:232-236`; `body_files.py:137-140`). | `retention/r2.py:388-391`; `raw_archive.py:384-388` | Yes, on every PDF capture when `store_uncompressed_pdfs` is set. Low severity: the `.gz` stays canonical and verified. It matters if the public `.pdf` becomes the only copy, which is what R1 would cause. |
| R4 | **Legacy capture/state Parquet may be raw provenance.** Nothing writes or deletes it now: `raw_archive.py:52-53` keys are only read (`raw_adoption_inputs.py:23-29`, `index/*`). But it is rebuildable only if all 2,289 referenced receipts exist. | See the receipt-coverage facts above | No writer or deleter is reachable. Action: list `receipts/` once, confirm all 2,289 keys and their line counts, then treat these tables as derived. Until then keep them immutable and back them up. |
| R5 | **Receipts and bodies are not served publicly.** | `infra/cloudflare/congressional-data-r2-edge.json:35-45`: the custom domain allows only `/viewer-publications/`, `/bodies/sha256/` and `/exports/`, and blocks `/receipts/`, `/indexes/` and `/warehouse/`. `__r2_data_catalog/` is not allowlisted. | Custom domain: protected. Whether the r2.dev public URL is enabled for the bucket is CANNOT-VERIFY. If it is, everything in the bucket is world-readable, including the DocSpec warehouse. |
| R6 | **Orphan receipts are re-applied on every run.** This is a raw-provenance safety net, not a risk. | `raw_archive.py:670-677`. Receipts are written immutably first (`:517-522`, `r2.py:372-376`), then native selection runs (`:773-795`). | Yes, and it should be kept. My earlier "O(history) listing" finding for ct-365w is downgraded: it covers about 2.3k receipt files, about 3 LIST pages. Bound it by date prefix if it ever grows; do not remove it. |

**No raw-data risk in my batch is live today.** The raw writers in this batch (Archive bodies and
receipts, `checked_put` recovery, the `ct-84x7` stream reads) use conditional immutable writes,
MD5-verified uploads, verified collisions and read-back. R1 is the one to remove before anything calls it.

## 2. What drops away

- **ct-ihve v5/live-site breakage.** Irrelevant. Retiring v5 was correct; nobody has saved links.
- **ct-87n4 checker accepting `[2,5,6]`.** Irrelevant.
- **ct-dat9's 4-day hosted outage.** No user impact. Only a process lesson remains: check the pin against the client.
- **ct-jufk empty-module shim.** Code hygiene only.
- **ct-365w receipts listing.** Minor (see R6).
- **ct-l5q1 downstream fixture reuse, and ct-v5kb keeping the v1 writer.** Irrelevant (delete instead).
- **All resume, old-attempt, historical-proof and exact-adoption concerns** (ct-9vtu, ct-y32m, catalog proofs readable across validator upgrades, preserved withdrawals). These become *waste* rather than gaps.

What still matters: R1–R4 above. ct-si9g's quadratic loop matters only if the incremental engine is kept,
and I recommend it is not. The failing `test_workflow_resume.py` case is minor.

## 3. Re-grades (only where my judgment changes)

| ticket | proposal old → new | work old → new | reason |
|---|---|---|---|
| ct-9vtu | A- 90 → C 75 | A- 90 → B 84 | Resuming exact adoption of a rebuildable derived catalog. Good code, near-zero value; a rebuild makes it unnecessary. |
| ct-y32m | A- 90 → C 75 | A- 90 → B 84 | Saves re-downloading derived catalog files for a one-time adoption that need not happen. |
| ct-5kb2 | A 94 → B 85 | A- 91 (unchanged) | Measured and well built, but the target was adoption speed for derived data. The batching may still help a fresh build. |
| ct-gd8v | A- 91 → B 85 | A- 91 (unchanged) | Guards exact adoption of tables that are rebuildable from receipts (if R4 checks out), against legacy writers that are now retired. It protects nothing in R2 from loss. |
| ct-ihve | B+ 88 → C+ 78 | B- 81 → B 84 | The proposal spent effort on v5 links, preserved withdrawals and pinned late-loading generations, which is compatibility nobody needs. The work's main defect (live v5 breakage) no longer matters. |
| ct-87n4 | A- 90 → B- 82 | B+ 88 → A- 90 | Live verification of reviews and recoveries for a site with no users is low value. The drift defect is moot. |
| ct-dat9 | B 85 → B- 80 | C+ 78 → C 72 | It deliberately **forbids full rebuild from raw** (`cli/raw_sync.py:373-374`; `cli/document_index.py:41-42`). In a greenfield project that is the cheapest correctness and recovery tool, so this inverts the right design. Resume and "old generation stays visible" serve readers that don't exist. |
| ct-si9g | B 84 → C+ 78 | C+ 78 (unchanged) | Exact preservation of derived interpretations plus resume inside large components, built before a full rebuild was ever timed. |
| ct-v5kb | B 84 → C+ 78 | B- 80 → C+ 77 | Historical proof readers, stale-proof rejection and preserved old snapshots all protect derived publication history. |
| ct-rcs8 | A- 92 → B+ 88 | B+ 87 (unchanged) | Lossless adoption of one derived row. A rebuild still needs a representation for giant rows, so this keeps partial value. |
| ct-365w | B+ 87 → B+ 89 | B 84 → B 86 | Its "no lost or repeated additions" under lost replies and restarts protects capture provenance. The O(history) concern shrinks to minor. |
| ct-87uq | B+ 88 → B 85 | A- 90 (unchanged) | Froze derived category outputs exactly; behavior-change freedom was cheap here. |
| ct-snh8 | B+ 87 → B 84 | A- 90 (unchanged) | "Without changing published data" protected derived output. |
| epic ct-czsd (not averaged) | B- 81 → C- 70 | C+ 78 → C- 70 | Its central requirement was exact adoption of existing derived snapshots without reclassifying, plus resume. That drove most of the retention package's growth of about 18.8k lines since `585b9ad6`, though not all of that growth comes from czsd tickets. The code carries derived data forward instead of rebuilding it from the raw data. |

New batch averages (29 tickets): **proposal 85.9 (B)**, was 88.9; **work 87.5 (B+)**, was 88.0.
Every other ticket's grade is unchanged.

## 4. Keep / simplify / delete, going forward

- **Raw capture and custody: KEEP.** Archive acquisition, `put_body`/`retain_body_file` collision checks,
  immutable receipt batches, `corpus_recovery` `checked_put` with read-back, and `r2.py` conditional
  writes (`ct-84x7`). Fix three things:
  - Delete `delete_gzip` (R1).
  - Verify `.pdf` collisions (R3).
  - Separate the DocSpec warehouse or scope its token (R2).
  Add one standing raw audit: every receipt referenced exists, and every body key hashes to its name.
- **Raw and catalog adoption: DELETE** once R4 checks out. That covers `raw_adoption.py`,
  `raw_adoption_inputs.py`, `raw_readings_adoption.py`, `catalog_adoption.py`, retained-input
  `read_catalog`, the `--adopt-raw`/`--adopt-catalog` modes, and ct-9vtu/ct-y32m/ct-5kb2's adoption
  paths. Replace them with "derive capture/state from receipts" plus "build the catalog from raw".
- **Incremental catalog engine: RADICALLY SIMPLIFY.** This covers ct-si9g, ct-v5kb, ct-upte, ct-7e7q and
  their dependency routing pages, membership leaf cache, component and scope proofs, `source_update_proof`,
  catalog selection v2 and historical readers. The retention package is 27.8k lines across 98 files.
  - Start with a timed full rebuild from raw (DocSpec native Runs, or plain partitioned Parquet).
  - Add incrementality only where that timing is unacceptable.
  - Put keyed merges in the engine (`UpdateMergeSpec` already exists, `raw_storage.py:378-395`), not in app-side B-trees.
  - Keep the interpretation and grouping policy code and the giant-row lesson from ct-rcs8.
- **Viewer publication: SIMPLIFY.** Keep ct-ihve's stable-ID, content-addressed pages and one checker
  (ct-87n4). Delete continuation/resume descriptors, the release source-fingerprint and AST-hash
  machinery, withdrawal preservation, and the `release_identity.py:12-16` shim. Make publishing "write an
  immutable release, flip a pointer".
- **ct-dat9 routing: REVERSE one decision.** Make explicit full rebuild from raw a supported operation.
  Delete the refusing `--rebuild`/`--repair` stubs and the `raw_catalog.py` facade. Keep one CI check that
  the hosted runtime pin satisfies the client protocol.
- **ct-snh8 and ct-8w0g: KEEP as is.** They are small, proportionate, and ct-8w0g sits on the raw
  acquisition path. Clean the stale `globals.py` references (`capture-raw-sources.yml:34`,
  `docs/congress-api-contracts.md:155`).
