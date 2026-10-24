# mi03b efficiency audit (read-only)

**Scope:** my area of the surviving code: the `docspec_client` transport, raw_storage's native write and read path (custody), the news_lake DocSpec backend, and the engine pieces my batch touched (lifecycle catalog and Update key pruning).
**Code read at:** congressional-tech `c858a5a2` (the primary checkout's HEAD; `54a68ac7` is on the plan branch) and docspec-rs `d9c6719`.
**Plan read:** `simplification-plan-20261024.md`. I did not touch either worktree.

**Measurement status**
- **M1 measured** (project venv, `mi03b-efficiency-probe_test.py`; results in `mi03b-efficiency-results.json`).
- **M2/M3 could not run.** `spicy-stack/docspec-rs/target/` (release and debug binaries) disappeared during this pass. I did not remove it. The only binary left is the linux-amd64 artifact, and I ran no cargo.
- Engine call and revision counts below are therefore **reasoned, not measured**, unless they cite an existing measurement.
- Real sizes, measured from local copies (`output/incremental-updates-20261019/adoption-inputs`):
  - S = **1,298,420** state rows;
  - N = **3,909,134** capture rows.
- Code constants: leaves split 16 ways by hex prefix of a SHA-256 key (`partition_routing.py:28-57`) when a leaf exceeds `max_state_rows = 16,384` (`raw_storage.py:785`). Capture default `--limit 20000` (`capture-raw-sources.yml:99-102`). The capture job runs daily (`:90`).

Variables: S state rows; B body-metadata rows; N capture rows; U state updates per run; C new captures per run; L leaves (about S / 5k; **L ≈ 256** for S = 1.3M at depth 2); d routing depth (2); F files per news table; H history (polls/operations).

---

## Ranked findings (cost at today's scale)

### 1. Each capture run rewrites the whole raw state index: O(S), not O(U)
- **Path.** `RawStorage.prepare`, run on every capture (`raw_storage.py:1144-1258`). Bodies follow the same pattern (`:972-997`).
- **Mechanism.** State keys are SHA-256 of the URL and are routed uniformly into L immutable leaves (one engine dataset per leaf, `_candidate`, `:1058-1075`). Any update re-reads, rebuilds and re-Builds its **whole leaf**.
  - Expected leaves touched = L·(1 − e^(−U/L)).
  - At L ≈ 256, U = 1,000 already touches 98%; the default U ≤ 20,000 touches about 100%.
  - So a capture run rewrites about all **1.3M state rows**: about 256 engine Builds, plus as many body-leaf Builds.
- **Repeated per touched leaf:**
  - one engine stream read with an Arrow→Python→Arrow round trip (`:923`);
  - `prior.to_pylist()` (`:1153`); `updates.to_pylist()` **twice** (`:1146`, `:1158`);
  - `from_pylist` (`:1177`); `table.equals(prior)` (`:1178`);
  - per split part, **two more** `to_pylist()` and one `from_pylist` just for `decoded_bytes` and `schedule` (`:1239-1240`, `:1253-1254`);
  - a Parquet write; a full blake3 read (`client.py:411`);
  - engine admission (re-read, digest verify, decode), then per-phase lifecycle commits. ct-lcbc's profiling cited about 11 lifecycle revisions per operation;
  - one routing `replace` that rewrites the root path for **each** touched leaf (`:1257`; bodies `:996`): L·d page versions per run, most never referenced.
- **Big O per run.**
  - Time and I/O: O(S + B) rows read, converted (×4 to Python) and written, plus O(L) engine Builds × O(phases) catalog commits.
  - Memory: O(leaf).
  - It grows with **history (S, B)**, not with change (U).
- **Easy way (decision 6).** One state dataset (and one body dataset) per kind, updated with the engine's keyed `update_table` plus the existing `STATE_MERGE_SPEC` (`raw_storage.py:390`), bucket-partitioned on the key (engine `Transform::Bucket`; `STATE_PARTITION_SPEC` already exists). Only the files holding changed keys are rewritten. Reads use `read_keys` (one stream, key-pruned) instead of route lookup plus whole-leaf decode.
- **Evidence.** S, N, the leaf limit and the 16-way split are measured or read from code. The touched fraction is arithmetic. The engine commit count is reasoned (no binary).
- **Plan impact.** Promote **Q7** from "only if per-phase commits are too slow" to a scheduled decision. The O(S) rewrite remains even with deferred commits; it comes from the layout, not the commit protocol. Gate it on Step 0 Run A: if state can be derived from receipts, rebuild state into the new layout instead of migrating it.

### 2. Arrow→Python→Arrow round trips exist only to make a self-made byte count match
- **Sites:** `raw_storage.py:923` (every leaf read), `:992` (body leaves), `:1136` (every capture batch), `:1239`, `:1253` (state parts).
- **Why they exist:** the comment at `:918-921` says native IPC and Arrow `take` allocate validity bitmaps differently, so `nbytes` varies. Both writer and reader round-trip so that the stored `decoded_bytes` equals the read-back `nbytes` exactly.
- **What the check adds:** nothing beyond the engine's verified pin (row count plus content digest; checked at `:891-893`) and the streaming budget (`size`, `:911-914`).
- **Measured (M1, 21-column `NATIVE_CAPTURE_SCHEMA`, 100k-row slice):**
  - round trip 0.237 s, **2.37 µs/row**;
  - `Table.nbytes` 41 µs, the same 83.5 MB;
  - extrapolated **9.3 s per pass over N = 3.9M** captures, plus every state read and write (finding 1 multiplies this per run).
- **Easy way:** drop the exact-equality check. Keep the `size` budget and the engine pin verification. Existing `decoded_bytes` values in `raw.json` can stay as budget hints.
- **Plan impact:** a small addition to WS1/WS2 (raw_storage).

### 3. news_lake export computes C5 three times and materializes the corpus in Python
Applies to the DocSpec backend, which survives (decision 2).
- **Path:** `read_release` (`lake.py:972-978`) reads every table into Python dicts. `export_authorized` (`storage/docspec/export.py`) then:
  - computes expired ids from captures (`:84-89`);
  - runs the Python `export_release`, which deep-copies the whole release (`analysis/export.py:64`) and runs `validate_shape` plus a credential check on every record (`:69-71`, `:115-116`);
  - compares `rows == orig_rows` per table (`:104`);
  - exports captures and versions again through the engine's C5 `ExportPolicy` (`:111-141`);
  - hashes whole tables with `content_digest([..., rows])` to name a staging operation (`:146`).
- **Big O per export:** O(N_news) × about 5 passes, 2× corpus memory. Only the engine pass is needed to produce the files.
- **Plan impact (changes WS8 fix 4).** The plan keeps Python as the single C5 authority and deletes the native policy. Under decision 6 and this cost, the reverse is cheaper:
  - keep the engine `ExportPolicy` (it streams from pins);
  - compute expired capture ids with an engine-side projected read (`id`, `retain_until`), not a full Python release read;
  - keep Python `export_release` only as a test oracle (Q6), behind the same differential test, including `retain_until == now`.
- **Evidence:** reasoned from code; not measured.

### 4. Reverting news append keys to `['id']` scans every file on every poll
WS8 fix 2.
- **Big O per poll, per append table:** O(F_t) files probed (`id` column only). With compaction that becomes O(N_t) id bytes per poll, so it grows with history.
- **Existing measurement** (ct-pgxn, cited in `spicy-stack/.tickets/ss-wie5.md`):
  - `['id']` on uuid5 keys adds **470 ms at 720 files** and **485 ms at 1,079**;
  - extrapolated about **5.2 s per table per poll at one year** uncompacted;
  - eight append tables use time keys today (`files_scanned` 720 → 0).
- **Assessment:** correctness (probe P2) justifies the revert, but per-poll cost becomes O(history).
- **Easy way, when it matters:** engine bucket partitioning on `id` for those tables, so an id lookup prunes to 1/n of files. This is generic and already supported, unlike bloom filters (declined in ss-wie5).
- **Plan impact:** none now. Make the WS8 "measure `['id']` with compaction on" step use one-year volume, and write the bucket-partition fallback into the decision rule.

### 5. Removing automatic lifecycle compaction leaves news lifecycle growth unbounded
WS8 fix 1.
- **Engine behavior:** without compaction, each dataset keeps every operation's records. Each commit clones the live key map, O(K) (`docspec-rs/src/catalog.rs:715`). Cold opens replay O(revisions). History counts against `max_metadata_bytes` (32 MiB) until a commit is refused (`catalog.rs:713-714` comment; ct-lcbc's numbers: about 11 revisions per op, about 250 per dataset per day when polled hourly).
- **Big O:** O(H) per commit, O(H²) cumulative, then refusal.
- **Plan impact (changes WS8 fix 1).** Don't make compaction operator-only. Make compaction keep app-published release versions. The engine has no public "retain this version" primitive; protection today covers only head, export pins, reader grants and incomplete ops (`retention/compaction.rs:235-300`). Add a generic retain/pin primitive to docspec-rs (decision 6), then keep periodic compaction. Until then, the operator-only version grows without bound if the backend ever polls.
- **Evidence:** reasoned; engine not run.

### 6. Each producer file is read three times per submission
- **Path:** `run_table` / `update_table` (`client.py:482-497`, `686-716`).
  - Python writes the Parquet file once.
  - It reads it whole into memory for blake3 (`hash_input`, `:406-412`, `read_bytes()`).
  - The engine re-reads it to verify the digest and decodes it.
- **Big O:** O(bytes) × 3 per submission; O(file) peak memory in Python.
- **Easy way:** hash while writing (wrap the Parquet sink in a blake3 hasher), or stream with `blake3().update_mmap(path)`. That drops one read and the in-memory copy. The engine re-read stays: it is the custody check across the process boundary.
- **Cost today:** about 380 MB of raw Parquet per full rebuild, so low. Fold it into WS3 step 2 (the single submission owner).
- **Already fine:**
  - the binary digest is cached per process (`client.py:213-221`);
  - pin lookups are cached (`_verified_pins`, `:1013-1018`);
  - retained-input discovery is O(retained attempts).

### 7. State reads re-validate rows that were already verified
- **Scheduling path:** `raw_state_routes.candidates`. Each leaf it reads is round-tripped (`raw_storage.py:923`), converted again (`raw_state_routes.py:150`), and `summarize(rows)` is recomputed and compared to the page summary (`:151-152`). The page bytes were already hash-checked by `MetadataObjects.read`, and the leaf by the engine pin. That is three checks of the same facts per leaf. The pruning by schedule summary itself is sound.
- **`states_for`** (used by corpus_recovery transfer, inventory and preservation, and by the recovery queue): one route lookup per URL, then a whole touched leaf decoded per group (`raw_storage.py:633-645`). For a recovery batch of thousands of URLs that is about all of S per call. Finding 1's `read_keys` replaces it.
- **Evidence:** reasoned.

### 8. The raw selector publish reads raw.json twice around one conditional write
- **Path:** read before write, conditional `put_index_selector`, readback compare (`raw_storage.py:1283-1290`).
- **Cost:** O(1) per run, ≤1 MiB.
- **Easy way:** the PUT's ETag (MD5 of exactly those bytes) already confirms the write.
- **Plan impact:** none. Cheap, and the plan's keep list accepts readback on raw paths. Revisit only together with WS2's verifier.

---

## One line each (code the plan deletes; no plan change)

- `iter_states_for`'s production branch decodes **all** leaves concurrently into memory (O(S) RAM) when more than 512 URLs are requested, unlike its docstring and its pytest branch (`raw_storage.py:683-702`). Its only caller goes with WS7.
- The Python retention planner (WS2 step 6) has no efficiency concern worth keeping it for. Delete it as planned.
- The engine's hand-written SHA-256 and calendar transforms: confirm WS9 steps 8–9 (`sha2` crate; Iceberg transform functions).

## What changes the plan

1. **Q7 becomes required, not conditional** (finding 1). The one-dataset-per-leaf raw layout costs O(S + B) per capture run whatever the commit protocol. Decide it after Step 0 Run A, using engine keyed Update with bucket partitioning.
2. **WS8 fix 4 should keep the engine C5 policy**, not the Python one (finding 3). Python stays as the test oracle.
3. **WS8 fix 1 should be "compaction keeps release pins" via a generic engine retain primitive**, not "operator-only compaction" (finding 5).
4. **Small additions:** drop the `decoded_bytes` round trips (finding 2) and hash while writing (finding 6) inside WS1–WS3; multi-prefix routing replace inside WS1's batched-upload step.
