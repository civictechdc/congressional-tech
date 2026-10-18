# Reuse table metadata within each operation

The first browser check of the completed backend publication failed independently
of backend preparation. The backend at frozen `2feb8c7` had already completed
exact verification of 1,683,430 filenames, all observation values, 270 output
proofs and 86 bound / 0 withdrawn reviews. Its files remain unchanged.

With the normal 64 MiB decoded cache, parsed filename metadata did not fit.
The first 352-field technical record parsed metadata **45 times** in 19.086 s;
the same warm operation parsed it 45 more times in 17.435 s despite **zero HTTP
requests**. The records matched exactly. A source-URL search then exceeded its
120 s case limit. Peak sampled process-tree memory was 3,639,607,296 bytes under
the unchanged 7 GiB local watchdog. The original receipt remains at primary
`output/publication-remediation-20261018/rollout/browser-layout-check/attempt-1/receipt.json`.

The retained-byte cache correctly refused the oversized value. The repeated
work came from later chunks asking for the table again after the shared
in-flight load had finished. The reader now passes one operation-owned
`{buffer, metadata, spans}` handle through its private read and prefetch helpers:

- A technical record initializes once and shares the handle across all existing
  eight-column reads and prefetch.
- Selected rows reuse their existing handle for every selected group and its
  prefetch. A single read and its prefetch also share one handle.
- A shared column load keeps one handle across all row-group workers. It still
  runs independently of any one caller's abort signal.

The handle is not added to a permanent cache or returned with result values.
Its local references finish with the operation. Existing cache admission,
48 MiB compressed / 32 MiB range-entry / 64 MiB decoded defaults, shared pending
loads, failure eviction, independent cancellation, six column workers and
eight-field technical decoding are unchanged. A later operation can parse
unadmitted metadata again; the correction removes repeated parsing *within*
that operation. Backend code, resource limits and public data are untouched.

## Focused verification

A new test forces decoded admission off with a **one-byte** cache and rewrites
only its generated Parquet fixture into two-row groups. The technical record
has 28 scalar fields, requiring four bounded reads. It fails on the original
reader with **5 parses instead of 1**, and passes on `592480c` with one parse.

The same fixture verifies exact original values and results, including nested
Unicode/null/empty/duplicate evidence through the maintained suite. The new
checks establish one metadata initialization per selected multi-group read,
one for a read plus prefetch, and one per complete column load across four
groups. Searching a source column and returning selected browse rows requires
two table initializations in total. Repeating it performs zero additional HTTP
requests while parsed metadata stays unretained. Cache bytes and peak stay zero
for the one-byte decoded budget; compressed storage remains within its limit.

Injected metadata failure retries successfully. Canceling one technical-record
or column-search waiter leaves the concurrent caller successful and exact.
These tests retain the existing shared-load/failure behavior rather than adding
special cancellation state to the handle.

All **101** focused filename-reader and UI checks passed under Node **22.22.2**,
npm **11.19.1**, and the existing read-only Python **3.12.13** runtime. The
engine-strict frozen site install left the lock unchanged. Independent static
review approved exact commit `592480c`; the report is primary
`output/publication-remediation-20261018/rollout/browser-layout-check/independent-review-592480c.md`.
The original regression failure is retained in this worktree's
`output/browser-metadata-reuse/baseline-regression.log`.

## Separate actual-catalog focused probe

The authorized independent reviewer then ran one changed-frontend probe against
the same closed backend, with identical cases, runtime, cache/heap settings,
120 s case timeout and 7 GiB process-tree ceiling. The loader hash matches exact
`592480c`. Both technical results preserve the original 352 fields, 10,257
result bytes and SHA-256
`be2e436ba97c92dc310a4fdcf945ee85450004e0cb6e1e21d5fb8bfedf21ff21`.

| Operation | Original attempt | Changed frontend | Metadata parses |
| --- | ---: | ---: | --- |
| Technical cold | 19.086 s | 0.596 s | 45 → 1 |
| Technical warm | 17.435 s | 0.459 s | 45 → 1 additional |
| Source-URL search | Timed out at 120 s | 27.523 s | 2 for column load and selected browse rows |

The search completed with 1,014,639 matches. The original timed-out search has
no completed result hash or latency, so this does not establish search-result
parity against a completed original run. Sampled process-tree peak was
2,022,293,504 bytes versus 3,639,607,296 bytes before. These are single paired
observations, not general latency or memory guarantees.

Receipts remain at primary
`output/publication-remediation-20261018/rollout/browser-layout-check/attempt-2-frontend/receipt.json`
and `comparison.json`; the first failed attempt remains immutable. This probe
reused the accepted backend and performed one source-column search, with no
backend rerun. It is not exhaustive or deployed browser qualification.
The implementation agent ran only controlled fixtures; the separate actual
probe ran under root authorization. No network acquisition, public write,
workflow dispatch, push or merge was performed by this implementation.
Exact source references and local commands are in
[evidence/browser-metadata-reuse.json](evidence/browser-metadata-reuse.json).
