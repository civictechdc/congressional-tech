---
id: ct-0n0y
status: closed
deps: []
links: [ct-tw3r]
created: 2026-10-22T17:36:18Z
type: bug
priority: 0
assignee: mikewolfd
parent: ct-syem
tags: [docspec, bug, custody, memory, transport]
---
# Fix 4 docspec_client runtime bugs (cleanup_safe 422 data loss, read_arrow missing pin verification, Host.close SIGINT race, _write_producer_parquet .to_pylist() OOM)

CS300 Audit Finding (DocSpec Client & Boundary Auditor - 4 Active Runtime Bugs):
1. Pre-Admission Refusal Misclassification in cleanup_safe (packages/docspec_client/src/docspec_client/docspec.py:1547-1555 vs docspec-rs/src/http.rs:698): docspec-rs maps any unlisted error code to 422 UNPROCESSABLE_ENTITY (http.rs:698), while cleanup_safe assumes any 400 <= status < 500 with a non-empty code outside {'worker', 'custody_quarantined', 'timeout', 'host_unavailable'} is a deterministic pre-admission refusal and deletes the staged producer input directory via shutil.rmtree (docspec.py:1949, 2122, 2227). Also cleanup_safe checks 'timeout', whereas docspec-rs/src/http/deadline.rs:48 emits 'request_timeout'.
2. Missing Pin & Header Verification in NativeDatasets.read_arrow (docspec.py:2479-2510): When group != 'source', read_arrow bypasses _read_pin_endpoint and omits both the GET /datasets/{dataset}/versions/{version} != pin check and the response header checks (docspec-dataset, docspec-version, docspec-manifest-blake3, content-type) enforced by source_batches (L2563-2581), read_keys (L2320-2338), and _read_pin_endpoint (L2354-2369).
3. Graceful Shutdown Race in Host.close() (packages/docspec_client/src/docspec_client/docspec_host.py:228-250) & _finalizer Leak (docspec.py:1791): Host.close() closes process.stdin (L230) and immediately on the next line (L233) sends SIGINT and waits at most min(self.timeout, 5) seconds before SIGTERM/SIGKILL, defeating docspec serve --shutdown-on-stdin-eof draining (and note 7 macOS CrashReporter .ips stack-overflow crashes in docspec where parentProc exited early). Also NativeDatasets._finalizer (docspec.py:1791) only calls self._host.release() without closing self._responses when host.owners > 1, leaking open ArrowResponse streams and Rust read permits.
4. OOM Hazard in _write_producer_parquet (docspec.py:1074-1088) and apply_update_merge_spec (docspec.py:499-500): Whenever stored.nbytes > 4_000_000, _write_producer_parquet calls stored.to_pylist() (L1078) just to estimate row byte lengths, expanding multi-MB Arrow tables 5x-10x into Python dicts.

## Acceptance Criteria

1. Align cleanup_safe with docspec-rs error semantics (include 'request_timeout' and use an explicit pre-admission refusal flag or allowlist so post-admission 422 errors never delete staged producer inputs). 2. Route read_arrow (non-source group) through verified pin & header checks. 3. In Host.close(), allow stdin EOF a grace period to drain before sending SIGINT/SIGTERM, and ensure _finalizer closes self._responses. 4. Replace stored.to_pylist() in _write_producer_parquet with Arrow-native batch/slice sizing.


## Notes

**2026-10-22T17:42:50Z**

Subagent Self-Review Additions:
1. Cross-link Bug 1 (cleanup_safe vs http.rs:698) to ss-mn81 and ss-e2it in spicy-stack: coordinate so docspec-rs ErrorBody (src/http.rs:607-700) includes an explicit pre-admission refusal signal and cleanup_safe (docspec.py:1547-1555) handles 'request_timeout' (src/http/deadline.rs:48).
2. Bug 2 addition (docspec_host.py:261-304): When a server deadline expires mid-stream after HTTP 200 OK headers are sent (docspec-rs/src/http/deadline.rs:69), the truncated Arrow IPC stream raises pa.ArrowInvalid or OSError('DocSpec Arrow response lacks a complete stream terminator') in ArrowResponse.finish() (docspec_host.py:300-303) instead of a structured DocSpecFailure (code='request_timeout' / 'stream_truncated').
3. Bug 3 addition (docspec_host.py:70-71, 146-154, 191-195, 219): Store self.workspace directly on Host instead of indexing self.command[self.command.index('--workspace') + 1] in Host.close() (L219) and acquire_host() (L70-71); enforce a bounded response byte limit in Host.request() (L191-195, matching docspec_dagster/client.py:26 RESPONSE_LIMIT = 1 << 20) and reject % zone IDs / whitespace in _ready_address (L146-154).
4. Bug 4 addition: Cite packages/congress_api/src/congress_api/retention/raw_storage.py:19, 375, 462, which imports private _merge_row_pair (docspec.py:419) and calls apply_update_merge_spec (docspec.py:479-603, which calls .to_pylist() at L499-500).

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch syem).
- Grades: proposal 84 → 84, work 78 → 78.
- Problem: Residual of the exact AC1 hazard: `pre_admission` comes from the error *kind*, not from where the error was raised.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:84
- Covered by: WS3 step 3 (ct-tw3r), which sets `pre_admission` at the engine's admission point.
- See docs/reviews/2026-10-24-ticket-audit/README.md
