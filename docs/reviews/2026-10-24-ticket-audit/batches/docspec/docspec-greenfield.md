# docspec batch: greenfield / raw-data addendum

Lens: nothing uses the engine yet. Only raw/source data must survive: the captured files and bytes in R2 `congressional-tech-raw`, their receipts and their provenance. Everything derived can be rebuilt. This addendum supplements `docspec-verdicts.md`; that file is unchanged. Repo paths are relative to `docspec-rs` at `d9c6719` unless prefixed `ct:`. "Pin" means `c949c67` (`ct:packages/docspec_client/src/docspec_client/models.py:16-25`).

## 0. What the engine actually holds of the raw data

- **Raw custody lives outside the engine.** Python writes receipts and bodies directly to R2, as immutable objects, before any engine call:
  - `ct:packages/congress_api/src/congress_api/retention/raw_archive.py:509-525` does `store.put(receipts/<family>/<day>/download-…jsonl.gz, immutable=True)` and only then indexes each line.
  - `ct:.../retention/r2.py:252` limits that writer to `receipts/` and `bodies/sha256/`.
- **The engine's `raw-*` datasets are an index over those receipts.** Each write is a fresh initial Build (`ct:.../retention/raw_storage.py:1058-1075`; `raw-<kind>-<hash>`, `operation='initial'`). They can be rebuilt by replaying `receipts/` (`raw_archive.py:672` already iterates `store.keys('receipts/')`).
- **The engine shares the raw bucket.** Its owned prefix is `s3://congressional-tech-raw/__r2_data_catalog/docspec-archive-v1` (`ct:.github/docspec-remote.json`, `ct:.cache/docspec-catalog/production-remote.json`). Its S3 key is bucket-scoped (R2 tokens cannot be limited to a prefix), so only engine code keeps it out of `receipts/` and `bodies/`.

## 1. Raw-data risks

| # | Risk | Evidence | In pin? | Reachable in production today? | Severity for raw |
|---|---|---|---|---|---|
| R1 | Isolation is code-only and config-only. The engine has bucket-wide write/delete credentials on the raw bucket. Nothing checks that `owned_prefix` stays clear of `receipts/` or `bodies/`. | Scope check `src/storage/remote/objects.rs:931-937` (`bucket == self.bucket && key.starts_with(prefix)`, with prefix normalised to `…/` at `:927`); create-only writes `:537,:582` (`if_not_exists(true)`); `owned_prefix` read verbatim from config | Yes | Only through a mis-set `owned_prefix`, or a future write path that skips `scope.key`. I found none today: every remote put/delete/stat in `objects.rs` calls `scope.key`; `drop_table` never purges (`src/storage/remote.rs:338-345`; `purge_table` is never called) | **Highest.** This is the one route to real raw loss. The fix is a platform primitive (section 4), not more code. |
| R2 | Remote exact-key deletion | `objects.rs:168-218`: scope-checked, size and BLAKE3 verified, expiring HEAD/DELETE-only actor; a small TOCTOU between the digest check and `delete` | Yes | Engine code only. The consumer plans removals but never executes them (`ct:.../docspec_client/client.py:1327-1330`) | Low. It cannot reach `receipts/` or `bodies/` while R1 holds. |
| R3 | False custody record for every `raw-*` write. On remote, an initial Build of `raw-*`, `catalog-*`, `obs-*` or `source-observations-*` records the remote input `ObjectRef` **without uploading the bytes**, then reads the local file instead. Availability checks and Deep verification skip inputs for those names. | `src/engine/pipeline.rs:317-335`; `src/engine/write/build.rs:362-372`; `src/engine/release_check.rs:86-93,226-229`; all `#[cfg(all(not(test), not(feature="test-util")))]`, so no test runs it | **No** (added in `b4b827d`/`97373eb`/`d05df4d`) | Yes, in a HEAD release build against R2 | Medium. No raw bytes are lost: rows land in the uploaded source group, and the input is a projection of receipts. But the engine's record of what it holds is wrong, no check can detect it, and any inventory, restore or removal closure that resolves these inputs will fail. |
| R4 | Deferred lifecycle commits. Protections and phase records stay in memory until the final commit; flush errors are discarded | `src/catalog.rs:765-790`; `src/engine/pipeline.rs:510-518`, `:111-112` | No | Yes (HEAD, prod build) | Low for raw: a crash leaves orphan objects inside the owned prefix. Nothing is deleted. |
| R5 | Sweeping local reclaim: unlinks anything under `<retained>/<dataset>/` that is outside the live closure; the head-reference walk fails open | `src/engine/retention/compaction.rs:146` (`unwrap_or_default`), `:194-230`, `:787-837`; `src/catalog.rs:1012-1055` | Yes (`65d47f7`) | No, for R2: it is gated to local storage (`compaction.rs:165`, `catalog.rs:1013-1015`) | Low. It is still the most dangerous pattern in the codebase; it must never be enabled remotely. |
| R6 | The client deletes staged producer input on "pre-admission" codes that the engine also raises after admission (`invalid_json`, `invalid_group`, …) | Pin: the client's own list `ct:.../models.py:27-45` + `client.py:62-72`; HEAD: `src/http.rs:277-286` + `src/error.rs:173` | Yes (client-side list) | Yes | Low. The staged input is rebuilt from receipts already written as immutable objects (R2/raw_archive evidence above). |
| R7 | Large payload cells are re-sliced and copied on write | `src/storage/batch.rs:232-265`, `src/storage.rs:487-497` (`c949c67`) | Yes | Yes | Low. These are copies of `bodies/`, not the originals. |

**Not a risk:** public exposure. The edge rule allow-lists only `/viewer-publications/`, `/bodies/sha256/` and `/exports/` (`ct:infra/cloudflare/congressional-data-r2-edge.json`), so `__r2_data_catalog/` is blocked by default.

**Bottom line:** in the pinned engine I found no path that can delete, overwrite or expose raw objects; the protection is `scope.key` plus `if_not_exists`. After the pin, the code adds false custody records (R3) and non-durable protections (R4), but still no raw loss.

## 2. What drops away under this lens (earlier findings re-ranked)

**Drop to low or irrelevant** (they protect rebuildable derived data, or compatibility nobody needs):
- ss-cnsn's loosened `validate_saved` check.
- ss-1txq's O(history) archive rewrite. Delete the archive instead.
- ss-g9sn's fail-open head walk and whole-workspace inventory (local derived only).
- The ss-e2it `pre_admission` mislabel as a data-loss issue.
- The ss-6cv1 `for_path` fallback. It misroutes a read; it cannot delete anything.
- ss-8tjo's broken Dagster `capabilities()`. Delete the adapter.
- ss-wrfw's "preserve an old pin".
- Legacy Format 10/11 readers, `CompletedGroups::Legacy`, alias spellings, `cli_args.rs`, route aliases. These are now "delete", not "concern".
- Real-R2 qualification of derived operations (ss-vfm6) and the restore and recovery tests. Lower priority.

**Stay high:**
- The test/production divergence (60 cfg sites). It hides what the shipped binary does.
- Consumer dataset names inside the engine (R3).
- Raw-bucket isolation (R1), which is the new top item.

**Unchanged:** the ss-sgmp unbounded cache (an ops and memory issue), and the ss-yjvy/ss-6gwu/ss-55jg scope narrowing (an honesty-of-closure issue).

## 3. Grade changes (old → new; all other grades unchanged)

None of the 37 tickets protects raw bytes, so none gains points. The only raw protection that matters (`scope.key`, `if_not_exists`, the expiring delete actor) predates this batch.

| ticket | grade | old → new | reason |
|---|---|---|---|
| ss-1txq | proposal | A- 90 → B- 80 | Its archive design keeps derived history proofs forever; the correct greenfield move was to drop old records behind the frontier. |
| ss-1txq | work | B 83 → C+ 76 | A 300-line checkpoint planner and an O(history) archive, built to keep rebuildable lineage. |
| ss-8ani | proposal | C+ 77 → C 70 | It plans a typed-key refactor of retention machinery that should mostly be deleted; the Strict<T> defense only guards local GC of derived objects. |
| ss-8tjo | proposal | C 72 → C- 66 | About a quarter of its scope unified an unused Dagster adapter and protected experiment artifacts. |
| ss-7rnt | proposal | C 74 → C- 70 | Asked to "hide/deprecate" aliases where it should have deleted them. |
| ss-7rnt | work | D 62 → D- 58 | Added backward-compatible aliases and an argv shim for zero users. |
| ss-cnsn | proposal | A- 90 → B 83 | The phantom-key bug failed safe (it kept extra derived records); calling it a "P0 silent functional bug" overstated it. |
| ss-e2it | work | C+ 74 → C+ 77 | The input-loss hazard I flagged applies only to rebuildable inputs. |
| ss-6cv1 | work | D+ 66 → C- 69 | The unfixed fallback misroutes reads but cannot delete raw data. |
| ss-wrfw | proposal | B 80 → C+ 75 | "Preserve an old pin" and historical-evidence mapping for a project nobody uses. |

New batch averages: proposal 82.5 → 81.5; work 77.4 → 77.2.

## 4. Keep / simplify / delete, by area (going forward)

| Area (approx. LOC) | Call | Why / how |
|---|---|---|
| Raw-bucket isolation (config and infra) | **Add (platform primitive)** | Move the engine's derived data to its own bucket, or at minimum give the engine no credentials on `receipts/` and `bodies/`. Put R2 bucket-lock retention rules on `receipts/` and `bodies/sha256/`, so no code bug can delete raw objects. Give the capture writer a put-only token. Make the engine refuse an `owned_prefix` that overlaps those prefixes. |
| Remote scope + create-only writes (`storage/remote/objects.rs`) | **Keep** | This is the only raw boundary in the code. |
| Production-only `cfg(not(test-util))` branches (60 sites) | **Delete** | One build should have one behavior. Delete the dataset-name branches outright: `pipeline.rs:317-335`, `release_check.rs:86-93,226-229`, `write/build.rs:362-372`. If deferred commits pay off in a measurement, make them the only mode and test them. |
| Retention / retirement / removal (`src/engine/retention`, 17.4k LOC, 8.7k non-test) | **Delete most; simplify the rest** | The consumer calls only `/retention/inspect` and `/retention/removal/plan`. For rebuildable data, keep "selected release plus readers' pins" and reclaim unselected generations by prefix. Delete the 8 retirement planners, owner grants, availability retirement, the operation-recovery receipts and the string-prefix inventory chain. |
| Restore points and remote catalog-loss restore (`engine/restore*`, `src/restore*`, ~2.4k LOC) | **Delete** | The consumer never calls them. Recovery means rebuilding from `receipts/` and `bodies/`. |
| Succession checkpoint/archive and `prove_succession` (`engine/history`, checkpoint planner ~300 LOC) | **Delete the archive; keep only the current head chain** | Historical proofs of derived releases have no user. |
| Legacy formats and compatibility (Format 10/11, `CompletedGroups::Legacy`, `cli_args.rs`, 77→~40 routes, `Resume`, AST alias spellings, `--occurrences/--values`) | **Delete** | Greenfield; no readers. |
| Lifecycle-as-Iceberg KV (`catalog.rs` 1.4k LOC: SnapshotRows, baseline compaction, gc toggles, deferred commits, cache) | **Simplify; measure an alternative** | It is an append-only KV store with heavy custody rules for derived records. Once retention shrinks, re-measure whether it needs baseline compaction at all. |
| Continuous backfill + SourceFence leases (`backfill/continuous.rs` 1.2k) | **Simplify** | The consumer uses it, but for derived columns a "build a new version, then select it" cutover is enough; the fences and leases guard rebuildable state. |
| Local sweeping reclaim (ss-g9sn) | **Keep, local only, fail-closed** | Make the head walk return its error. Assert that it can never run remotely. |
| Dagster adapter (`adapters/dagster`) | **Delete** | Unused (the consumer uses `docspec_client`) and already broken (`/capabilities`). |
| Provider qualification tests (`remote_build_provider_tests`, 3.5k LOC) | **Replace with one isolation smoke test** | Check that every engine write and delete stays under `owned_prefix`, and that a `receipts/` key is refused. Drop the derived-lifecycle provider choreography. |
| Engine features (UpdateMergeSpec, CollectSet, partition_by, export child tables, key pruning, tail coalescing, identity input aliasing) | **Keep** | They do real derived work for the consumer. Move consumer policy out of the connected-components code (the `document_id` formula and `body` naming in `connected_components.rs:27-36`, `topology.rs:24-28`). |
| Verification (`release_check.rs`, deep checks) | **Simplify** | Check once at creation. Remove the name-based skips. Keep deep checks for when they are requested. |
