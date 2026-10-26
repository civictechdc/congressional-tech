# Validation of review 8 engine findings: D1, D2, D6, D7, D8, D9, D11

Spec: `docs/engine-first-data-model.md` (DM) and `docs/engine-first-architecture.md` (ARCH) at 33c2cba0, worktree `/Users/mikewolfd/Work/wt/ct-ticket-audit`.
Engine: `/Users/mikewolfd/Work/spicy-stack/docspec-rs` at d9c6719 (clean). It pins DataFusion =53.1.0, iceberg =0.10.1 and parquet 58 (58.4.0 in the lock). Dependency sources were read from `~/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/`.
Method: I read the code and ran one heap model (`v8e_cc_mem.py`). Nothing was built or executed against the engine, and nothing live was touched.

## Verdict table

| ID | Verdict | Evidence (read by me) | Fix judgment |
|---|---|---|---|
| D1 | **Confirmed** | No JSON or URL function exists in the `datafusion-functions*`-53.1.0 crates. `datafusion-functions-json` and `datafusion-spark` are absent from `Cargo.lock`. docspec-rs registers no scalar UDF, only two UDAFs (`aggregation/udaf.rs:78,268`). ARCH §13 item 8 lists only the URL functions. CC: `connected_components.rs:93-123` (pinned release only), `:133-157` (Utf8 only), `:27-36` plus `topology.rs:259` (engine computes `document_id`). | **Right, with sharper specifics.** Add one generic variadic `json_array(...)`/`to_json` UDF over arrow-json 58.4's public `make_encoder`, which encodes strings with serde_json and so matches DM §3. Change CC to take an in-job relation and return a deterministic component label, with no ID. |
| D2 | **Confirmed** (thread dependence inferred) | `export/pipeline.rs:545-626`: no re-batch, and it flushes on `memory_size() >= max_batch_bytes` or `in_progress_size() >= max_row_group_bytes` (`:609-613`). `query.rs:791-829` splits by memory size. `pipeline.rs:676-698`: global dictionary, 1 MiB pages (16 KiB on page-index columns), write batch 256, no page row limit, no per-column encoding. No ticket tracks this. | **Stopgap only.** The right fix is engine work against ARCH §10.2, gated by §15.4. Pinning `compute_threads` in the profile conflicts with runner classes. |
| D6 | **Confirmed in substance; one number wrong** | `storage.rs:376-391,439-453`: the Basin (`s3://`) path caps row groups at **2,048** rows (not 8,192), row groups and files at 2 MiB, and hard-codes ZSTD-3. iceberg-0.10.1 `spec/table_properties.rs` has no `write.parquet.compression-*` and no delete-after-commit (only `previous-versions-max`, a log trim). | **Right.** Also state that the engine already writes ZSTD-3. Drop `delete-after-commit`, which a REST catalog's server would act on: unverified for Basin. Drop the §6.1 sort clause. |
| D7 | **Confirmed** (textual) | DM §8.1 inputs row: identity, snapshot IDs, provenance set, run. DM §8.3: receipt keys appear only inside the digest. ARCH §8.6: snapshots expire after 30 days, keeping 5. | **Right.** Store the key list as a content-addressed object, not inline. Also fix ARCH §10.3.7's "always rebuilt" for spicy-pinned releases. |
| D8 | **Confirmed** | `storage.rs:858-920` and `catalog.rs:1148-1153` use `fast_append().with_check_duplicate(false)` (that flag is about files, not keys). No key check exists. DM invariant 1 says "MUST satisfy, SHOULD test", but neither the §7.1 publish gate nor the engine checks it. | **Right.** One `GROUP BY pk HAVING count(*) > 1` per table at the pin is O(n). |
| D9 | **Confirmed** (textual) | DM §6.2 L276: an operational failure writes no row. §7.1 L416: publish refuses on a non-empty work list. ARCH §12: budgets also refuse. | **Direction right, mechanism wrong.** An automatic registry edit after three runs is not a reviewed registry. Use a deterministic pre-read size bound (`size_limit`) and a provenance `unreadable` decision. |
| D11 | **Confirmed in substance; wording imprecise** | `topology.rs:31-56`: the DSU is dense `usize` over input rows. The memory goes to `HashMap<String,usize>` and `HashMap<(String,String),usize>`, per-row `String` copies, and `HashMap<(String,i64),String>` (`:81-89, :120-276`). No node-count refusal exists. The budget reserves about 1/3 of the real heap. | The reviewer offered no fix. **Fix:** an engine ticket to intern keys and tokens to u32/u64 IDs, drop the per-row path and doc-ID maps, add the §13.4 node cap, and count true heap. |

## Details

### D1: JSON encoder, URL functions, ConnectedComponents

**DataFusion 53.1**
- The function crates hold `core crypto datetime encoding math regex string unicode` and the nested array functions.
- A search for `json`, `url` and `percent` found only doc-logo URLs and percentile code. There is no `to_json`, no escaper, and no URL parse, resolve or normalize function.
- Strings can be hashed (`sha256`) and hex-encoded (`encode(...,'hex')`), and arrow-cast 58.4 casts Binary to FixedSizeBinary (`cast/mod.rs:241`).
- A pure-SQL escaper is possible: 34 nested `replace()` calls, for `\`, `"` and the 32 control characters. That is hand-rolled policy, so I reject it.

**docspec-rs**
- It defines no ScalarUDF.
- The reviewer's `window.rs:129` citation is an `ExecutionPlan::name`, not a window UDF. The conclusion is unaffected.
- `url` 2.5.8 and `percent-encoding` 2.3.2 are in the lock transitively. `url` implements the WHATWG URL standard, not RFC 3986.
- **Open choice for the lead:** browsers resolve `href`s by WHATWG. Specifying WHATWG resolution in DM §7.2 would make the already-locked crate correct and cheaper than adding an RFC 3986 crate. Either way, DM must name one.

**ARCH §13**
- Item 8 lists only reference resolution and percent-encoding normalization. The JSON encoder is absent, as the reviewer says.
- Nothing in either repo's tickets tracks items 3, 4 or 8, or a JSON encoder.

**ConnectedComponents**
- Input is restricted: `register_input` reads only `releases.get(&spec.input.dataset)`. `qualify` refuses a non-Utf8 `row_key` and edges that are not Utf8 or List<Utf8>.
- The engine computes `document_id` itself: `compute_document_id` serializes `("bodies", list)` or `("sources", list)` through serde_json, called at `topology.rs:259`.
- The format agrees with DM §7.5, but it is an ID formula inside the engine, which ARCH §13 bans.
- It also has a third fallback: SHA-256 over `"<data-file path>:<row>"` (`topology.rs:252-256`). That puts a run-specific value into an ID, which breaks ARCH §10.2.
- It computes the ID at CC time. DM §7.5 computes it after recovery attachment and review merges (order of evaluation, steps 4–5), so the engine's ID would be computed at the wrong step even when the formula matches.

**Cheapest correct primitive**
- A generic `json_array(v1, …, vn)` scalar UDF in docspec-rs that encodes each argument with `arrow_json::writer::make_encoder` (public, `writer/mod.rs:115`) and joins them in `[ , ]`.
- arrow-json encodes strings with `serde_json::Serializer::serialize_str` (`encoder.rs:460-463`), the escaping the reviewer and DM §3 rely on. Lists come out as `[..]` and nulls as `null`.
- Binary is lowercase hex (`encoder.rs:465-470`), which covers `["sources", source_id hex…]` directly.
- About 60 lines, with golden vectors against Python `json.dumps`.

**CC changes**
- Accept a materialized job relation.
- Emit a deterministic label: the smallest member key, not a row index.
- Delete the ID formula from the engine path.
- The model then computes `document_id` in SQL with `sha256(json_array('bodies', array_sort(array_agg(DISTINCT k))))`.
- Utf8 keys are acceptable, since `encode(fsb,'hex')` is cheap.

**Could not see:** whether DataFusion upstream (after 53.1) or `datafusion-spark` has these functions. Neither is in the lock.

### D2: Export determinism

**Code**
- The export streams batches from `crate::query::bounded`. That function splits any batch whose `get_array_memory_size` exceeds `max_batch_bytes` (`query.rs:811-818`). Memory size includes buffer capacity, not just rows.
- Each slice is written with `writer.write(&sub_batch)`, cut only at the row-group remainder (`pipeline.rs:587-596`).
- parquet-rs cuts each `write()` into `write_batch_size` mini-batches from the start of that call. It checks page size and dictionary fallback after each mini-batch. So page boundaries follow the upstream batch boundaries, which follow `batch_rows` (`SessionConfig::with_batch_size`, `budget.rs:116-118`) and `max_batch_bytes`.
- Row-group flushes are also triggered by bytes (`pipeline.rs:609-613`).
- Thread count: `with_target_partitions(compute_threads)` changes the plan shape (per-partition sort plus SortPreservingMerge). That probably still emits `batch_size` batches, so thread dependence is plausible but not shown.

**Spec gap**
- DM §8.1 requires: dictionary only on `dict` columns, `DELTA_BYTE_ARRAY` on `filename`, 64 KB pages with a 1,024-row page limit and 1,024-row write batches (ranged), 16 KB pages (lookup), flushes on row count only, and a pinned `created_by`.
- The engine sets: global dictionary, 1 MiB pages, 16 KiB only on page-index columns, write batch 256 when indexed, no page row limit, no per-column encoding, and no `created_by` (only `http/ipc.rs:507` sets one).
- ARCH §10.2 already states the re-batch and row-count-flush rule as an engine duty, and §15.4 the test. No ticket in either repo tracks the gap.

**Fix judgment**
- The reviewer's §7.1 edit (pin the limits) is acceptable only as a stopgap. It makes `compute_threads` part of the profile, which ties a release to a runner class. The `memory_size` flush stays fragile even with pinned limits.
- **Better:**
  - File an engine ticket: re-batch to the pinned write batch, and flush on row count only, using byte limits only to refuse.
  - Add per-file and per-column writer properties from the export spec.
  - Keep DM §8.1 unchanged.
  - Make ARCH §15.4 the gate.

**Could not see:** actual byte drift. Not executed.

### D6: Lake writer settings

- **Remote write path:**
  - `is_remote = location starts_with("s3://")` gives `target_file_bytes ≤ 2 MiB`, `batch_rows.clamp(1, 2048)` and `max_row_group_bytes ≤ 2 MiB` (`storage.rs:376-391`).
  - The writer sets ZSTD level 3, dictionary on, 1 MiB pages, chunk statistics and no offset index (`:439-453`).
  - The reviewer's "8,192" is the local default (`budget.rs:44`). Basin row groups are at most 2,048 rows, which makes the finding stronger.
  - The code comment at `:433` says "`set_max_row_group_bytes` stays unset", but `:443` sets it. The comment is stale.
- **Compression property:** iceberg-0.10.1 `spec/table_properties.rs` knows only metadata compression (`:43-92`), not `write.parquet.compression-*`. The reviewer is right that the property is ignored. But the engine writes ZSTD-3 anyway, so DM's intended effect holds and the property is dead text.
- **Metadata deletion:** iceberg-rust has only `write.metadata.previous-versions-max`, which trims the metadata log (`table_metadata_builder.rs:1174`). With a REST catalog, the server writes metadata files, so whether `delete-after-commit` does anything is Basin's behavior. **Unverifiable here.** The reviewer's "client acts on it" framing is off for REST, but the conclusion (the doc cannot promise it) holds.
- **Sort clause:** the engine writes batches in arrival order, so an ORDER BY in the producer would order rows within a commit. "Unenforced" is too strong. But ARCH §8.1 says nothing depends on physical order and compaction (128 MB) rewrites files, so the clause is useless. Drop it.
- **Fix:** take the reviewer's rewrite, and add "the engine writes ZSTD-3 Parquet; Basin compaction sets the final layout". Drop `write.parquet.compression-*` and `delete-after-commit`. Keep `gc.enabled`. Drop the §6.1 L263 sort clause.

### D7: Reproducing a kept release

- DM §8.1 lists `inputs/<input_digest>.json` as: input identity, pinned snapshot IDs, provenance set, run. DM §8.3 hashes the sorted receipt keys into the identity, so the keys exist only as a digest.
- ARCH §8.6: snapshots older than 30 days expire, keeping the last 5.
- A rerun after expiry can read the current lake. Captures are append-only and rebuild-reproducible (ARCH §8.2), and readings are keyed by body and version. But the rerun cannot know which receipts to include, so it cannot reproduce the release.
- **Fix (reviewer's, endorsed):**
  - Store the sorted receipt-key list.
  - Specify that a rebuild filters `captures` to that list instead of reading at a snapshot.
- **Refinement:**
  - Write the list once as `inputs/receipts/<sha256>.json.gz`. Its SHA-256 is already an input to the identity, so it is self-verifying. This keeps the inputs record about 2 KB.
- **Additional gap:** ARCH §10.3.7 keeps releases named by spicy-regs' pin list. DM §6 drops a lake table version once neither the live nor the last-good profile names it. A spicy-pinned release can therefore lose its table version, so "a kept release can always be rebuilt" is false for those too.

**Could not see:** the full receipt count. The local cache holds 2,289 files, so I made no size measurement.

### D8: PK uniqueness

- Every engine append path is `fast_append().with_check_duplicate(false)`:
  - `storage.rs:870-872` and `:905-907`;
  - `catalog.rs:1148-1153`, which also expires snapshots.
- Identifier fields are only carried into schemas (`storage/identity.rs:91-124`).
- The engine's key dedupe lives only in the merge path (`write/merge.rs:197-200`), which this system does not use.
- DM invariant 1 states uniqueness, but it is a SHOULD-test with no gate.
- The ARCH §8.1 conflict retry prevents duplicates only if implemented correctly, so an uncaught producer bug becomes silent link and count inflation.
- **Fix (reviewer's) is right.** Add PK uniqueness to the §7.1 publish refusal: a hash aggregate per table, O(n), seconds at 3.9M rows.

### D9: An input that always fails

- Confirmed from DM §6.2 L276, §7.1 L416 and ARCH §12 (budgets).
- Two cases block forever:
  - a body that deterministically crashes or exhausts memory in a parser;
  - a body object that is missing, which is an invariant-2 violation.
- **Reviewer's fix:** an automatic `unreadable` registry after three runs.
  - That needs cross-run counter state.
  - It silently drops documents.
  - It makes a registry, which DM §7.1 defines as a reviewed file versioned by the profile, depend on run history.
- **Better:**
  1. Make resource exhaustion deterministic: each parser version declares a byte bound checked against `stored_bytes` before reading, giving a `size_limit` row.
  2. The publish refusal names the stuck inputs.
  3. A person records a provenance `unreadable` decision (body, parser version), and the work list anti-joins it.

### D11: ConnectedComponents memory

- **Structures** (`topology.rs:31-56, 81-89, 120-276`):
  - `DisjointSet { parent: Vec<usize>, rank: Vec<u8> }` over **input rows**: dense, 9 B per row.
  - Around it:
    - `key_owner: HashMap<String, usize>`;
    - `token_owner: HashMap<(String,String), usize>`;
    - per row: owned `row_key`, `occ_file` (the data-file path), `Vec<(ns,String)>` tokens and a body-token `Vec<String>`;
    - at the end: `BTreeMap<String, Vec<usize>>` components and `occurrence_to_doc: HashMap<(String,i64), String>` (path plus 64-char doc ID per row).
  - "String-keyed union-find" is imprecise: the union-find is integer, and the lookups and copies are string-keyed.
- **Estimate** (`v8e_cc_mem.py`; hashbrown 7/8 load, 24 B headers, 16 B rounding, 64 B hex keys, 130 B paths):

  | Workload | Per row | Total heap | Budget reserves |
  |---|---|---|---|
  | 1.68M rows, 2.3M token occurrences, 1.0M distinct tokens | about 712 B | **1.65 GiB** | 0.54 GiB |
  | 4M rows, 2M tokens | about 712 B | **3.3 GiB** | 1.0 GiB |

  - ARCH §13.4 says 32 MB (4M × 8 B).
  - The reviewer's 1–2 GB is right for today's shape and low at 4M rows.
  - The reservation (`retained_bytes`: key + path + 32 per row, ns + value + 16 per token) under-reserves about 3×, so the memory pool does not protect the runner.
  - No node-count refusal exists.
  - `incremental.rs` builds both an old and a new topology (`:135`), which doubles the peak on incremental runs.
- **Fix:** file an engine ticket, shared with D1's CC changes:
  - intern keys and tokens to dense integer IDs;
  - drop the per-row path and doc-ID maps;
  - add the §13.4 node cap;
  - reserve the true heap.

## Score for the storage reviewer on these findings

**82 / 100.** Every substantive claim held when I re-derived it from the code. Points come off for:
- the wrong row-group number (8,192 against the 2,048 Basin path);
- missing that the engine already writes ZSTD-3;
- the REST framing of delete-after-commit;
- "String-keyed union-find";
- one mis-cited UDF line;
- a weak D2 stopgap;
- a D9 mechanism that conflicts with the registry model;
- no D11 fix.

**My confidence: medium-high.** Everything was read in code. D2's byte drift and D11's heap figure are modelled, not measured.
