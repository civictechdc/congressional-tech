# mi03a addendum: greenfield lens

Premise: nothing uses this system yet. The only thing that must survive is the raw/source data: the captured files and bytes in R2 `congressional-tech-raw`, their receipts and their provenance. Everything derived from them can be rebuilt. This addendum revisits `mi03a-verdicts.md`, which is unchanged. Paths are relative to `/Users/mikewolfd/Work/congressional-tech` unless prefixed with `rs:` (`/Users/mikewolfd/Work/spicy-stack/docspec-rs`). This was a read-only review.

## 1. Raw-data risks, highest first

| # | Risk | Evidence | Reachable from production today? |
|---|---|---|---|
| R1 | **The raw-state selector is rewritten in place with no old-vs-new value check (ct-dmca).** `upgrade-source-rules` evolves the raw URL-state leaves (outcome, sha256, body_key provenance). It adds a scalar backfill group, then publishes a new raw selector over `RAW_KEY`. The only check is a selector readback. No step compares the evolved leaf values with the base leaf before publishing. | `packages/congress_api/src/congress_api/cli/raw_sync.py:84,500-502` → `retention/catalog_raw_updates.py:336-358` → `retention/raw_storage.py:1300-1450` (selector write at `:1279-1298`) | **Yes**, through `raw_sync --upgrade-source-rules` whenever the stored state schema differs from `STATE_SCHEMA`. The old native versions stay immutable, so this is a provenance-pointer risk, not byte loss. |
| R2 | **Unverified local files are substituted for pinned raw receipts and state.** This comes from ct-2ukk, outside this batch, but it lives in the same raw-custody code. In production only (`PYTEST_CURRENT_TEST` unset): `iter_states_for` reads `output/incremental-updates-20261019/adoption-inputs/state.parquet` whenever its row count matches. `changed()` reads `.cache/docspec-catalog/captures-0.parquet` when the schema and row-group counts match. Neither checks a digest. | `retention/raw_storage.py:655-672`; `retention/source_capture_inputs.py:61-74`; consumed at `retention/catalog_raw_updates.py:591` and `retention/source_replay.py:229,260` | **Yes**, on any machine where those files exist. A stale copy silently replaces the R2 provenance seen by rule upgrades and catalog builds. Tests can't see this because the branch is skipped under pytest. |
| R3 | **The retention planner ignores native protection (ct-a70m).** The parser expects `path/protected/status/reasons`, but the engine returns `objects:[{object, blocker}]`. Any raw-dataset object the engine protects would be listed as "reclaimable". | `retention/native_capacity.py:477-540` vs `rs:src/model/retention.rs:83-99` | **No, latent.** The CLI passes no objects (`cli/raw_sync.py:437`). `plan_removal` runs only when a `removal_id` is given. The Python client has no method for `/retention/removal/execute` (grep of `packages/docspec_client/src/docspec_client/client.py`). It becomes dangerous the moment someone wires deletion to this plan. |
| R4 | **Automatic retries of raw-table commits whose outcome is unknown (ct-3faj regression).** `run_table` and `update_table` resubmit when stderr contains 'commit state is unknown', 'remote_unconfirmed' or '502/503/504'. Raw capture and state leaves on R2 go through `run_table`. | `packages/docspec_client/src/docspec_client/client.py:501-552,720-770`; raw writers at `retention/raw_storage.py:1066,1075,1217` | **Yes.** Native operation-id idempotency probably makes the replay safe, but this policy was never qualified, and it broke the ticket's "no automatic retry" rule. Low-to-medium. |
| R5 | **Hand-rolled key pruning decides which raw-state rows an Update replaces (ct-csyg).** If it skips a file that holds a key, a URL could end up with duplicate or stale state rows. | `rs:src/engine/key_pruning.rs`, `rs:src/engine/write/compaction.rs:66-73`; raw Update at `retention/raw_storage.py:1187-1233` (schema-evolved leaves only) | **Yes, narrowly**: only after R1 has run. It is guarded by exhaustive oracle tests (`rs:381108c`). Low. |
| R6 | **Qualification data was written into the raw bucket (ct-3180)**, under `s3://congressional-tech-raw/__r2_data_catalog/docspec-qualification-20261019/…`. That bucket is also the public bucket. | Receipt `output/docspec-reuse-20261020/ct-3180-r2-qualification/verification-receipt.json`; `retention/r2_edge_rules.py:17,20-27` | One-off, and isolated by owned prefix. The prefix is not on the public allowlist (only `/viewer-publications/` and `/exports/` are). Low, but the practice should stop. |
| R7 | **The raw bucket is the public bucket** (ct-te1p, adjacent to this batch). `/exports/**` is publicly readable with a broad pattern. This batch's export sanitizer (ct-3li2) is what keeps private field metadata out of anything written there. | `retention/r2_edge_rules.py:17,27` | Yes, for anything written under `/exports/`. This is exposure risk, not loss. A separate public bucket is the plain fix. |
| R8 | **Owner close kills a draining host** (ct-bt1q): SIGINT, then SIGTERM after about 5 s, then SIGKILL. | `packages/docspec_client/src/docspec_client/host.py:296-316` | Yes. Admitted raw writes may be cut off, but native recovery state and retained producer inputs survive (ct-3faj). Low. |

No item in this batch deletes R2 raw objects. Compaction (`compact`, `compact_lifecycle`) is called only from news_lake, which is local (`packages/news_lake/src/news_lake/storage/docspec/compaction.py:139,248` return early for remote). No Python path executes a native removal.

## 2. Problems that drop away or shrink

- **ct-adu0 / ct-ccy4.** The production shortcuts that trust receipts without hashing (`catalog_dependency_preparation.py:195-210,362`) affect only rebuildable dependency preparation. Severity falls from "unqualified production path" to "a code-hygiene issue that can produce a wrong derived build". Resume and receipt reuse for derived prep are nice-to-have, not a requirement.
- **ct-dzyf.** O(table) Python reads during abandon of news cycles: irrelevant. Rebuilding is acceptable, so abandon and rollback are optional.
- **ct-4nyy / ct-f11a.** Old-export readback, lost-response export replay, and the extra hashing of hard-linked files are compatibility polish for derived exports. They drop away. The dual C5 implementation still matters only because a wrong public export is an exposure problem.
- **ct-8ax6.** News lake file fragmentation in a local lake nobody uses: low priority. The engine already coalesces (ss-7hrv).
- **ct-13cn / ct-gziq.** Manufactured consumers only cost time and disk on derived prep. Raw risk is nil: both guard on `native.remote is None` (`source_observations.py:737-740`, `catalog_dependency_storage.py:684-692,797-800`). They are still worth deleting.
- **ct-a70m.** Protecting "application releases, exports, active readers, restore prerequisites" is protecting derived data. Only the planner's latent misreading (R3) still matters.
- **ct-eipa.** The leaf-size drift to 16,384 rows: irrelevant. It is a derived-layout performance question.
- **ct-gf8i / ct-csjp / ct-5fkx.** Derived news views. The remaining concerns are only about efficiency.

## 3. Grade changes (old → new; unlisted grades stay the same)

| ticket | grade | old → new | reason |
|---|---|---|---|
| ct-3faj | proposal | A- 90 → A 94 | It protects the inputs of raw capture and state commits when the outcome is unknown, the only custody that touches raw provenance. |
| ct-dmca | proposal | B- 80 → C- 70 | It invests in in-place evolution and continuous backfill of rebuildable data, and points that machinery at raw provenance. |
| ct-dmca | work | D- 60 → F 55 | It republishes the raw-state selector with no old-vs-new value equality check (R1). |
| ct-a70m | proposal | C+ 78 → D 65 | A retention planner for derived releases, exports and restore is not needed. The right greenfield policy is "never delete raw". |
| ct-13cn | proposal | C- 72 → D+ 68 | It preserves review binding and dependency policy for derived data no one uses. |
| ct-gziq | proposal | C 74 → C- 70 | Native refresh for derived summaries with no consumer. |
| ct-dzyf | proposal | B+ 88 → B- 80 | Rollback machinery for rebuildable news data. |
| ct-4nyy | proposal | B- 82 → C+ 78 | Old-export reads and lost-response replay for derived exports. |
| ct-f11a | proposal | B+ 88 → B 85 | Old-export pin readback: compatibility nobody needs. |
| ct-8ax6 | proposal | B 85 → B- 82 | Effort spent preserving lineage, replay and abandon of derived releases. |
| ct-3180 | proposal | B 85 → B- 82 | Qualification ran inside the raw (and public) bucket. |
| ct-adu0 | work | C 74 → C+ 78 | Its production shortcuts endanger only rebuildable derived prep. |
| ct-ccy4 | work | C- 72 → C 75 | Same reason. |

New averages: proposal 86.2 → **84.2**, work 77.2 → **77.3**.

## 4. Keep / simplify / delete, going forward

- **docspec_client transport (ct-egpe, ct-copj, ct-bt1q, ct-3faj): KEEP. It is the raw writers' custody layer.**
  - SIMPLIFY by deleting the substring retry loop and the compatibility fallbacks for older engines (415 → Parquet, the `partition_by` "unknown field" retry, legacy row-group rewrite) at `client.py:465-552,683-770`.
  - Delete the test seam at `host.py:177-179` and the `congress_api.retention.docspec`/`docspec_host` shims. With one pinned engine, none of this is needed.
- **Raw state evolution (ct-dmca): DELETE `evolve_state_schema`, the rule-upgrade path that calls it, and the default scalar backfills.**
  - Never evolve raw provenance in place. For a raw schema change, write a new raw generation from receipts, verified row for row against the old one, and rebuild the derived data.
- **native_features consumers (ct-13cn, ct-gziq): DELETE** the scratch-scope datasets, the alias summaries, the `last_change_report` and `last_refresh_summary` side effects, and the operator-status change count. Keep at most the thin `compare`/`changes`/`refresh` client methods.
- **Retention planner (ct-a70m): DELETE** `plan_protected_retention` and the `retention-plan` CLI mode. Replace them with one guard test asserting that no Python path can call `/retention/removal/execute` or delete under the raw prefixes.
- **news_lake (ct-5fkx, ct-8ax6, ct-dzyf, ct-4nyy, ct-f11a, ct-gf8i): SIMPLIFY radically.**
  - One backend: drop the PyIceberg "reference oracle" lake.
  - Drop the app-level compaction; the engine coalesces.
  - Drop abandon/rollback; rebuild instead.
  - Keep one C5 policy (native) with expiry as a predicate.
  - If news captures are ever raw-of-record, move their bytes and receipts under the same raw-custody rules as congress data.
- **Typed preparation (ct-adu0, ct-ccy4): KEEP the DuckDB external sort** (it makes rebuilds fast). SIMPLIFY by deleting the receipt-resume machinery and every `PYTEST_CURRENT_TEST` branch and repo-root cache shortcut. Treat preparation as disposable scratch.
- **Engine tickets (ct-3li2, ct-cpio, ct-clvr, ct-csyg, ct-csjp, ct-5fkx engine side): KEEP.**
  - Merge the duplicate export sanitizer and the three copies of the footer accounting into one.
  - For ct-csyg, keep the oracle tests. Its correctness now guards raw-state Updates (R5).
- **R2 layout (adjacent): SPLIT the public bucket from `congressional-tech-raw`**, and stop running qualification inside the raw bucket (R6, R7).
- **Raw verification (adjacent, ct-2ukk): DELETE the local-file substitutions** at `raw_storage.py:655-672` and `source_capture_inputs.py:61-74` (R2). Raw reads should come only from pinned, digest-verified objects.
