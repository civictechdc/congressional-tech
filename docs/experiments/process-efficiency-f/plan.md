# File-backed catalog and integrated context-cache comparison

Preregistered 2026-10-18 before F timings. This supplements the original D decision; the user's later instruction explicitly asks for aggregate runtime, memory and complexity rather than the original rigid component thresholds.

Decision: retain the file-backed route if correctness and recovery checks pass, and measure its resource tradeoff. Then decide whether a 1 MiB serialized source-context cache is worth adding to this route.

Hypothesis: F removes overlapping whole compressed-table allocations, at a cost of owned temporary copies and streaming hash/copy work. Nested row expansion can still dominate memory. The cache may improve whole-rebuild time, but hit deserialization and bookkeeping may make the benefit too small to justify complexity.

Arms: (1) the current source-context one-pass implementation with the previous bytes-backed catalog I/O, (2) the identical code with F file I/O, and (3) F plus the previously retained bounded-cache candidate. Freeze all sources before timing; publish their hashes. Apply the same benchmark harness, including scratch sampling, to all arms. The cache comparison is directly against arm 2 in new alternating pairs; it does not subtract earlier D results.

Cases: the frozen D constructed high-fanout fixture (32 URLs, 64 paired occurrences per URL, 16 source rows per URL). Each run performs the entire retained-catalog rebuild, archival, generation upload, validation, and exact comparison. These are development fixtures, not full-corpus or viewer-builder qualification.

Held constant: same Docker image ID, no network, 2 CPU quota, 2 GiB limit, one filename worker, same input/reference bytes, warm uncontrolled OS cache, one owned TMPDIR per run. Three pairs per comparison in AB/BA/AB order. Stop on first failure; preserve evidence. Maximum 5 minutes per run and 30 minutes for all runs. No production data acquisition.

Measures: total rebuild wall time; complete qualification wall time including post-build semantic comparison; association-stage time; 250 ms process-tree RSS sampling; 250 ms peak scratch logical and allocated bytes beneath the owned TMPDIR. The same sampler overhead applies to both arms. Peaks can miss shorter events. Retain inputs, implementation hashes, all raw reports and failures. Separately verify ordered row hashes and all stable top-level metadata; allow only fresh pair catalog IDs and code fingerprints independently recomputed from each frozen implementation. Verify history digests against the identical previous tables.

Decision rule: correctness, input immutability, selector/history invariants and the 2 GiB bound are mandatory. For F, report observed wall/memory/scratch tradeoffs without claiming the compressed-file size is the peak saving. For the optional cache, adopt only if paired complete-rebuild improvements are consistent and clearly larger than observed variation; weigh the measured memory/scratch cost and added finalization/LRU code. If timings overlap or benefit is indistinguishable, retain the simpler one-pass route. A small bounded memory increase is acceptable for a clear whole-run gain. Do not infer that F fixes the separate viewer-builder out-of-memory failure.

## Separate large-pair read component

Added before timing at root review request. Read only the verified existing local mirror at `/Users/mikewolfd/Work/congressional-tech/output/filename-patterns-20261015/public-raw-catalog-v3/catalog`; selector generation `cbcf65877e2843ae8b23915c3d05a18f`, catalog ID `76758ea73fa94075bda46ce79e569fd3`. Verify the selector and both file SHA256/size values before trials. Two alternating old-bytes/new-files pairs (AB/BA), each in a fresh process with the same image, 2 CPU/2 GiB limits and no network. Measure selected-pair reading/validation only, retaining the snapshot until memory sampling finishes. Stop on any failed process; no capacity retry or raised limit. At most five minutes per process. This component tests compressed allocations; it is neither a full rebuild nor viewer preparation.

Preflight correction: the supplied `76758...` identity is the catalog ID, not generation; the initial generation assertion refused before timing. The actual selector above and both SHA256 values were then verified.

Component invocation repair before data collection: the offline wrapper accepts `-m module` only. The first process exited on usage validation before importing the component or reading the pair. Its command/log/exit remain in `component-runs`; the corrected module invocation starts a new `component-runs-2` evidence directory with the same preregistered arms and limits. This is not a retry after a capacity failure; no measured component trial had started.
