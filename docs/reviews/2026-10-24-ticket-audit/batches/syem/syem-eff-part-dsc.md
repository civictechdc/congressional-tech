# syem efficiency pass, slice dsc: docspec_client transport, news_lake DocSpec backend, engine admission and read side

Read-only. Python files are identical at c858a5a2 and origin/main 56cca36d. The engine is read at docspec-rs HEAD d9c6719, with the pinned engine c949c67 checked where the two differ.

**Measurements:** `syem-eff-dsc-measure.py`, run through the project `.venv`, in-memory and tmp only:
- a synthetic 200,000-row capture-shaped table with random hex digests;
- a fake host that counts requests, writes and hashes;
- `tracemalloc`.

**What the measurements cannot see:**
- the real engine (no local docspec binary exists, and no cargo run was needed);
- remote R2 timings;
- real news datasets.

**Variables:**
- N: rows in one producer table.
- P: staged Parquet bytes.
- S: rows in a dataset or leaf version.
- C: changed rows per run.
- L: affected leaves or datasets per run.
- K: distinct pins read per process.
- H: versions between two compared releases.
- D: total entity decisions.
- n, d: news batch records and duplicates within a batch.

## 1. Producer staging and submission (`run_table`, `update_table`, `update_evidence_table`, `_write_producer_parquet`, `hash_input`)

**Big O, success path:**
- Time is O(N) cast + O(N) zstd Parquet encode + O(P) BLAKE3, plus 1 JSON request.
- I/O is P written, P read back for the hash, plus a `request.json` write.
- `update_table` with deletions adds a second small Parquet write and hash.
- Memory: `hash_input` holds the whole file, because `read_bytes()` loads it (client.py:411-412), so it is O(P) RAM.

**Measured** (200k capture-shaped rows: 69.8 MB as Arrow, 18.0 MB as Parquet):
- `run_table`: 1 request, 1 Parquet write in 0.39 s, 1 hash of 18.0 MB in 0.014 s.
- `update_table` with 1,000 deletions: 2 writes, 2 hashes, 1 request, 0.25 s.
- About 2 µs per row. 3.9M rows extrapolates to about 8 s and P ≈ 350 MB.

**Do once:**
- The success path has no repeats. Each of the 3 cloned blocks runs once per call, so the clones cost maintenance, not runtime.
- The repeats are on failure paths:
  - `operation_conflict` rewrites and re-hashes the input (client.py:522-533).
  - The merge "unknown field" fallback reads the **entire base dataset** (`source_batches(base_pin)`, client.py:735-737) and merges it as Python dicts. That is O(S_dataset) time and memory per update, growing with history rather than with C. It is dead on the c949c67 pin, which accepts `merge` (model.rs:1982), and WS3 already deletes it.
- The client hash and the engine hash cover the same bytes. The client's digest is the custody pin written into `request.json` and required by the engine (`sql_validation.rs:55`), so it buys exact replay. It costs 14 ms per 18 MB. Keep it.

**Easy way:**
- Hash with `blake3.update_mmap(path)`, or hash while writing, instead of `read_bytes()`. That removes the O(P) RAM spike.
- **Keep Parquet staging over IPC.** Measured: IPC is 69.8 MB against 18.0 MB of Parquet (3.9x more bytes to retain, upload or download), and the engine's Build reads Parquet. This supports WS3 step 5 (refuse IPC for raw writers) on efficiency grounds as well.

## 2. Engine admission and Build input (engine side)

**Local retained store:**
- `admit_source` → `copy_verified` reads P, writes P, fsyncs and hashes (storage.rs:1018-1061). The Build then reads the retained copy (P).
- Input bytes are therefore touched 5 times per Build: Python write, Python hash read, engine copy read, engine copy write, engine Build read. Then the client deletes its staging directory.
- **Easy way:** client staging (`workspace/request-*`) and engine retention share a filesystem, so the engine can `hard_link` the verified file (one hash pass, no P write or fsync). That is the pattern `derived_files.retain_verified_file` already uses in Python. Reasoned, not measured.

**Remote retained store** (CI with engine credentials; pin c949c67):
- `upload_file` hashes while uploading, in a single pass (objects.rs:557-600, `concurrent(1)`).
- `initial_source` then re-reads the input **from R2** (c949c67 write/build.rs:341-345).
- Per Build that is P up plus P down. A full raw rebuild extrapolates to about 350 MB up and 350 MB down. Reasoned from the code and the measured P per row.
- HEAD adds a *generic* local re-read: if the local `spec.input` still matches the digest (one local BLAKE3 pass), read it locally (write/build.rs:356-372, production-only `cfg`). **This is not a dataset-name predicate.** The plan's WS1 move 1 lists `write/build.rs:362-372` for deletion alongside the real name predicates (`pipeline.rs:317-335`, `completion.rs:230-237`, `release_check.rs:86-93`). Deleting it restores the R2 download.
- **Recommendation:** keep the generic local read as the single unconditional code path, with a test, and delete only the name-gated upload skips.

## 3. Read paths (`source_batches`, `read_keys`, `read_arrow`, `_read_pin_endpoint`, `changes_batches`)

**Big O:** O(S_read) streaming. `read_arrow`, `read_keys` and `_read_pin_endpoint` materialize a full table by design.

**Do once:**
- `_verify_pin` sends `GET /datasets/{d}/versions/{v}` before every first read of a pin (client.py:1010-1018). The engine's handler takes the per-dataset lock and loads the release (engine.rs:588-600), and the stream route loads it again.
- The stream's own headers already bind `docspec-dataset`, `docspec-version` and `docspec-manifest-blake3` (checked at client.py:1057, 1085, 1276, 1367; `changes_batches` checks status only).
- So each first read of a pin costs 2 requests and 2 release lookups. With one dataset per raw leaf, that is L extra round trips per run, and K per process in total, bounded by the 8,192-entry `_verified_pins` cache.
- The GET only adds comparison of the non-identity fields of the pin dict. **Easy way:** drop the pre-GET and rely on the identity headers. Reasoned, not measured.

**ArrowResponse:** 69.8 MB streamed in 64 KB chunks took 12-30 ms, against 0-3 ms direct. **Leave alone.** The 5 copies of the header check are a code cost only.

**read_changes:** `table['side'].to_pylist()` loops over C rows in Python (client.py:996-1001). `pc.value_counts` would do it. Minor.

## 4. Python re-implementation of the engine merge (`specs.py:476-692`: `_merge_row_pair`, `apply_update_merge_spec`)

**Measured:** 7.1-7.6 µs per row and ~490 B of Python memory per row on a 3-column table (200k rows: 1.4 s, 93.5 MB). Wider rows cost more.

**Surviving caller: the raw state path** (origin/main raw_storage.py):
- Per affected leaf it reads the whole prior leaf and calls `prior.to_pylist()` (:1150).
- It merges each row in Python with `_merge_states` (:1160).
- It rebuilds the leaf from Python lists, calls `to_pylist()` on the same partition 3 more times (:1206-1208, :1236-1237 and :1250-1251), then sends the delta with `merge=STATE_MERGE_SPEC` (:1221). **The engine merges again.**
- One `to_pylist`/`from_pylist` round trip is used only to get `nbytes`. Measured: 0.115 s per 65,536-row leaf, against 0.00003 s for `part.nbytes`, with an equal result.
- Cost per run is O(L × leaf rows) Python dicts. A full rebuild over 1.27M state rows is about 9 s and ≥0.6 GB at the 3-column rate.

**Easy way:** send incoming rows with `merge` to `/updates/run` (supported on the pin) and delete the Python merge engine, about 217 lines. Use `Table.nbytes`. Under decision 6, this engine-overlapping code survives the plan as written; it sits outside WS7's scope.

## 5. Hashing dependency (`blake3`)

- `blake3` is imported optionally (transport.py:10-13; client.py:23-26) but is **declared nowhere**. It is absent from uv.lock and from every pyproject.toml, and was installed into the local venv by `uv pip` on Oct 23.
- `uv sync --locked` (.github/actions/setup-python-project/action.yml:21) runs in exact mode, so CI lacks it. Two fallbacks follow:
  - IPC payloads hash with the hand-written BLAKE3 (transport.py:17-125). **Measured at 1.36 MiB/s**, against about 1.3 GB/s for the extension, roughly 1000x slower.
  - `hash_input` spawns a `docspec hash` subprocess for every producer file (client.py:413).
- IPC is used only by news_lake (`stream_ipc=True`), and news_lake runs only in validate-explorer CI tests. Production impact today is therefore limited to subprocess spawns per raw and catalog producer file.
- **Easy way:** declare `blake3`, a maintained library already in use locally, in `docspec-client`, and delete the hand-written BLAKE3, about 108 lines.

## 6. news_lake DocSpec backend

**`_dedup_incoming` is quadratic in duplicates.** Each duplicate rebuilds the whole list: `deduped = [merged if r['id']==rid else r for r in deduped]` (lake.py:266), which is O(n·d). Measured with the merge stubbed:

| records | duplicates | time |
|---:|---:|---:|
| 5,500 | 500 | 0.035 s |
| 22,000 | 2,000 | 0.57 s |
| 44,000 | 4,000 | 2.36 s |

That is about 4x per doubling. **Easy way:** keep the insertion-ordered dict `seen_in_batch` and return `list(seen_in_batch.values())`.

**Caches grow with history:**
- `_known_ids` and `_known_upsert_records` (lake.py:88-89, 297-346, 450-495) hold every id or record committed in the process, so memory is O(total).
- `_decisions` and `_decision_roots` (incremental.py:507-541) are rescanned and `apply_decisions` re-run over all D decisions on every bridge update, which grows with history rather than C.
- WS8 already deletes the `_known_*` caches. Confirmed, reasoned.

**Views re-read whole datasets after lifecycle compaction:**
- `incremental.py:293-336` accepts only the change paths `forward_changes` and `unchanged`.
- After `compact_lifecycle` reclaims `result/{id}` records, the engine's forward chain returns `HistoryNotQualified` (changes/chain.rs:60-66) and serves the exact `full` path (ComparisonPath::Full, retention.rs:247-253).
- Python discards that exact change stream and re-reads the whole new version as Python dicts (`table_records(read_arrow(new_pin))`, :336). That costs O(S) Python per table per update after each lifecycle compaction, which runs every `lifecycle_compact_interval` commits.
- **Easy way:** treat `full` like `forward_changes` (filter `side == 'after'`) and delete the added-objects and full-read fallbacks (:321-336). WS8 fix 1, which stops the automatic lifecycle compaction, lowers the frequency but leaves the waste. Reasoned, not measured.

**Fine as is:**
- `_maybe_compact_table` is an in-memory O(files in pin) check per commit, with no I/O.
- `content_digest` (a JSON SHA-256 over records) costs an extra serialization next to the IPC BLAKE3, but it buys replay-stable operation ids across pyarrow versions. Keep it.
- Bridge lookups are batched `read_keys` calls, one per table per delta, so there is no N+1 pattern.

## Ranked by cost at today's scale (1.68M filename rows, 3.9M capture rows, ~1.27M state rows)
1. **Engine input double handling.** Remote: P up plus P down per Build, about 350 + 350 MB per full raw rebuild (reasoned). Local: a copy plus fsync instead of a hard link. The plan's WS1 would delete the generic local read that avoids the download.
2. **Python merge on the raw state path, plus the engine merge on top.** O(L × leaf) Python dicts per run and about 9 s / ≥0.6 GB per full state pass, with 4 `to_pylist` calls of the same partition, one of them used only for `nbytes` (measured).
3. **`blake3` undeclared.** 1000x slower IPC hashing and a subprocess per producer file in locked environments (measured throughput).
4. **news views discard `full` changes** and re-read datasets as dicts after each lifecycle compaction: O(S) per update (reasoned).
5. **news `_dedup_incoming`:** O(n·d) (measured).
6. **Pin pre-GET:** 2 requests and 2 release lookups per first read of each pin, so L extra per run (reasoned).
7. **Leave alone:**
   - client Parquet staging (about 2 µs per row; IPC would move 3.9x more bytes);
   - ArrowResponse;
   - the 5 header-check copies (code only);
   - the 3 staging clones (no runtime cost on the success path).

## Changes to the plan
- **WS1:** remove `write/build.rs:356-372` from the dataset-name-predicate deletion list. It is a generic verified local read. Make it the single, unconditional path and test it, rather than deleting it.
- **WS3, or a new WS7-adjacent item:** move raw state merges onto the engine's `merge`, then delete `specs.py:476-692`. Declare `blake3` and delete transport.py:17-125.
- **WS8:** accept `path == 'full'` in views and delete incremental.py:321-336. Fix `_dedup_incoming`.
- **WS9 (optional):** hard-link verified local producer inputs instead of `copy_verified`. Consider `concurrent(>1)` for large uploads.
