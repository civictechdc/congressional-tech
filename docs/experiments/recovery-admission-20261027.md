# Recovery metadata admission and exact-pin read retry

The scoped repair removes repeated immutable-schema checks and cached chunk JSON
parsing during selected-table admission. In three paired runs over 32 retained
metadata pages (2,048 components,2,766 logical source rows), median process CPU time
fell from **2.2014 s to 1.3462 s**: **38.85% less CPU**, or1.64 times faster. Median
wall time fell from 2.4478 s to 1.3627 s. Every admitted metadata table digest and the
complete recovery JSON from the shared private four-source/three-document fixture
matched exactly. This is bounded local evidence, not a full-corpus runtime claim.

The native client's exact-pin GET now retries the observed upstream transport
failure at most three times within its original absolute deadline. It never
retries a delivered Arrow stream or any write. This addresses the actual failure
that discarded the temporary admission index after 27 minutes.

## Diagnosis and boundedness

The observed initial recovery path is:
`CatalogRecoverySources._initial_index` → selected filename `iter_batches` →
`CatalogComponentReader.read` → `_require_component` → `_component_binding`.

Selected-table admission exhausts component metadata before yielding its first
native batch. Consequently a32 KiB recovery spill alongside a growing selected
index does not indicate a stalled row loop. An 11.89-second proc-only sample showed
99.57%of one CPU,1.086 GBadditional character reads,52.2 MBcharacter writes, zero
physical reads, and the selected temporary file growing from 1,199,812,608 to
1,203,240,960 bytes. Character reads include page-cache and other process reads;
these figures do not imply remote download volume.

The coordinator's10-second profile contained197 samples and zero errors. Binding
JSON encoding, logical-schema compatibility, cached chunk JSON decoding and
per-component construction dominated its stacks. The retained
[root profile](recovery-admission-20261027/root-profile.raw) provides the raw
frames. A separately started nonblocking profile completed before the coordinator
asked to reuse its profile; its 441 usable samples/43 read errors independently
showed 39.68%under schema compatibility and 31.29%under component binding. These
inclusive shares describe one interval, not whole-run attribution.

The selected catalog contains 1,241,157 document components and 1,683,430 sources.
The metadata pass is finite; the subsequent failure proves it reached the first
native input. Root reported its final failure at 12:18:58 EDT after 1,647.56 seconds:
`DocSpecFailure: Failed to execute http request` during `_verify_pin`, requesting
R2 catalog `/v1/config`. No active SQLite database was opened or queried during
this diagnosis. The selected index is temporary and its context manager cleans
it up on failure; the completed renderer checkpoint and manifest remain separately
owned by the coordinator.

## Small changes and validation authority

`SelectedCatalogTable.iter_batches` retains two scan-local standard-library LRU
caches: at most 64 decoded physical-chunk metadata objects, keyed by the full
canonical reference including length/digest; and 16 successful compatibility checks,
keyed by exact immutable schema text against the captured logical Arrow schema.
Evicted chunk metadata is still available in the existing temporary SQLite store.
The limits bound entries, not all Python allocator memory. Each original metadata
object retains its maintained1 MiB input limit. No global/persistent cache or
checkpoint format was added.

Every component still runs `_require_component`, including the complete binding
hash, source/document ownership, schema, membership and count checks. Admission
still completes before native delivery. The same 32-page replay performed:

| Operation | Baseline | Candidate |
| --- | ---: | ---: |
| Schema compatibility checks | 2,048 | 1 |
| Chunk metadata SQL lookups | 4,096 | 1,650 |
| Component binding encodes | 2,048 | 2,048 |
| Binding JSON bytes encoded | 483,666,989 | 483,666,989 |

The remaining binding encodes establish different component proofs and remain.
No validation was bypassed through a previously verified-page flag.

`NativeDatasets._verify_pin` retries only the exact-pin GET when the diagnostic
contains the observed `Failed to execute http request` and status is absent or
500/502/503/504. Backoffs are0.25 and 0.5 seconds. All attempts use the same absolute
deadline; insufficient remaining time preserves the failure immediately. Host
request cleanup closes the failed response before retry. Exact returned-pin
comparison still precedes verification-cache admission. Deterministic refusals,
wrong returned pins and Arrow-stream failures retain their existing failure path.

## Checks and replay

Unchanged baseline:48 passed,11 native-runtime skips in the coalesced catalog,
native recovery and DocSpec host suites. Final focused check, also including the
initial recovery scan suite: **67 passed,11 skipped**. The qualified native CLI and
old-protocol comparison binary were not configured; no new native runtime was
built or qualified.

Added tests cover fresh admission per scan, exact rows/order, full-reference
length corruption after cache use, successful transient GET retries, exhausted
attempts, deadline preservation, permission/schema refusal, and wrong-pin refusal.
A maintained mock HTTP adapter test verifies two transient pin failures followed
by one exact Arrow payload, preserving null/duplicate rows. Existing initial-scan
cases cover replacement order, nullable/schema changes, ambiguity, capture
completeness, policy admission and cleanup after interruption. Existing transport
cases keep premature/aborted Arrow streams as failures.

```sh
PYTHONPATH=packages/viewer_publication/src:packages/congress_api/src:packages/congress_shared/src:packages/docspec_client/src \
  /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest \
  -p no:cacheprovider \
  packages/congress_api/tests/test_catalog_coalesced_batches.py \
  packages/viewer_publication/tests/test_filename_native_recoveries.py \
  packages/viewer_publication/tests/test_initial_recovery_scan.py \
  packages/congress_api/tests/test_docspec_host.py -q
```

[Comparison](recovery-admission-20261027/comparison.json), paired raw results,
[source hashes](recovery-admission-20261027/source-hashes.json), both recovery JSON
files and the [replay](recovery-admission-20261027/replay.py) are retained. Replay
reads retained immutable metadata only, stops real-data admission deliberately at
a fake native boundary, hashes all four private admission tables, and then runs
the maintained recovery producer over one shared private native-Arrow fixture.
It does not download real payloads. Metadata-result comparison hashing is timed
separately and excluded from admission timing.

Initial block-ordered wall runs varied widely on the shared host (candidate
3.81–18.21 seconds); [those measurements](recovery-admission-20261027/initial-wall-runs.json)
remain retained. The final three pairs interleave baseline/candidate and report
process CPU time as well as wall time. No production speedup is inferred from
those host measurements.

An independent subagent approved the production diff and regression coverage;
review was static. The final added HTTP test passed in the owner's focused run.
No runtime, source receipt, worker, active coordinator, remote object or
operational checkpoint was changed. Checkpoint compatibility and activation stay
with the coordinator. Admission remains temporary: a later failure after these
bounded retries can still require a new scan; this repair adds no persistence or
midstream retry.
