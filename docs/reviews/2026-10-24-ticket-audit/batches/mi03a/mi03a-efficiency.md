# mi03a: efficiency audit (read-only), fourth pass

Scope: the surviving paths in my batch's area. These are the docspec_client custody transport (ct-3faj, ct-egpe, ct-copj, ct-bt1q), the raw_storage state and body index write/read path it serves (ct-eipa, ct-dmca), the news_lake DocSpec backend (ct-5fkx, ct-8ax6, ct-4nyy, ct-f11a, ct-gf8i), and the engine pieces those tickets touched (writer, export, key pruning, occurrence planning).

Code was read in `/Users/mikewolfd/Work/congressional-tech` at `c858a5a2`. For `raw_storage.py` I read the `origin/main` version (`54a68ac7`; it differs only by 13 lines for `stored_sha256`) via `git show`; line numbers below are from that version. Engine code was read in `/Users/mikewolfd/Work/spicy-stack/docspec-rs` (`d9c6719`). The plan was read at `/Users/mikewolfd/Work/wt/ct-ticket-audit/docs/plans/simplification-plan-20261024.md`, read-only.

Variables: S state rows = 1,298,420 (row count of `output/incremental-updates-20261019/adoption-inputs/state.parquet`). Captures N = 3,909,134. Distinct bodies B = 1,036,256 (`pc.count_distinct` on the pinned captures `body_key`/`sha256`). Body-index keys = 2B = 2,072,512 (`body:` plus `sha:`). R receipts = 2,289. C = URLs changed per run. L = leaves per trie. Leaf cap = 16,384 rows (`max_state_rows`).

Measurement scripts are in this directory, all run with the project venv and no network:

| script | what it measures |
|---|---|
| `mi03a-measure_raw_leaves.py` | Leaf reads and writes per `prepare`, using the project's own `MemoryNative`/`SelectorStore` doubles |
| `mi03a-measure_leaf_python_cost.py` | Per-leaf Python conversion cost on the real schemas |
| `mi03a-measure_arrow_response.py` | `ArrowResponse` throughput |
| `mi03a-measure_state_leaf_files.py` | Data files per state leaf through the real engine. **Could not run**: `docspec-rs/target/` no longer exists, and building a binary is outside my rules. The engine-side counts below are therefore reasoned, not measured. |

---

## F1. The raw state and body indexes are rewritten almost entirely on every run: O(S + B) per run, not O(C)

**Path.** `RawStorage.prepare` (`raw_storage.py:1083-1255`), `_prepare_bodies` (`:942-994`), `_candidate` (`:1055-1072`), and `split_partition`/`RoutingPages` (`partition_routing.py:28-70,105-114`).

**Mechanism.**
- State and body rows are routed by `key_hash(key)`, a SHA-256 prefix trie (`partition_routing.py:43`). This spreads every run's changes uniformly over all leaves.
- Every touched leaf is read in full (`_read_states`/`_read_bodies`), merged in Python, and rebuilt in full as a brand-new native dataset: `'raw-' + kind + '-' + sha256(operation, kind, prefix, base_id)` at `:1059-1060`, built with `run_table`. That is an immutable Build of the whole leaf.
- At today's size both tries are 256 leaves. State leaves average 1,298,420/256 ≈ 5,072 rows and body leaves 2,072,512/256 ≈ 8,096 rows, both under the 16,384 cap at depth 2.
- The expected share of leaves a run touches is 1 − e^(−C/256): 32% at C=100, 86% at C=500, and over 99% at C ≥ 1,200.

**Measured (in-memory doubles, real `RawStorage` code, 256-row leaves, C=100 fixed):**

| S seeded | leaf reads | leaf writes | rows written | rows written per change |
|---:|---:|---:|---:|---:|
| 8,000 | 161 | 162 | 5,287 | 52.9 |
| 16,000 | 161 | 162 | 10,347 | 103.5 |
| 32,000 | 161 | 162 | 20,325 | 203.2 |

Rows written grow linearly with S at constant C. That is history-proportional work.

**At today's scale (reasoned from the measured model):** a run with C in the low thousands reads and rewrites about 1.30M state rows plus 2.07M body rows. It creates about 512 new native datasets per run, which accumulate with history H. Each one is an Iceberg table create plus per-phase commits on R2 (decision 1).

**Python cost alone (measured per leaf, × 256 leaves of each kind):** about **68 s per run**. Per state leaf: two Arrow↔Python round trips (22 ms each), two `to_pylist` calls (46 ms each), key re-hashing (2 ms), and `summarize` (115 ms). Body leaves are about 10 ms each. The native Build cost per leaf comes on top and is **reasoned, not measured**.

**Easy way (decision 6).** Use one native dataset per kind with the engine's keyed `UpdateMergeSpec`.
- `STATE_MERGE_SPEC` already exists at `raw_storage.py:381`, and the engine already has bucket partitioning, `BTreeSet` key pruning (`rs:src/engine/key_pruning.rs:277-330,626-690`) and tail coalescing.
- New URLs become appended files, and changed URLs rewrite only the files that hold them: O(C + touched files) per run, with no per-leaf datasets and no Python round trips.
- Captures are already append-only (`capture_pages.append`, `:1129-1136`), O(C) per run. Leave them alone.

**Why ct-eipa's decision doesn't hold.** It compared Build against Update for one 8,192-row leaf (0.538 s against 0.834 s). It never measured how many leaves a run touches. Under uniform hash routing that is all of them, so the comparison that matters is "256 leaf Builds" against "one keyed Update of C rows".

## F2. The same rows are converted, hashed and size-checked repeatedly on each leaf rewrite

All on the same path, per touched leaf:
- **Read side.** `_read_table` streams batches from the engine, then does `pa.Table.from_pylist(table.to_pylist())` (`:922`) solely to normalize null bitmaps so that `table.nbytes == decoded_bytes` holds (`:923`). The caller then calls `prior.to_pylist()` again (`:975`, `:1150`).
- **Write side.** `decoded_bytes` is computed with the same round trip: `pa.Table.from_pylist(part.to_pylist()).nbytes` at `:989` (bodies), `:1133` (captures), and `:1236`, `:1250` (state). `summarize(part.to_pylist())` makes another full pass at `:1237`, `:1251`.
- **Key hashing.** `split_partition` turns every key back into Python and SHA-256-hashes it on every rewrite to re-check the prefix (`partition_routing.py:40-45`). These are the same keys, hashed in every earlier run.
- **The repeat buys nothing real.** `decoded_bytes` is computed by the same normalization on both sides, so the equality check can only confirm itself; it is a self-referential check. Content identity is already guaranteed by the engine-verified pin (`pin['verified']`, its manifest digest and row count, checked at `:891-893`).
- **Easy way.** Keep the row-count and pin checks and delete the `decoded_bytes` normalization. Store the key hash and ordinal as columns once at ingest; `state_key_sha256` is already declared at `:367` but never stored. All of this disappears with F1's engine move.

## F3. The bucket partition spec on state leaves silently does nothing

- `_candidate('state', …, partition_by=STATE_PARTITION_SPEC)` (`raw_storage.py:1247`) partitions on `state_key_sha256`.
- The state table's columns are `_state_order`, `_state_key` plus `STATE_SCHEMA` (printed: there is no `state_key_sha256`). `run_table` drops partition fields that aren't columns (`packages/docspec_client/src/docspec_client/client.py:460-464`), so the spec is silently removed.
- `_candidate` also retries without `partition_by` on `TypeError` (`:1062-1070`).
- The result is dead configuration that looks like bucketing; it is a success-shaped no-op. Either add the column (as part of F1) or delete the spec and the fallback.

## F4. Each producer file is written once and read in full two or three times

- `run_table` writes Parquet (`transport.py:142-185`).
- `hash_input` then calls `Path.read_bytes()` on the whole file and runs blake3 (`client.py:403-412`). That puts the whole file in memory.
- The engine re-reads and re-hashes the file to verify `expected_digest`, then decodes it.
- The engine's verification is a real trust boundary and should stay. The Python pre-read is not needed: the digest could be computed while writing (a hashing sink wrapped in `pa.PythonFile`) or streamed (`blake3.update_mmap`).
- Cost: about 512 leaf files per run (F1) at a few MB each, roughly 2–4 GB of extra local reads per run. **Reasoned, not measured.** Fold this into WS3's single submission owner.

## F5. The production-only `iter_states_for` branch reads the whole state index for any request over 512 URLs

- `raw_storage.py:655-700`: when more than 512 URLs are requested, it reads `output/.../state.parquet` if present. Otherwise it reads every state leaf with a 4-thread pool (`leaf_items`, `:675-689`). That is O(S) for 513 URLs.
- The pytest path reads only the routed leaves through SQLite (`:690+`).
- This confirms WS1's deletion. The surviving path is the cheaper one.

## F6. The orphan-receipt sweep lists every receipt on every run

- `raw_archive.py:672-678` lists `receipts/` and does a delivery-route lookup per key on every run. That is O(R) LIST requests plus O(R) lookups, and R grows with history.
- Page reads are cheap in production: pages are content-addressed and cached by sha256 (`partition_routing.py:78-103`). The pytest path skips that cache and re-reads and re-validates every page.
- It is fine at R = 2,289. The easy way, once it matters, is a `StartAfter` listing from the last checked key, or trusting the delivery routes alone.
- Minor: `_delivery` hashes the key, and `lookup` hashes it again (`raw_storage.py:1023-1025`, `partition_routing.py:106`).

## F7. news_lake DocSpec backend (low priority: unused)

- **Per poll, each record is serialized three times and hashed twice.** `content_digest` (canonical JSON plus sha256) forms the operation id (`docspec/lake.py:373,401-403`), then `records_to_arrow`, then producer Parquet or IPC plus blake3. The producer blake3 digest could serve as the operation id.
- **Each poll issues a 0-row relationship Update for every untouched table** (`lake.py:353-367`), up to 16 engine operations and snapshots per poll. An engine seal that carries unchanged members forward would make this once per batch. That would be a generic WS9 ticket.
- **Views return full in-memory lists**, O(view rows) per refresh (`docspec/views.py:447,453,531`).
- **Each export hashes both the destination and the source file in full**, even when they are hard links to the same inode (`docspec/export.py:193`).

## Checked and cleared

- **`ArrowResponse` copies.** On a 95.3 MiB Arrow stream in 64 KiB chunks it took 0.019 s, identical to reading the same bytes from an in-memory buffer. The extra Python copies are negligible.
- **Engine key pruning** uses `BTreeSet` range queries, O(F log C) (`rs:src/engine/key_pruning.rs:327,661-686`). Sound.
- **Binary verification** caches its sha256 keyed by (path, inode, mtime, size) (`client.py:213-224`), so it is computed once per binary.
- **Routing pages** are cached by content sha256 in production, so each is read once per process.

## Changes to the plan

1. **The WS7 keep list says to keep `partition_routing.py` and the raw-side routing pages because they "are raw provenance". Revise that.** The receipts are the provenance. The state and body tries are a derived index, and their layout makes every daily run O(S + B) (F1). Under decision 6, once Step 0 Run A shows that the index is reproducible from receipts, move the raw state and body indexes onto engine datasets updated with `UpdateMergeSpec`. Keep capture pages, which are already O(C).
2. **Step 0 should record leaf fan-out.** Log leaves touched and rows rewritten per run in B1 and in a real daily run. The plan's Q6 suspects the one-dataset-per-leaf layout. This audit predicts all 512 leaves are touched once C ≥ ~1,200.
3. **WS2/WS3:** delete the `decoded_bytes` normalization round trips (F2), the dead `STATE_PARTITION_SPEC` and its `TypeError` fallback (F3), and add hash-while-writing in the single submission owner (F4).
4. **Withdraw ct-eipa's decision ("retain Build for leaves") as evidence.** It measured the wrong variable.
