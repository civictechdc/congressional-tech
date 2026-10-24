# mi03b greenfield addendum (epic ct-mi03)

Lens: nothing uses any of this yet. Only the raw/source data has to survive: the R2 `congressional-tech-raw` objects, their receipts and their provenance. Everything derived can be rebuilt. This file adds to `mi03b-verdicts.md` and does not replace it.

Where the raw data lives (checked, not assumed):
- **Raw bodies** are plain R2 objects (`bodies/sha256/..`, `raw_storage.py:231-270`).
- **Capture state/provenance rows** (url → body_key, sha256, status) are DocSpec datasets. They are written by `RawStorage` through `native.run_table` (`raw_storage.py:1066-1075`, one immutable dataset per candidate) and `native.update_table` (`:1217`, only for schema-evolved leaves).
- **Hosted writer:** `capture-raw-sources.yml:441-455` runs `raw-source-sync --bucket congressional-tech-raw --native-config …`.
- **Derived catalog location:** the native catalog lives inside the raw bucket (`s3://congressional-tech-raw/__r2_data_catalog/…`, from the ct-3180 receipt).

## 1. Raw-data risks in or next to this batch

| # | Risk | Evidence | Reachable from a production path today? |
|---|---|---|---|
| R1 | **The engine that writes raw provenance is self-attested.** Setup checks the downloaded artifact only against its own descriptor (`setup-native-runtime.py:126`, `expected_source_revision=artifact['source_revision']`), never against the app pin `QUALIFIED_DOCSPEC_RUNTIME` (`docspec_client/models.py:16-25`). The raw capture workflow then writes state into the raw bucket (`capture-raw-sources.yml:271-278, 441-455`). The digest stops tampering but not staleness or a wrong version. The Oct 20–24 stale pin failed loudly. I cannot see R2, so I can't rule out quiet writes from an older engine. | `setup-native-runtime.py:32-56,99-131`; `client.py:316-320` enforces only the config's own digest | **Yes** (ct-ugqq, ct-oxg6) |
| R2 | **Shared blast radius.** The rebuildable native catalog shares a bucket and engine credentials with raw bodies. The engine has remote removal (`main.rs:205-208`, `RemoveObjects` / `PrepareRemoteRemoval`; `retention/removal.rs:433`). Remote lifecycle compaction drops old version records (`retention/compaction.rs:125-170`; object reclaim is local-only at `:170`). | ct-3180 receipt path; `raw_sync` `--bucket congressional-tech-raw --native-config` | **No app caller.** `grep` finds no removal-execute or `compact_lifecycle` call in `congress_api`/`scripts`/workflows. Reachable only by an operator running the engine CLI or HTTP against R2. |
| R3 | **The retention planner treats anything not explicitly protected as reclaimable.** An object is reclaimable unless a caller-supplied pin, engine status or path match protects it (`native_capacity.py:522-541`). The engine reports unknown objects as "unmatched", so raw bodies or receipts passed as candidates would be marked reclaimable. With `removal_id` set it requests a native removal plan (`:543-557`). | `native_capacity.py:430-575` (ct-qdkd / ct-a70m) | **No, inert.** `raw_sync.py:437` passes no objects and no `removal_id`. Latent. |
| R4 | **Custody protects in-flight raw-state writes (positive).** `request.json` and the producer Parquet are kept on an unknown outcome (`client.py:482-578, 686-797`). Raw paths use the default `stream_ipc=False`. The IPC path (`client.py:465, 668`) has **no custody** and is reachable only from news_lake today. | ct-m9td, ct-q968 | Yes, and it works. Keep raw writers off IPC. |
| R5 | **The raw-state update can silently lose its merge policy.** It retries without `merge` on `TypeError` (`raw_storage.py:1226-1233`), which would turn LATEST_OR_BACKFILL into plain key replacement and could null `body_key`/`sha256` provenance. | Next to ct-m9td / ct-xq1y; out of batch | Not with the current client, which accepts `merge`. Delete the fallback. |
| R6 | **Out of batch, flag to coordinator:** `migrate_pdf_bodies_to_uncompressed(delete_gzip=True)` deletes the raw `.gz` body when a PDF key merely *exists*. There is no digest check of that PDF, and `_object_exists` swallows errors. | `raw_storage.py:296-316` | No caller found. Latent raw deletion. |
| R7 | **news_lake append-ID uniqueness hole** (my probe P2: a duplicate id was stored). | `lake.py:88, 329` | Pilot only, local workspace. Becomes a raw-provenance bug only if news capture goes live. |

Nothing in this batch writes to the public bucket.

## 2. What drops away (now low priority or irrelevant)

- **ct-jo8n P1** (old news releases unreadable after auto-compaction) and the missing stale-seal / lost-publication tests: derived pilot data with no readers. Low.
- **ct-qkvr / ct-nloa** 1/8/32-poll measurements, R2 append qualification, the merge-policy relocation: pilot perf/compat. Irrelevant.
- **ct-n6lj / ct-vt7i** hot-group scale evidence and the static receipt; **ct-mpsp** app round-trip: derived views. Irrelevant.
- **ct-lcbc / ct-wmtx / ct-wjce** skipped measurements: perf of long-lived derived history that doesn't exist yet. Low.
- **ct-nc7l** "preserve every old pin / review decision / mapping" and worktree archiving: compat ceremony. Irrelevant.
- **ct-sb0s** R2 parity and the O(rows×cols) locator map: review provenance is derived. Low.
- **ct-m9td** IPC bypass: affects only news. Low, provided raw writers never opt in.
- **ct-oxg6** mutable `target/debug`/PATH default: raw writers use `from_config`, which requires an explicit binary (`client.py:252-266`), and `verify_runtime` enforces the configured digest. The resolver is reached only by derived `weekly_tables.py:824`. Low. The real gap is R1.
- **Small items:** ct-x0nk self-test, ct-tcfg guard, ct-qdkd "failed" state. Cosmetic.

These **stay or grow**: R1 (ct-ugqq), R2/R3 (bucket co-location and the planner's reclaim-by-default), and keeping raw writes on the custody path (R4).

## 3. Re-grades (only where judgment changed)

| ticket | proposal old → new | work old → new | reason |
|---|---|---|---|
| ct-ugqq | B+ 87 → A- 91 | D+ 67 → D- 62 | Binding the hosted raw writer's engine identity is the batch's most raw-critical aim. The shipped check is self-referential on a reachable raw-writing path. |
| ct-m9td | A- 91 → A 95 | B 86 → B+ 88 | Custody covers raw-state `update_table` (`raw_storage.py:1217`). The IPC bypass touches only the pilot. |
| ct-q968 | A- 91 → A 93 | — | Producer-input custody on unknown outcomes protects raw-state `run_table`. |
| ct-q05l | B+ 87 → A- 90 | — | Refuses unqualified R2 operations in the bucket that holds raw data. |
| ct-xq1y | — | A- 90 → A- 92 | Refusing unknown fields stops silent loss of `merge`/`relationship` on raw-state updates. The `partition_by` strip only affects layout. |
| ct-oxg6 | A- 90 → A- 92 | C 76 → C+ 78 | Pinning protects raw writers. The mutable-default regression doesn't reach them. |
| ct-qdkd | — | B- 82 → C+ 79 | Bundled a reclaim-by-default planner (R3). Inert today, but the wrong default for a bucket holding raw data. |
| ct-mi03 | B- 80 → C 72 | — | Much of the contract protected derived values, old pins and migration state. Raw-bucket isolation was never a guardrail. |
| ct-jo8n | B 86 → C 74 | C 74 → C+ 78 | Release back-compat for an unused pilot. Its worst defect (P1) is now low impact. |
| ct-nc7l | C 75 → D 65 | — | Gate built around preserving old pins and review decisions, plus worktree ceremony. |
| ct-sb0s | C+ 78 → D+ 68 | C 75 → C+ 77 | Native evidence for derived review provenance; the R2-parity gap no longer matters. |
| ct-qkvr | A 93 → B 85 | C+ 77 → C+ 79 | Pilot history; the uniqueness bug is latent, not live. |
| ct-nloa | A- 90 → B- 80 | — | Pilot perf. |
| ct-n6lj | A- 90 → C+ 78 | — | Incremental derived views. At greenfield scale, full recompute is the plainest design. |
| ct-vt7i | A- 90 → B- 82 | — | Derived-aggregate qualification for an unused consumer. |
| ct-mpsp | C+ 77 → C- 70 | — | Speculative partitioning for the pilot. |
| ct-lcbc | A- 90 → B- 80 | — | Bounds derived history that doesn't exist and adds a deletion-capable path. |
| ct-gfv8 | B+ 87 → B- 80 | — | Exposes that deletion-capable maintenance route with no raw-safety boundary. |
| ct-wmtx | A 94 → B 85 | — | Good discipline, but solves future history cost. |
| ct-wjce | A- 91 → B 85 | — | Micro-optimization of derived preparation. |

Unchanged: ct-n7la, ct-tcfg, ct-x0nk, ct-xl0y, and every grade not shown above.
New batch averages: proposal 87.7 → 83.5 · work 79.4 → 79.7.

## 4. Keep / simplify / delete

- **news_lake DocSpec stack** (`storage/docspec/*`, ~4,300 LOC, ~2,500-line test, CLI): **delete or freeze.** If news is revived, capture raw to R2 with immutable receipts and rebuild views by full recompute. Drop auto-compaction, JSON selectors, incremental bridges, time-keyed dedup and read_keys upserts. (jo8n, n6lj, nloa, qkvr, mpsp app side, vt7i receipt.)
- **Derived lifecycle/retention/removal** (lcbc, gfv8, wmtx, plan_protected_retention):
  - Never run removal or compaction against R2.
  - Make the planner protect by default, or delete its reclaim classification.
  - **Move the native catalog out of `congressional-tech-raw`**, into its own bucket or prefix, with credentials that cannot write or delete `bodies/` or receipts. Add a bucket policy (object lock or deny-delete) on raw prefixes.
- **Raw-write custody** (q968, m9td, n7la, q05l, xq1y): **keep.**
  - Simplify by forbidding `stream_ipc` for raw writers, or giving IPC the same custody.
  - Delete the string-matched fallbacks: `client.py:516` partition_by strip, the operation_conflict row-group rewrite, the `raw_storage.py:1226` merge-drop.
- **Runtime identity** (oxg6, ugqq, x0nk): **keep, simplify.**
  - One constant (revision + digest) that setup must match before any R2 access.
  - Delete `resolve_docspec_binary` search paths (`binary.py:20-43`).
  - Require an explicit binary + digest everywhere.
- **Native receipts for review provenance** (sb0s): **delete.** The raw capture receipts in R2 are the provenance authority.
- **Engine perf work** (xl0y, wmtx, wjce, vt7i, mpsp engine side): **stop.** No users, no scale.
- **Process** (nc7l gate, epic CS300 grading): **delete.** Replace with one invariant suite: no code path deletes or overwrites under raw prefixes; raw writers run only the pinned engine; raw-state writes keep custody.
- ct-tcfg: keep; add one bare `cargo test --no-run` line to `scripts/check`.
