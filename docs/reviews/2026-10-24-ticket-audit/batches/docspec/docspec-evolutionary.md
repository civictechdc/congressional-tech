# docspec-rs: evolutionary-refactoring audit (Audit mode, no changes)

**Scope.** The hotspots found in my ticket passes (`docspec-verdicts.md`, `docspec-greenfield.md`) at `d9c6719`, plus their callers and tests. This was not an exhaustive repository scan.

**Lens.** Greenfield. Only the raw data in R2 (`receipts/`, `bodies/`) must survive, and the engine holds none of it uniquely.

**Commands run.** Read-only `git`, `grep`, `sed` and small `python3 -I` inspections only.

**Checks not run.**
- No cargo build or test. Disk is at 99% with 29 GiB free, and the brief limits runs to `--all-features`.
- The one decisive characterization run (a non-`test-util` integration run) is therefore *recommended, not performed*.

## Recovered contract: what congressional-tech actually needs

Source: every route and command `docspec_client` calls (`ct:packages/docspec_client/src/docspec_client/client.py`), plus the capacity planner (`ct:.../retention/native_capacity.py`).

- **Writes and computation**
  - `/run` (JSON and Arrow IPC), `/updates/run` with `UpdateMergeSpec`
  - `/refreshes/*`: join, aggregate, connected components
  - `/backfills/*`, `/continuous-backfill`, `/receipts/*`, `/exports/*`
  - `/compactions/run` (`client.py:1184`), `/generations/seal`, `/inputs/capture`, `/dependencies/corrections` (`client.py:810-840`)
- **Reads.** latest, release, inspect, pinned source batches, `read_keys`.
- **Capacity.** `/retention/inspect` and `/retention/removal/plan` (`native_capacity.py:480,549`), plus `compact_lifecycle` *only when not remote* (`native_capacity.py:379`).
- **CLI.** Only `docspec hash <path>` (positional, `client.py:413`), characterised by `tests/remote_cli.rs:20`.
- **Not called by anyone:** every `retire-*` route, restore points and remote restore, succession proofs, abandon/fence operations, remote removal *execution*, and the Dagster adapter.

**Behavior that must be preserved:**
1. The raw-bucket boundary: `scope.key` plus create-only writes plus the digest-checked delete actor (`src/storage/remote/objects.rs:150-240, 527-590, 931-937`).
2. Correct derived outputs: oracle-equal results, and one coherent selected release per dataset.
3. Stable consumer identities, for example `document_id` parity with `ct:.../index/bipartite.py:197`.
4. The routes and CLI shapes listed above, or a client migration made in the same change.

## Hotspots, ranked

### H1. A build-configuration fork plus dispatch on consumer dataset names (rank 1)

**Where.** 60 `#[cfg(all(not(test), not(feature="test-util")))]` sites; 53 came from `b4b827d`, whose commit message has no body and no measurement.
- Deferred lifecycle commits: `src/catalog.rs:765-790`, `src/engine/pipeline.rs:510-518`.
- A flush whose errors are discarded: `pipeline.rs:111-112` (`let _ = …flush_deferred`).
- Admission records an input it never uploaded for `raw-*`/`catalog-*`/`obs-*`/`source-observations-*` datasets: `pipeline.rs:317-335`.
- Verification skips for the same names: `release_check.rs:86-93, 226-229`.
- The `GuardedCatalog` re-load is test-only: `catalog.rs:696-700`.

**Pressure.**
- **Parallel implementations.** There are two lifecycle-commit protocols, chosen by build features.
- **Multi-axis dispatch.** Behavior depends on remote × request kind × `base.is_none()` × dataset-name prefix × cfg.
- **Success-shaped fallbacks.** Flush errors are dropped, and admission takes the "local file verifies → record a remote ref without uploading it" shortcut.
- **Defensive sediment, inverted.** Production skips checks that the tests run.
- **Mechanism of harm.** No test can characterize what the shipped binary does, and consumer policy (dataset naming) is wired into the engine. The likely root cause is in the consumer's representation: it creates one dataset per candidate leaf (`ct:.../raw_storage.py:1058-1075`), multiplying fixed per-dataset R2 cost. The engine compensated with name-based fast paths.

**Cheapest safe move.** One build, one behavior.
1. Delete the dataset-name predicates first. They are post-pin, unqualified, and nothing depends on them, because the consumer pins `c949c67`.
2. Then make one explicit decision about the commit protocol, which has two coherent endpoints:
   - **(a)** Durable per-phase commits only: delete the deferral code.
   - **(b)** A single end-of-operation commit, with crash meaning "rebuild the operation": delete deferral as a mode *and* the phase-resume and recovery machinery it half-replaces. This is the larger greenfield simplification, but it contradicts the AGENTS.md rule to preserve expensive phases, so it is the user's call.
3. Longer term, the consumer should use one partitioned dataset per kind (ss-k3mg buckets) instead of a dataset per leaf.

**Evidence needed before moving code.**
- **Existing:** every integration suite runs with `--all-features`, so it characterizes only the test-util path. The MockS3 remote tests are `cfg(test)`, so the name branches are compiled out there too.
- **Missing:** run `cargo test --locked --test integration` once *without* `--all-features`. Integration tests compile the library without `cfg(test)`, so local deferred commits would actually execute. Also missing: a remote raw-leaf Build measurement (catalog commits, wall time) with and without deferral, before choosing (a) or (b).
- **Self-referential:** none. The coverage is absent, not circular.

**Change from earlier passes.** The delete call stands. I am revising "make deferral the only mode if measured" into an explicit (a)/(b) fork, because (b) could remove far more code. It stays rank 1: it is the only post-pin code that writes a false custody record.

### H2. Lifecycle records are string-keyed JSON rows dispatched by prefix in several places (rank 2)

**Where.**
- About 35 key families.
- `Inventory::record`, a ~612-line `if key.starts_with(...)` chain (`src/engine/retention/inventory/expand.rs:54-663`). It fails closed on unknown keys (`:658-661`), which is good.
- Further prefix dispatch in `src/engine/retention/owners.rs` (24 checks) and `src/engine/retention/compaction.rs` (10).
- GC reachability decided by collecting every `/`-containing JSON string and substring-matching it (`compaction.rs:686-726`).
- 8 retirement planners (`changes/retirement.rs`, `retention/{availability,compaction_recovery,export_recovery,grants,recovery,retirement×3,seals}.rs`).

**Pressure.**
- **Exhausted representation.** Typed records are simulated by string prefixes plus loosely shaped JSON.
- **Cloned workflows / shotgun change.** A new family needs synchronized edits in at least 3 dispatchers, plus a planner.
- **Mechanism of harm.** Every lifecycle feature pays this coordination cost, and the GC correctness argument rests on string heuristics.

**Cheapest safe move.** Delete before typing. Remove the families no consumer writes: retirement families, restore, the succession archive, owner grants, availability retirement. Only then parse the survivors once into a `LifecycleKey` enum, so the compiler enforces coverage. Do *not* run ss-8ani's typed refactor first; that would put types on sediment.

**Evidence needed before moving code.**
- **Existing characterization:**
  - the retired-operation reclaim test in `tests/operation_retirement.rs`
  - the 260-operation compaction test in `src/engine/retention/tests.rs`
  - `src/catalog/tests.rs:477` (lost commit response)
  - owners and grants unit tests
  - inventory's fail-closed refusal
- **Missing:**
  - A table-driven test: for each consumer-used operation, every record family it writes is accepted by inventory and survives compaction.
  - A property test that GC never removes a path reachable from the selected release or a reader pin.
- **Self-referential:** tests that assert exact key strings lock in the current representation. Treat them as characterization to rewrite after typing, not as contracts.

**Change from earlier passes.** "Delete most of retention" stands. The ordering is new: deletion first, typing second. Keep `/retention/inspect`, `/retention/removal/plan` and local `compact_lifecycle`, because the capacity planner uses them. Keep `Strict<T>`'s unknown-field rejection while GC exists (`retention/inventory/strict.rs`), since it is a real fail-closed trust boundary. The architect's defense of it was right.

### H3. `write_batches_inner` accretes every storage feature (rank 3; the only god-function with change-cost evidence)

**Where.** `src/storage.rs:359-660`, 301 LOC. `storage.rs` was touched by 18 commits since Oct 18 (`git log --since=2026-10-18 -- src/storage.rs`). ss-r9b4 (`c949c67`), ss-k3mg (`d17c855`), ss-mpsp and `97373eb` each edited the same loop: type coercion, skew splitting, a remote 2 MiB file cap (`:376-380`), partition fanout, and identity materialization (`:487-497`).

**Pressure.** Structural erosion: each feature adds decisions inside one stream loop.

**Cheapest safe move (preparatory, when the next storage feature arrives).** Split the loop into stream stages:
- normalize (coerce plus split)
- route (partition fanout plus the writer bound)
- materialize identity

No behavior change.

**Evidence needed.**
- `src/storage/tests.rs:1107` (skew split)
- the fanout-bound test from `381108c`
- `tests/update_pruning.rs` (oracle)
- `tests/partitioning_and_cc.rs:90,280`
- Missing: an end-to-end byte-equality test for a 20+ MB payload through `/run` and `/exports/run`.

**Change from earlier passes.** I am *downgrading* other "god functions" to leave alone, or obviated by the moves above:
- `execute_engine_command` (561 LOC, `src/main.rs:612`) is a flat, uniform command match; a stable dispatch is fine.
- `prepare_and_select` (239 LOC) mostly sheds its cfg branches in H1.
- `Inventory::record` disappears with H2.
- The ss-bhd0/ss-9m7f "<120 LOC" acceptance criteria were size targets with no change-cost evidence. Missing them is not itself a defect.

### H4. Hand-written infrastructure that replaces established behavior (rank 4)

**Where.**
- `src/cli_args.rs`, a hand-rolled argv rewriter. `d05df4d` changed positional clap arguments to `--long` flags (`git show c949c67:src/main.rs:60` `Hash { input }` vs `src/main.rs:135-138`), then added this shim to keep positional calls working.
- A FIPS SHA-256 (`src/engine/connected_components/sha256.rs`) although `sha2` is already in `Cargo.lock`.
- Year/Month/Day calendar math in `compute_partition_column` (`src/storage/partitioning.rs`), while Bucket already uses `iceberg::transform::create_transform_function` (`:289`).
- Per-row facet maps (`src/engine/export/pipeline/facets.rs:197-232`) instead of DataFusion GROUPING SETS.

**Pressure.**
- Handwritten infrastructure replacing established behavior.
- `cli_args.rs` is also compatibility sediment that the refactor itself created.

**Cheapest safe moves, one at a time.**
1. Restore clap-native positional arguments for `hash` (the consumer contract) and delete `cli_args.rs`.
2. Swap in `sha2` behind the existing FIPS test vectors (`sha256.rs` tests).
3. Route Year/Month/Day through the iceberg transform function, gated by a differential test over a wide date range against the current output.
4. Facets last, and only if exports change again.

**Evidence needed.**
- `tests/remote_cli.rs:20` covers positional `hash`.
- The `cli_args.rs` unit test at `:161` tests the shim itself, which makes it self-referential. Delete it with the shim.
- The partition month-refusal tests and the facet assertions in `tests/exports.rs:1122` already exist.

**Change from earlier passes.** I am revising "delete `cli_args.rs`": positional `hash` must survive, but through clap, not a shim.

### H5. Consumer policy inside connected components (rank 5)

**Where.**
- The `document_id = sha256(["bodies"|"sources", …])` formula (`src/engine/connected_components.rs:27-36`).
- Body-edge detection by name (`topology.rs:24-28`: namespace `body`/`bodies` or column `body_key`).
- Incremental refresh builds full old and new topologies (`connected_components/incremental.rs:97-98`).

**Pressure.** Wrong owner, plus dispatch on names.

**Cheapest move.**
- Make the edge role an explicit enum on `ConnectedEdgeSpec`.
- Let the spec supply the id expression (the `ScalarExpr` AST already exists).
- Leave the two full topology scans alone until measured; they are linear.

**Evidence needed.**
- `tests/partitioning_and_cc.rs:536,1166` re-implement the same serde/sha formula, so that check is self-referential.
- Add one golden vector produced by the Python `compute_document_id` (`ct:.../bipartite.py:197`, `ensure_ascii=False`, compact separators).

**Change from earlier passes.** Severity unchanged (medium). The data is derived, but `document_id`s are consumer URL identities.

### H6. Error identity is a string, and admission state is inferred from it (rank 6)

**Where.** `ErrorKind::from_code` prefix/suffix heuristics (`src/error.rs`); `pre_admission` derived from the error kind (`src/http.rs:277-286`).

**Pressure.** Wrong abstraction. "Pre-admission" is a fact about which phase failed, not about the code string.

**Cheapest move.** Set the flag once at the admission seam: errors before the admission commit are pre-admission, all others are not. Do not build a full typed error taxonomy for its own sake.

**Evidence needed.** Only `src/http/tests.rs:294` exists. Missing: a test that a post-admission failure reports `pre_admission: false`.

**Change from earlier passes.** Severity is lower than my first pass, because staged inputs can be rebuilt from receipts. Still cheap to fix.

### H7. Surfaces nobody uses (rank 7, an outright delete)

**What.**
- Restore points and remote restore (~2.4k LOC)
- Succession proofs and archive
- `retire-*` routes and planners
- Remote removal execution (keep only `plan`)
- `adapters/dagster` (which also calls a non-existent `/capabilities`)
- Most of `src/engine/remote_build_provider_tests` (3.5k LOC); replace with one isolation smoke test: every write and delete stays under `owned_prefix`, and a `receipts/` key is refused.

**Consumer check.** `client.py` calls none of these. A text search alone is not proof of non-use, but this is a greenfield project with no deployment, and the user's statement settles it.

**Change from earlier passes.** The delete call stands. The route-alias call is revised: keep the routes the client uses (`/continuous-backfill`, `/receipts/run`, `/compactions/run`, `/generations/seal`, `/inputs/capture`, `/dependencies/corrections`, `/backfills/*`, `/retention/inspect`, `/retention/removal/plan`), or migrate the client in the same change. Delete the rest, rather than "77 → ~40" blindly.

## Leave alone (sound in the inspected scope)

- Remote scope containment, create-only writes and the digest-verified delete actor (`objects.rs:150-240, 527-590, 931-937`). This is the real raw boundary. Add only an `owned_prefix` overlap refusal.
- Key-point pruning (`src/engine/key_pruning.rs`), with oracle and exhaustive operator tests.
- Vectorized `UpdateMergeSpec` merge (`write/merge.rs`). It is large, but it has oracle tests and no erosion evidence.
- Tail coalescing (`write/compaction.rs`), backed by the measured file-count bound.
- `Strict<T>` unknown-field rejection, for as long as GC exists.
- ss-wie5's decision to decline bloom filters.

## Success-shaped fallbacks (confirmed)

Fix these inside H1/H2, not as separate chores:
- `pipeline.rs:111-112`: the flush result is discarded.
- `retention/compaction.rs:146`: `.unwrap_or_default()` on the head reference walk.
- `storage/object_io.rs:29-31`: `for_path` falls back to Local. Low under greenfield, because it misroutes reads only.
- `http/ipc.rs:535`: a substring fallback for the disk-capacity classification.
