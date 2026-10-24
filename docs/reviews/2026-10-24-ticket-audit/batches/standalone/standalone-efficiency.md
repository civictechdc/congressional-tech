# Standalone batch: efficiency audit (4th pass, read-only)

## Scope and method

- **Code:** congressional-tech main c858a5a2. My audit files match origin/main; 54a68ac7 changes none of them.
- **Engine:** docspec-rs HEAD.
- **Area:** paths from this batch that the simplification plan keeps:
  - the recovery raw import (`corpus_recovery/transfer`), plus the r2.py and raw_storage code it calls;
  - the docspec_client transport (ct-nmjc);
  - the news_lake DocSpec backend (ct-xu1o, ct-r60e, ct-pgxn);
  - engine key pruning (ct-tuez).
- **Plan-deleted code:** one line each, at the end.

**Variables used in the Big-O estimates:**

| Symbol | Meaning |
|---|---|
| N | capture rows (3.9M) |
| B | bodies in one recovery batch |
| R | receipt records (100 per object) |
| S | state rows |
| C | changed URLs per run |
| L | leaf size (`max_state_rows=16384`, `raw_storage.py:785`) |
| A | affected leaves per run, about min(C, S/L) |
| H | history (runs, polls) |
| F | files |
| P | pinned source files (230 under `congress_api/src`) |

**Measurements.** All run with the project venv, using scripts I wrote in this scratch dir:
- `standalone-measure_import.py` wraps the existing offline fixture in `packages/corpus_recovery/tests/test_import_corpus_recovery_batch.py` and counts store calls, hashes and gzip calls.
- `standalone-measure_leaf.py` times the per-leaf Python round trips on a synthetic 16,384-row leaf.

Anything else is marked *reasoned, not measured*.

## Findings, ranked by cost at today's scale

### E1. A raw state update rewrites whole 16k-row leaves as new datasets, with Python round trips around each one

**Location:** `raw_storage.py:1144-1250`.

**Big-O per run:**
- Read and decode O(A·L) rows: each affected leaf is read whole (`:1150`).
- Write O(A·L) rows: each leaf is rewritten in full as a **new** native dataset through `_candidate` → `run_table(operation='initial')` (`:1058-1074`, `:1232-1240`).
- The write is done this way even when one row changed, so write amplification is up to L = 16,384 per changed URL.
- Leaf count grows with S/L. The routing pages are cached (`partition_routing.py:73-104`).

**Repeated work per affected leaf:**

| Operation | Count | Where | Measured |
|---|---|---|---|
| `to_pylist` | about 4 | `prior.to_pylist()` `:1153`; `part.to_pylist()` twice `:1243-1244`; key column inside `split_partition` (`partition_routing.py:42`) | 82 ms each |
| `from_pylist` | 2 | `:1177`; again at `:1243` only to compute `decoded_bytes` | the `decoded_bytes` round trip costs 95 ms; `part.nbytes` costs 0 ms |
| `updates.to_pylist()` | 2 | `:1146` and `:1158` | – |
| sha256 of every key in the leaf | 1 | `partition_routing.py:43` | 5 ms per leaf |

The sha256 above hashes `'url:'+url` for Python prefix routing. Meanwhile each leaf dataset is also bucketed by the engine on a different hash, `bucket(state_key_sha256)` (`:373-379`). The same identity is hashed twice, for two partitioning systems stacked on each other.

**Easy way.** The engine primitive already sits in this function: the `schema_evolved` branch calls `update_table(delta, keys=[STATE_KEY_FIELD], merge=STATE_MERGE_SPEC)` with only the changed rows (`:1197-1221`). Two steps:
1. Make that delta Update the normal path.
2. Key it on the existing 64-hex `state_key_sha256`. ct-tuez made keys shorter than 128 bytes prunable; the URL key `'url:'+url` usually is not.

Engine bucket partitioning plus key pruning then replace the Python prefix routing and leaf splitting (`partition_routing.split_partition`, `RoutingPages` for state).

Cost becomes O(C) rows written, plus O(files whose bucket and key bounds match) probed. Use `part.nbytes` for `decoded_bytes`, after checking it matches the round-trip value on sliced tables; if not, `take` compacts in C++.

**Plan effect.** The plan lists `partition_routing` and `raw_state_routes` as surviving raw-path code. Under decision 6 they overlap engine partitioning, keyed Update with merge, and pruning. Raise this as an engine move, with Step 0 measuring it.

Open question: are the native raw datasets fully derivable from receipts? State carries attempts, `next_attempt_at` and outcomes for URLs never retained. If not, any re-layout must migrate them; it cannot rebuild them.

### E2. Captures: one new native dataset per batch, and an O(N) Python round trip just to measure size

**Location:** `raw_storage.py:1131-1140`.
- Each run's captures become `ceil(additions/L)` new datasets named `raw-captures-<identity>`, chained on capture pages. Dataset count grows with history (sum of batches over H runs), not with the current table.
- `decoded_bytes=pa.Table.from_pylist(batch.to_pylist(), …).nbytes` (`:1138`) converts every capture row to Python dicts and back, for a size number.
- Measured: 36 ms per 16,384-row batch, against 0 ms for `batch.nbytes`. That is about 8.5 s per full 3.9M-row adoption, and O(new captures) per run.

**Easy way:** use `batch.nbytes`.

**Engine-first:** append to one engine dataset per kind, and have `indexes/raw.json` select an engine release pin rather than a list of datasets. The comment at `:1059-1062` gives the reason for a dataset per batch: an unselected Update must not advance the selected base. Engine release pins already decouple "latest" from "selected", so this needs a short design check, not new machinery.

### E3. Plan risk: WS8's revert of ct-xu1o to `['id']` keys brings back a per-poll cost that grows with history

- With uuid5 ids, every file's id range covers the whole key space. An `['id']` probe therefore decodes the id pages of every file, which is O(total rows), not O(poll).
- Receipts: id-keyed p50 rose from 561 to 1,088 ms between 120k and 2.16M rows, while time-keyed stayed between 537 and 603 ms (`output/news-poll-scale-20261021/summary.md:23,29`).
- Compaction cut the file count from 1,079 to 49 (`:65`). It does not shrink the rows whose id pages must be decoded (*reasoned, not measured*).

**Also repeated today:**
- The append path probes the same keys twice: once in Python through `read_keys` on the time values (`lake.py:319-322`), then again inside the engine's Update (`lake.py:400-408`).
- `_known_upsert_records` grows with every distinct id a process sees (`lake.py:425-447`).

**Easy way, cheapest first:**
1. Derive the time column from input, as the ticket's design required. Then the same id always carries the same time, the time-key probe is complete, and the cost stays O(poll). This fixes the duplicate-id bug without the revert.
2. Or keep `['id']` and add Parquet bloom filters on `id`. parquet-rs supports them; docspec-rs has none (`grep -rn bloom src` returns nothing). That means reopening ss-wie5; WS9 currently says to keep its decision.
3. Either way, a generic engine append mode ("insert if absent, skip if identical, refuse if different") would remove the Python pre-read.

**Plan effect:** WS8 fix 2 should measure first and prefer option 1 over a blind revert.

### E4. Recovery import: each body is read, hashed and fetched more than once

**Location:** `transfer.py:26-46,107-136`; `r2.py:111-129`.

**Measured on the fixture** (2 bodies, 1 receipt object):
- 2 store reads per body; the test pins this at `test_import_corpus_recovery_batch.py:106`, "Presence check and full readback".
- 1 read per receipt object.
- 8 metadata writes, followed by 13 metadata reads.
- 16 sha256 calls in `transfer.py`.
- 2 `file_digest` calls, 1 `gzip.compress`, 2 `gzip.decompress`.

**Per new body:**

| Operation | Count | Where |
|---|---|---|
| Local read | 2 | `:111-113` and `:116` |
| sha256 of raw bytes | 2 | `:113` and `:117` |
| sha256 of the gzip payload | 2 | intent `:29`, then `stored_sha256` from the readback, which is the same bytes (`:136`) |
| MD5 | 2 | `put_parameters` `r2.py:112`, `verify_upload` `:128` |
| Presence check | 1 GET | `:129`; a HEAD would do |
| PUT | 1 | – |
| Full readback | 1 GET | `:43-45` |
| Decompress of bytes just compressed | 1 | `:134` |

The readback buys nothing over the server check: the PUT already carries Content-MD5, so R2 rejects a corrupted transfer, and the ETag is then compared with MD5 (`verify_upload`). Metadata writes through `GuardedStore` repeat the same readback.

**Easy way:**
- Presence: HEAD (`inventory.head_body` already exists).
- Create-only PUT with Content-MD5, plus `ChecksumSHA256`, so R2 verifies the bytes and stores the sha256. *Confirm R2's checksum support in its docs; not testable offline.*
- Trust the ETag/MD5 match instead of a readback.
- Hash the payload once and reuse it as `stored_sha256`.
- On a 412, use WS2's single verifier: HEAD for size plus checksum, and GET only when no checksum is stored.

Saving: one full GET, one decompress and two hashes per body, and one GET per receipt object. At today's 2,289 receipt objects the receipt saving is small; the body saving scales with batch bytes.

**Plan effect:** fits WS2 step 2 and WS3. The test assertion at `:106` must change on purpose.

### E5. docspec_client transport reads and hashes every producer file twice

- Each `run_table`/`update_table` encodes Parquet, then `hash_input` reads the **whole file into memory** and hashes it with blake3 (`client.py:403-412`). The engine then reads the file and hashes it again to check `expected_digest`.
- Cost: 2 reads and 2 hashes per file, with memory O(file). Files reach 32 MiB in the no-row-group mode (`transport.py:152-155`).
- Easy way: stream the hash, or have the engine return the digest it computed and record that.
- Low cost, since blake3 runs at GB/s (*reasoned, not measured*).
- The retry that rewrites the file with the legacy layout on `operation_conflict` (`client.py:522-533`) re-encodes and re-hashes the whole table. WS3 already deletes it.

### E6. RecoveryGuard runs per-write checks that could run once per phase

- Every raw write calls `check()`. That stats all P = 230 pinned files plus the batch inputs, and runs `getppid`, `disk_usage` and lock stats (`guards.py:106-113,131-136`).
- Cost: O(W·P) stats. Each is microseconds, so roughly 1 s per 2,000 writes (*reasoned, not measured*).
- The cloud check calls `gh api` (5 statuses, up to 10 pages each) every 30 s (`guards.py:116-124`).
- Easy way: a git tree hash plus a clean-tree check at the start (WS4), then a cheap identity check only at phase boundaries.

### E7. Route splits re-hash every key once per child

- `raw_storage.py:1037` and `raw_readings.py:147` filter the whole dict once for each of the 16 children, calling `key_hash` per key each time. That is O(16·E·d) sha256 per overflowing leaf, where E is the leaf's entries and d the split depth.
- `encoded(...)` also re-serializes the entries at each level (`raw_readings.py:139`).
- Bounded by leaf size and occasional, so low cost.
- Easy way: hash once, then bucket by the next hex character. It disappears with E1 if routing goes.

## Plan-deleted code (one line each)

- **`export_viewer_pins`** has a native-export path and a Python materialization path (`filename_exports.py:763-819` vs `:821+`), which is already in WS6. Keep only `native.export`.
- **Publication journal (WS6):** the full state is rewritten per event (O(H²)), and the writes dict is copied per event (`continuation.py:224-230,451`; `local.py:28`). These confirm the deletion.

## Findings that change the plan

1. **E1/E2.** The raw indexes (`partition_routing`, state and capture leaf datasets, `raw_state_routes`) duplicate engine partitioning, keyed Update with merge, key pruning and release pins. Under decision 6 they should not count as "surviving". The first step uses existing code: make the delta `update_table` path the normal state path, keyed on `state_key_sha256`.
2. **E3.** WS8's revert to `['id']` keys needs the compaction-on measurement before anything else. Prefer an input-derived time key. If `['id']` stays, reconsider WS9's "keep ss-wie5's decision".
3. **E4.** WS2 step 2 should also remove the readback in `checked_put`, and use R2 checksums or the ETag rather than a GET.
