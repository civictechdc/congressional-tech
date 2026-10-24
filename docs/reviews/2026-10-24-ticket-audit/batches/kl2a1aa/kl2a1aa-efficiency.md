# kl2a1aa: efficiency audit of surviving hot paths (read-only)

Code read at congressional-tech `main` c858a5a2 and docspec-rs d9c6719. The `54a68ac7` fixes (stored_sha256, engine pin, delete_gzip) sit on branches only, and are excluded from these findings.

**Measurements.** All ran through the project venv: `.venv/bin/python -I <script>`. The scripts are in this directory with the `kl2a1aa-` prefix. They use only the project's own in-memory fixtures (`tests/native_memory_helpers.py`, `testing_fakes.py`) or a fake S3 client, with no network and no engine binary. Each figure below is labeled either **measured** or **reasoned, not measured**.

**Variables:**

| Variable | Meaning |
|---|---|
| S | URL-state rows |
| B | unique bodies; the body index holds about 2B rows (`body:` and `sha:` keys) |
| K | leaves per index |
| L_leaf | rows per leaf |
| U | state rows changed per run |
| C | new captures/bodies per run |
| Q | body lookups per run |
| R | receipts |
| H | runs (history) |
| N | news corpus records |
| F | bytes per browser file |
| L / G | raw / gzipped bytes of one body |

**Scale observed locally.** I read the cached routing pages in `.cache/docspec-catalog/r2-native-manifests` (one generation of unknown date):
- **raw-state-v1:** 256 leaves at depth 2 (prefix length 2), S ≈ 1,298,420 rows, about 5,074 rows per leaf.
- **raw-bodies-v1:** 256 leaves, 2,072,512 index rows (B ≈ 1.04M), about 8,098 rows per leaf.

(**measured**, `kl2a1aa-raw_index_shape.py`)

---

## 1. The raw index rewrites whole leaves every run (state and body index)

Code: `raw_storage.py:1141-1256` (state) and `:943-997` (bodies). The candidate is written as a new dataset per leaf (`_candidate`, `:1058-1075`).

**Big O per run:**
- Rows rewritten ≈ (touched leaves) × L_leaf, where touched leaves ≈ K(1 − e^(−U/K)). Once U ≳ K, that is O(S) for state and O(B) for the body index. It does not scale with U or C.
- Python cost per touched leaf:
  - 2–5 full row conversions (`prior.to_pylist()` at `:1153` and `:1208`; `from_pylist` at `:1176`; `from_pylist(part.to_pylist())` at `:1239`, `:1253` and `:991`; `summarize(part.to_pylist())` at `:1240`);
  - one SHA-256 per row in `split_partition` (`partition_routing.py:43`).
- Storage grows by about one full index copy per run. That is O(H·(S+B)), and nothing reclaims it; WS2 step 6 deletes the reclaim planner.

**Measured** (`kl2a1aa-measure_state_update.py`, `kl2a1aa-measure_body_lookup.py`):

| Index | Changed rows | Index size | Leaf datasets rewritten | Rows written | Amplification |
|---|---|---|---|---|---|
| state | U=200 | S=20,000 | 148 | 11,677 | 58× |
| state | U=200 | S=40,000 | 148 | 23,081 | 115× (doubles with S) |
| body | 200 | N=2,000 | 137 | 2,371 | 12× |
| body | 200 | N=8,000 | 137 | 8,815 | 44× (grows with N) |

`key_hash` calls equal the rows written, plus U.

**At today's scale (reasoned):** with K=256, about 1,000 state changes and 500 new bodies per run rewrite essentially all of S plus the body index. That is about 3.3M rows as about 500 new datasets, to record about 2,000 changed rows.

**Do once.**
- Python `_merge_states` (`:1077`, called at `:1163`) merges rows that the engine then merges again with `STATE_MERGE_SPEC` on the evolved path (`:1215-1223`).
- Each row's route hash is recomputed on every rewrite.

**Easy way.**
- Use the engine's keyed `update_table(..., keys=[STATE_KEY_FIELD], merge=STATE_MERGE_SPEC)` and send only the U changed rows. That delta path already exists for schema-evolved leaves (`:1196-1230`).
- The blocker is the `_candidate` isolation rule (`:1059-1061`: an unselected update advances the dataset's latest). Either the engine needs "update from an explicit base without advancing latest", or the app accepts the advance under the raw selector's CAS.
- Cheap interim fix: use `part.nbytes` instead of `from_pylist(part.to_pylist())` (**measured** 17 ms vs 0.04 ms per 16k-row leaf, same value, `kl2a1aa-measure_roundtrip.py`), and drop the Python pre-merge.

**Plan impact.** This is the measurement Q7 asks for. The keep list's "raw-side routing" is sound for correctness but costs O(S+B) per run and O(H·(S+B)) in storage. A step smaller than Q7's migration is to use the existing delta path for all leaves.

## 2. Body lookups during capture thrash a one-leaf cache

Code: `raw_storage.py:600-609`; `_BodyLookup` in `raw_archive.py:584-603`; called per digest from `raw_sync.py:443`.

**Big O.** O(Q) leaf reads of L_leaf rows each, so O(Q·L_leaf) rows decoded, plus an O(L_leaf) filter per lookup. A miss on a new body also reads a leaf.

**Measured** (`kl2a1aa-measure_body_lookup.py`):
- 500 lookups in capture order made 498 native leaf reads.
- The same lookups sorted by route made 221, which is the number of distinct leaves.
- The result is the same at both N=2,000 and N=8,000.

**At today's scale (reasoned):** each lookup decodes an 8,098-row leaf, so Q=5,000 decodes about 40M rows per run. Reading each leaf once would decode at most 2.07M.

**Easy way.** Group pending digests by route, or keep a bounded LRU of leaf key-sets. Better, use the engine's `read_keys` (key pruning) on the leaf dataset. States already batch by leaf (`states_for`, `raw_storage.py:633-640`), so make bodies do the same. **Not in the plan.**

## 3. `blake3` is not a declared dependency; the hand-rolled fallback is about 380× slower

Code:
- The fallback is `docspec_client/transport.py:18-125`, a pure-Python BLAKE3.
- It is used by `run_ipc`/`update_ipc` (`client.py:432`, `:605`).
- When the extension is missing, `hash_input` (`client.py:403-413`) spawns `docspec hash` once per file.

**Evidence.**
- `packages/docspec_client/pyproject.toml:6-9` declares only httpx and pyarrow.
- No toml, lock or workflow file names blake3.
- The local venv has blake3 1.0.11, installed by uv and required by no package.

**Measured** (`kl2a1aa-measure_blake3.py`): on 1 MiB, the extension takes 0.0024 s and the fallback 0.90 s (1.11 MiB/s). The digests match.

**Impact.** In CI and any fresh venv, every news_lake IPC commit and export hashes its bytes at about 1 MiB/s. `stream_ipc` defaults to True (`lake.py:68`, `:424`; `incremental.py:412`, `:484`; `docspec/export.py:162`).

**Easy way.** Declare `blake3` (a maintained, Rust-backed package) and delete the fallback, about 100 lines. Alternatively, let the engine compute the digest it already verifies. **Add to WS3.**

## 4. news_lake publishing re-reads and re-validates the whole corpus every cycle

Code: `lake.py:707-721`.

**Big O.** O(N) reads and validation per cycle, so O(H·N) over history, with O(N) Python dicts in memory. `check_corpus` also contains the superlinear pieces the fork reviewer found (O(D·K) decisions, O(outputs × inputs)).

**Do once.**
- Each record is validated at commit (`lake.py:522`) and again in every later publish (`semantics.py:124`).
- `mark_snapshots_validated` writes `validated_snapshots` (`control.py:291`), but the DocSpec path never reads it. Only the PyIceberg oracle reads it (`releases.py:111-134`), and WS8 deletes that oracle.

**Easy way.** Validate the delta, and use pinned dataset versions to skip unchanged tables. Use engine key lookups for cross-record checks.

**Cost today:** low (pilot scale). **Reasoned, not measured.** **Add to WS8.**

## 5. The explorer re-exports through docspec into a throwaway workspace

Code: `export.py:957-984` and `docspec_views.py:564-627`, `:664-687`, running in `publish-explorer.yml:104` (workspace in `$RUNNER_TEMP`).

**Big O per run.** For each browser file F:
- one engine hash (`hash_input`);
- an engine import (`/run`, which reads F and writes a dataset);
- an engine export (writes F again);
- 2 redundant SHA-256 passes. `export.py:964` recomputes digests after `sync_export`, although `replace_source_files=False` leaves the files unchanged, and `:984` verifies them again.

The output is thrown away, and export-pins.json records digests that don't match the published files.

**Easy way.** Delete it. Or, under decision 6, make the engine the producer and delete the Python Parquet writer. **Not in the plan** (it covers only the weekly mirror, plan:774). **Reasoned, not measured.**

## 6. Per-body hashing and I/O on the raw write path

**In-memory bodies.** Path: `prepare_capture` → `body_payload` → `R2Store.put`/`AsyncBodies.put`.
- **Measured** (`kl2a1aa-measure_body_hashing.py`, 8 MiB body): 3 SHA-256 passes and 2 MD5 passes. That is 2 SHA-256 over L (`raw_archive.py:109` and `:225`; the second re-hashes a digest already in the key), 1 SHA-256 over G (`:227`), and MD5 over G twice (`r2.py:112` and `r2.py:128`).
- Easy way: pass the known digest into `body_payload`. R2 already enforces `ContentMD5`, so compare the ETag with the MD5 computed once.

**File bodies.** Path: `retain_body_file`.
- **Measured:** the gz scratch file is read 3 times: MD5 (`r2.py:420`), upload, and SHA-256 (`body_files.py:156`).
- Easy way: compute MD5 and SHA-256 of the gz bytes while writing them (a hashing writer).

**On a 412 (orphan).** The code downloads the full object, decompresses it and hashes it twice (`raw_sync.py:413-415`; `body_files.py:137-149`). A HEAD comparison of the ETag with the local MD5 would settle identical bytes first, because gzip is deterministic (level 1, mtime 0).

**Cost:** CPU seconds per GB. Low.

## 7. Recovery import probes and reads back full objects

Code: `corpus_recovery/transfer.py:26-47`, `:105-137`.

**Per new body (reasoned from code):**
- 2 local reads of L;
- 3 SHA-256 over L and 3 over G (`:110`, `:117`, `body_payload`, the `checked_put` journal at `:29`, and `:136`);
- a full GET as an existence probe before the PUT (`:129`);
- a full GET readback after an MD5-verified PUT (`:42`);
- a full decompress-and-compare (`:134`).

**Easy way.**
- Use HEAD for existence.
- After an acknowledged PUT, trust `verify_upload`'s ETag/MD5 check.
- Keep the readback only when reconciling a lost acknowledgment.

**Plan impact.** The keep list keeps "checked_put with readback". Narrow that to the lost-acknowledgment path.

## 8. A local file of the same size suppresses raw-index page uploads

Code: `r2.py:341-351` and `:205-210`; `immutable_metadata.py:91-93`. The cache directory is `native_config.parent` (`raw_sync.py:323`), and its path contains no bucket name.

**Risk.** A stale or other-bucket cache file means a raw routing page is never uploaded, while the selector still references it. This is raw provenance. A repeat PUT with `IfNoneMatch` costs one request (412), so the skip saves almost nothing.

**Easy way.** Remove the skip and rely on the conditional PUT, or at least scope the cache by bucket. **Add to WS2.** Step 4 covers only reads.

## 9. Archive open lists every receipt

Code: `raw_archive.py:670-677`.

**Big O.** Every capture run does O(R/1000) LIST calls plus O(R) delivery-tree lookups, so it grows with history. Today that is 3 LIST calls for 2,289 receipts: cheap.

**Easy way.** Receipt keys are partitioned by owner and day (`raw_archive.py:517`), so list only the day prefixes since the selected raw generation. Low priority.

## Left alone

- The engine's `split_oversized_batch` (`batch.rs:232-360`) runs in one linear pass and compacts each slice once.
- The heap-pruned schedule scan (`raw_state_routes.py:111-160`) works.
- The engine's hand-rolled SHA-256 is already covered by WS9 step 8.
