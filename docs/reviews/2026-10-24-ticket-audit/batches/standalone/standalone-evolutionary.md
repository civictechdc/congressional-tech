# Standalone batch: evolutionary-refactoring audit (Audit mode)

This is an audit only: it inspects and recommends, and changes nothing. The greenfield lens applies: only the raw data in `congressional-tech-raw` must survive (bodies, receipts, provenance); everything else can be rebuilt.

Coverage: the hotspots found in the earlier passes (`standalone-verdicts.md`, `standalone-greenfield.md`), traced through their entry points on main c858a5a2. This pass ran only read-only greps; the test results cited come from earlier passes.

Findings are marked **[confirmed]** (read in code or tested) or **[hypothesis]** (inferred, not measured).

## Ranked hotspots

### H1. Code provenance for raw writes in recovery import (ct-esm4; ct-fqgf and ct-vxzu are sound)

1. **Contract.** `dispatch_corpus_recovery_import.py` is the only route in this batch that writes raw data:
   - bodies and receipts, written immutable (`corpus_recovery/transfer.py:26-46,132,147`);
   - the raw selector, via compare-and-swap (`transfer.py:94-101`; `RAW_KEY = 'indexes/raw.json'`, `raw_storage.py:364`).

   It must keep:
   - immutable writes with exact readback;
   - no second PUT after a lost acknowledgment;
   - the seal comparison against the caller's own bytes (ct-fqgf, `inventory.py:19-30`);
   - the fsynced `events.jsonl` raw-write log (`dispatch_corpus_recovery_import.py:100-105`);
   - a code identity that covers everything that executes.
2. **Pressure: cloned workflows with divergent policy.** [confirmed] The two dispatchers each own a pinning policy:
   - publication pins whole package folders (`dispatch_corpus_recovery_publication.py:29-39`);
   - import pins `congress_api/src` plus seven named modules by hand (`dispatch_corpus_recovery_import.py:107-122`).

   The import's hand list drifted and now misses `docspec_client` and `congress_shared` (custody/storage), which is exactly the code that writes raw datasets.
3. **First move.** Give pinning one owner. Lift the existing folder-digest pinning (`SelectedRuntime.PACKAGES` and its digest walk) into one corpus_recovery helper, have the import dispatcher use it, and delete the hand list. Do not invent a new scheme.
4. **Evidence.**
   - Existing tests to keep: `corpus_recovery/tests/test_import_corpus_recovery_batch.py:108` (lost-ack writes no duplicate), `:194`; `congress_api/tests/test_r2_body_files.py:25` (body `IfNoneMatch`); and the ct-fqgf test `test_bounded_import_evidence_names_malformed_fields_and_keeps_primary_error`.
   - Self-referential test, fix first: `scripts/corpus_recovery/tests/test_dispatch_corpus_recovery_import.py:111-117` checks only modules it names. Replace it with a completeness check: every repo-owned module loaded during an import dry-run must appear in the pins.
   - Missing test: when an existing body object holds different bytes, the import must fail on readback.
5. **Change from earlier passes.** Confirms H1 as the #1 raw risk. The first move is now "reuse the existing folder pinner", replacing my earlier suggestion of git commit plus lockfile plus clean-tree.

### H2. Write policy for the shared raw bucket (cross-cutting; R2/R5 from the greenfield pass)

1. **Contract.** Derived publication writes into the raw bucket with the same credentials (`viewer_publication/constants.py:4`; the bucket is public via edge rules, `r2_edge_rules.py:17`). The behavior that must hold: no derived writer can create, replace or mask a raw object.
2. **Pressure: wrong abstraction / boolean accumulation, and an exhausted representation.** [confirmed] The object class is encoded as key-prefix string tests scattered across several places:
   - `R2Store.put` combines the `immutable` flag with `bodies/`, `indexes/`, `indexes/native-manifests/` and `indexes/processing/` branches. Any other non-immutable key gets an **unconditional** write (`r2.py:338-378`).
   - The read cache treats `receipts/` and `bodies/sha256/` specially (`r2.py:247-255`).
   - The guarded client has its own allowlist (`viewer_publication/client.py:124-135`).

   The local publication's catalog step writes through a plain `Store(R2Store)` (`corpus_recovery/publication.py:88-104`), outside that allowlist. [confirmed, adjacent] With `cache_dir` set (`congress_api/cli/raw_sync.py:323`), "readback verification" can read the local cache instead of R2 (`r2.py:272-278`).
3. **First move.** Use a platform primitive rather than more prefix code: put derived output in its own bucket, behind a bucket-scoped R2 token that cannot write `congressional-tech-raw`. Until then, the cheapest code-side step is one namespace-policy function consulted by both `R2Store.put` and the guarded client, which refuses unconditional writes to raw classes. That is a behavior change and needs explicit scope.
4. **Evidence.**
   - Existing: `viewer_publication/tests/test_recovery_viewer_transfers.py:144` refuses `indexes/raw.json` only.
   - Missing:
     - refusal tests for `bodies/` and `receipts/` through every derived writer;
     - a test that readback verification bypasses the immutable cache;
     - a characterization of today's unconditional `R2Store.put` path, recorded before it changes.
5. **Change from earlier passes.** The recommendation stays (separate bucket), but it is now the first move for H3 as well, because it removes the main reason the publication durability stack exists in the raw bucket.

### H3. Durability stack for derived viewer publication (ct-v6ao, ct-30pw, ct-5jqd, ct-2ut4, ct-76n5, ct-bpyj, ct-h73z, ct-piku)

1. **Contract.** The greenfield job: publish a rebuildable release and move one public pointer atomically.
   - The publication dispatcher declares "no acquisition or raw writes" (`scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:1`).
   - The pointer compare-and-swap primitive already exists (`viewer_publication/client.py:278-294`).
   - Two things must survive: the raw-prefix refusal (until H2 lands) and the mapping file's `IfMatch` conflict refusal (`corpus_recovery/mappings.py:77-79`).
2. **Pressure: defensive sediment, plus parallel implementations.** [confirmed] About 1,591 lines across `continuation.py`, `local.py`, `attempt.py`, `plan.py`, `reconciliation.py`, `client.py` and `resume.py`, with about 1,598 lines of tests. Their accumulated parts:
   - a remote nonce-chained journal;
   - a local event log (`local.py`);
   - three client wrappers (Guarded, Continued, plain);
   - accepted-plan reissue, reconciliation progress, incomplete-build diagnostics and a resume descriptor;
   - an alternate-runtime loader (`SelectedRuntime`, `dispatch_corpus_recovery_publication.py:21-149`). It exists so publication can run code from a different checkout, which only matters for resuming old attempts.

   It is also quadratic: the full state is rewritten on every event (`continuation.py:224-230`), and the writes dict is copied on every event (`:451`, `local.py:28`).
3. **First move.** Bounded replacement behind the publish contract:
   - write the release under a fresh immutable prefix with `IfNoneMatch`;
   - verify it;
   - compare-and-swap the pointer;
   - on any failure, discard and rebuild.

   Then delete the journal, local events, progress reporting, diagnostics, resume descriptor, plan reissue and `SelectedRuntime` together. Do not leave a second authority behind.
4. **Evidence.**
   - Characterize first:
     - the pointer advances only after every release object is verified;
     - a concurrent second publisher loses the compare-and-swap;
     - raw prefixes are refused;
     - mapping conflicts are refused.
   - Self-referential tests to delete with the code: `test_checkpoint_costs.py` (counts flushes and fsyncs), the journal internals in `test_publication_state_bounds.py`, `test_reconciliation_progress.py`, `test_local_continuation.py`, the historical case in `test_workflow_resume.py` (currently failing), and `test_runtime_ownership.py`, which imports `docs/experiments/efficiency-debt/runtime-ownership-probe.py`.
   - Keep `test_publish_corpus_recovery_mappings.py:186-270`.
5. **Change from earlier passes.**
   - **ct-piku changes from "sound, leave as is" to delete.** It protects only a derived route.
   - The rest confirms the greenfield "delete" call.

### H4. news_lake append keys and the parallel engine (ct-xu1o, ct-ur7v; ct-r60e, ct-ur2y)

1. **Contract.** Append tables must make an exact replay a no-op and refuse a conflicting id reuse. Nothing here is salvage data: news captures store only `payload_uri` plus hash (`news_lake/adapters/common.py:83-93`), and nothing reaches R2.
2. **Pressures.**
   - [confirmed] **Success-shaped fallback.** A process-local `_known_ids` cache decides correctness (`storage/docspec/lake.py:323-337`), and the time keys come from the run clock (`context.py:113,178-191`).
   - [hypothesis] **Two mechanisms for one pressure.** Table compaction with an undersized-file threshold of 32 (`docspec/schema.py:27`, `compaction.py:226-245`) already bounds the file count that the time keys were meant to keep from being scanned.
   - [confirmed] **Parallel implementations behind `hasattr` dispatch.** `storage/releases.py:187`, `storage/coordinator.py:281`, and PyIceberg `In` scans and deletes (`coordinator.py:15,183,245,346`) remain on the production CLI path.
3. **First move.** Delete the time-keyed append (`APPEND_UPDATE_KEYS`, `schema.py:30-40`) and `_known_ids`, going back to `['id']` keys bounded by compaction. Separately, delete the PyIceberg branches so `Coordinator` speaks only to DocSpec.
4. **Evidence.**
   - Fix first the order-dependent test at `packages/news_lake/tests/test_docspec_backend.py:1461-1468`: run the different-timestamp conflict first, in a fresh lake.
   - Add a test that replays a regenerated poll in a fresh process.
   - Measure `['id']` lookup cost with compaction on (never measured; ct-pgxn ran without compaction).
   - Replace the PyIceberg differential-oracle tests with direct C1–C5 contract assertions before deleting the oracle.
5. **Change from earlier passes.** ct-xu1o moves from "fix with an id fallback, or revert" to "revert". ct-ur7v's "delete the oracle" is confirmed and widened to the `hasattr` dispatch.

### H5. Producer Parquet write fallbacks in docspec_client (ct-nmjc)

1. **Contract.** Submit Arrow tables to the engine as Parquet input files. These feed both raw-adoption and derived writes.
2. **Pressures.** [confirmed]
   - **Boolean accumulation.** `_write_producer_parquet(row_group_size=None, _legacy_row_group_sizing=...)` has three sizing modes and five magic thresholds (`docspec_client/transport.py:142-185`).
   - **Compatibility sediment through error-string fallbacks** in `run_table`:
     - on `operation_conflict` it rewrites the input with the legacy layout so the digest matches an earlier attempt;
     - on `unknown field ... partition_by` it drops `partition_by` for older engines (`docspec_client/client.py:516-535`).

     In a greenfield project there are no older engines or earlier attempts to match, and the engine now splits oversized batches itself (docspec-rs c937ef8 / c949c67).
3. **First move.** Delete both error-string fallbacks and the legacy mode, then collapse to one byte-targeted row-group mode, or none if the engine split suffices.
4. **Evidence.** The existing test fakes the engine (`congress_api/tests/test_docspec_runtime.py:436`) and is self-referential for this question. Add a native-loopback test that submits a large table under `max_batch_bytes=4 MiB` (suite `scripts/dev.py test native-loopback`; not run here).
5. **Change from earlier passes.** Stronger than the greenfield call (collapse the modes): also delete the retry fallbacks.

### H6. Release identity and script shims (ct-ma8a, ct-r46l; ct-n3qy and ct-vd5b are fine)

1. **Contract.** A scheduled no-op skip for derived publication, keyed on code identity.
2. **Pressures.** [confirmed]
   - **Handwritten infrastructure:** a hand-maintained `source_files` list (`viewer_publication/release_identity.py:28-56`), missing 10 of 39 modules.
   - **Indirection without responsibility:** the shim `scripts/viewer_release_identity.py`, the empty-module injection (`release_identity.py:12-16`) and the `gc.get_referrers` module swap (`scripts/publication/publish-viewer-r2.py:17-26`).
3. **First move.** Key the identity on the git tree hash plus a dirty check, then delete the shims and the injection.
4. **Evidence.** `scripts/publication/tests/test_workflow_resume.py:147` asserts named files and is self-referential; delete it. Add a property test: changing any tracked file under the publication packages changes the identity.
5. **Change from earlier passes.** Confirms "simplify".

### Left alone (a valid outcome)

- **ct-fqgf, ct-vxzu:** small shared helpers on the raw path with meaningful tests.
- **ct-tuez:** interval-only bound use (docspec-rs `key_pruning.rs:735-746`) with tests on both sides.
- **ct-13g5:** column pushdown that makes rebuilds cheaper.
- **ct-tdsx:** `startup.ts` is a small shared verified loader.
- **ct-oc2g:** the v5 deletion is done.
- **ct-4zer, ct-m9ry, ct-o6d1, ct-2bhh:** no change pressure while nobody uses the viewer. Delete the `Catalog` class (`viewer_publication/filename_viewer.py:275`) only when the review-binding CLI (`filename_review_binding.py:171`) moves to the native reader.
