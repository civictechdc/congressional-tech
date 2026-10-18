# Process-efficiency implementation receipt

The authorized A–F implementation and small operator command live on the local
`codex/process-efficiency` branch in
`/Users/mikewolfd/.codex/worktrees/process-efficiency/congressional-tech`, based on
`24137dd08241c34f1632afcd78a80a6138e5779d`. Implementation, bounded measurements
and final combined verification are complete. No changes have been pushed,
deployed, merged or used to dispatch a production workflow.

The execution plan is the original `output/process-audit-20261018/IMPLEMENTATION.txt`
in the primary checkout, SHA256
`88488f0c9da51b56008b54d8485383318119958ba2d1cee7c1fd53a6e1c195a7`.
Its `AUDIT.txt` decision basis has SHA256
`53cde7371d5da4c8e5f67c4f0a9325926be27d3e1788e9c34aaa8d7dca7bec46`.

## Delivered behavior

| Unit | Practical result | Evidence and limits |
| --- | --- | --- |
| A: environment and test lanes | One six-member locked Python workspace, exact Python patch pin, checkout-local imports, prerequisite doctor, complete test inventory and explicit native/research lanes | [Environment validation](environment-validation.md); frozen capture workflow, parser hashes and research applicability remain unchanged |
| B: unchanged recovery mapping | Matching polls verify small identities/status and make zero table reads or writes; edits, deletion and whole-object absence invalidate reuse | [No-op tests](recovery-noop.md); full revision intentionally causes conservative cache misses |
| C: viewer preparation | Immutable compression policy, default Zstandard 9/version 10, exact data checks, complete-builder measurement and real browser range/CORS harness | [Compression decision](compression-plan.md); user authorized the default after bounded research; full Linux trial failed capacity and remains unqualified |
| D: source context | One sorted observation pass builds aggregate fields and occurrences, with a narrow link predicate | [Context comparison](../process-efficiency-d/report.md); direct integrated measurements favor keeping this simpler route |
| E: accepted preparation and restart | All output hashes including 256 ID shards are accepted before public writes; manual restart restores exact preparation and reconciles a durable conditional journal | [Restart validation](durable-publication.md); mock-store tests establish invariants, not hosted artifact/R2 latency |
| F: catalog file I/O | Selected and prior catalog tables stay in owned, verified files through consumption, archival and conditional publication | [File-backed comparison](../process-efficiency-f/report.md); selected-table loading uses less peak memory at a measured disk/time cost |
| Operator status | Read-only run, heartbeat and accepted-output reporting, with identity/expiry checks and no automatic resume | Independent status commit and tests; successful child exit does not imply public readback |

## Aggregate performance assessment

These changes affect different frequencies and portions of the work. Recurring
unchanged polls, a full changed-catalog publication, and an explicit failed-run
resume must be accounted for separately. Their percentages cannot be added.

The independent [architecture review](architecture-review.md) grades the resulting
local implementation **B overall**, versus B- originally. Correctness and
recoverability improve to A-, and developer reproducibility to A-. Algorithms and
data movement remain B-: repeated no-op work and complete compressed allocations
are reduced, but the full rebuild still traverses large nested state. The grade
reflects measured tradeoffs and remaining operational evidence, not the count of
features or passing tests.

The no-op eliminates table-sized repeated reads: the prior published viewer's
filenames and groups totaled 365,992,473 bytes per unchanged poll. Those viewer
files are distinct from the 1.083 GB raw selected catalog pair used for F. The audit figure is
not a measurement of new production traffic. The new tests assert zero table bytes
and zero writes for present, empty and absent accepted mappings.

The prior compression research measured level 9 repack plus exact equality at
0.0885 versus 0.5217 seconds for documents, and 0.0907 versus 0.5136 seconds for
filenames. Outputs grew 8.38% and 7.47%. Those are small selected, single-row-group
samples on macOS, not complete-publication gains. The source receipt is preserved
in [prior compression research](evidence/prior-compression-research.json). The new
multiple-row-group tests and 180 browser samples add correctness and harness
coverage; they do not turn this into complete-catalog performance qualification.

The initial one-pass context comparison measured 19.0970 to 18.3345 seconds for a
complete fixture rebuild (4.0%) and 2.0499 to 1.8194 seconds for association (11.2%).
Maximum sampled memory was essentially unchanged. The earlier cache comparison
used a different contemporaneous baseline, so its 9.8% whole-run improvement cannot
be subtracted from or added to the one-pass result.

The direct comparison on the final file-backed route measured medians of 14.1284
seconds without the cache and 13.6663 seconds with it: 3.27% less time. Paired gains
varied from 1.64% to 7.10%, and timing ranges were separated by only 0.0178 seconds.
Maximum sampled memory grew 0.25%. The retained candidate's 1 MiB budget bounds
stored entries, while oversized `pickle.dumps` can transiently allocate more.
The decision is to keep one pass: this modest variable whole-run benefit does not
justify added finalization, eviction and serialization safeguards here. This is an
aggregate runtime, memory and maintenance judgment, superseding the original
isolated percentage gate. The candidate and exact evidence remain available.

The file-backed route's small whole-rebuild fixture medians were 14.370 seconds
before and 14.133 seconds after, with overlapping ranges; no speed gain is claimed.
Maximum sampled memory rose from 370.36 to 384.33 MB, and scratch from about 64.52
to 65.03 MB. The separately measured 1.083 GB selected-pair read component shows
the intended allocation saving: peak memory fell from 1,875,550,208 to 878,702,592
bytes (53.15%), while median read time rose from 2.65244 to 4.58054 seconds (72.69%).
The file route used 1,083,172,637 bytes of scratch. This trades file I/O and space
for lower compressed-input memory; it is not a measured 53% whole-rebuild saving.

Accepted preparation saves rebuilding on explicit retry. The final mock fixture
made zero builder calls and zero repeated release-payload writes on resume.
Restore plus retry including journal work took 1.172 seconds locally. Success has
an explicit cost: 273 public writes required 548 serialized journal writes and
548 complete journal readbacks, plus one initial absence check. Their 236,828 bytes
are small; remote round trips may dominate. Hosted artifact transfer, journal
waiting and public verification need a representative delivery measurement.

## Verification and remaining limits

The first combined offline run passed 8,816 tests but failed 22 capture-verification
cases during fixture setup/use: that injected store lacked the new file-read
operation. The adapter correction passed all 23 focused cases. The same run exposed
two native capacity cases that lacked the `loopback` marker and therefore skipped
instead of joining the native lane. They are now enrolled explicitly.

The second combined run passed 8,837 tests and failed the historical workflow
coverage assertion, which required every future native file to appear in the frozen
capture workflow. The corrected assertion preserves its seven original native files
and checks that all current marked cases are covered by the maintained native lane
and its actual CI command. The frozen workflow itself remains unchanged. The
combined workflow/setup/capture-verification checks passed 76 cases in 3.30 seconds.
Both failed full runs remain under `output/process-efficiency/verification/attempt-1`
and `attempt-2`, with compressed copies in the committed evidence below.

All ten final verification commands passed against code revision
`5b128da7c432cde64893fce10c9a167d40a5d616`. The subsequent completion commit
contains documentation and retained evidence only.

| Final check | Result | Total command time |
| --- | --- | --- |
| Production offline | 8,838 passed, 49 deselected, 38 subtests passed, zero skips | 193.04 s |
| Active experiment regression | 241 passed, zero skips | 8.07 s |
| Native loopback | 49 passed, 3,983 deselected, zero skips | 69.15 s |
| Explorer | 113 passed, zero skips | 2.18 s |
| Explorer generated types | Passed | 0.52 s |
| Astro check | 53 files; zero errors, warnings or hints | 4.82 s |
| Viewer data | 7 passed, zero skips | 0.33 s |
| Static site build | 29 pages built | 2.50 s |

The dependency install and runtime inventory commands also passed. Exact commands,
wall times, runtime identities and log hashes are in the
[final verification receipt](evidence/final-verification/receipt.json). That directory
retains compressed copies of the runner, successful logs, both failed runs and
focused corrections; the uncompressed originals remain under
`output/process-efficiency/verification`.

The final macOS run used Python 3.12.13, PyArrow 25.0.1, Poppler 26.06.0,
Node 26.9.0 and npm 11.19.1. The maintained CI configuration uses Node 22;
these local checks do not establish a hosted Node 22 result. The native binary
was built offline in release mode with Rust 1.89.0, at
`packages/source-fetch/target/release/source-fetch`, SHA256
`1d66d0b443b020fb469903f3b810eee1917217e558a9beececde28f1031cabd8`.
The complete Linux native lane, including Rust transport, remains unqualified.

The static build verified the existing local review bundle against
`apps/site/document-review-publication.json`, then staged it through a temporary
symlink. Its source was the primary checkout's ignored
`output/filename-patterns-20261015/review-rebind-v2/public` directory. The verified
staging symlink was removed after the build; source assets and generated `dist`
remain intact. No new review or document acquisition was needed.

Final byte comparisons confirm the capture workflow and `document_cover.py`
still match the base revision. Their exact hashes are in the verification receipt;
earlier frozen-source checks also verified all nine research source hashes.

The full viewer baseline was killed by the Linux container's memory limit after
10.053 seconds before a publication file was written. Input size and hashes were
verified. The last durable completed operation was supervisor input verification;
the exact active worker stage cannot be recovered. Future attempts now flush
stage-start/completion events. No further full-catalog compression run is required
by the user's revised decision, and F does not establish a fix for that viewer
failure. The host's shared daemon and unrelated services were left unchanged.

No frozen held-out classification, new document acquisition, production writes,
workflow dispatch or live publication occurred. The parent task separately uses
read-only authenticated status monitoring for the already-running production rebuild.
Fixture, native macOS, bounded Linux and hosted
production evidence remain separate. The next authorized operational decision is
reviewing these local commits; rollout is outside this task.

## Local commits

- `320ffc1`: unchanged recovery mappings.
- `e6f27a7`: shared Python environment and explicit lanes.
- `3d6718f`: read-only operator status.
- `74327ed`: one-pass source context.
- `8bda52a`: ordered-row and required-metadata comparison.
- `5afecfc`: accepted preparation and durable publication journal.
- `f3ac7d4`: remove redundant guards and repeated resume downloads.
- `801b808`: Zstandard 9 and complete preparation/browser harness.
- `ea32cad`: exact Python patch pin and qualified native fixture budget.
- `0bac190`: independent aggregate architecture review.
- `0e867b4`: file-backed catalog I/O, consumer migration and direct measurements.
- `18162e9`: clarify component evidence and viewer failure limits.
- `9876d2a`: migrate the capture-verification test store.
- `32551b4`: enroll both native capacity cases.
- `5b128da`: verify native coverage through the maintained lane.

The final evidence commit contains this receipt and compact verification records.
