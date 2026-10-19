# Visible current-body reconciliation (ct-5jqd)

Explicit reconciliation now reports which object it is reading, bytes read versus
the declared length, checked-object count, outcome, and the exact next check.
`Continuation.reconcile()` replaces one bounded local
`reconciliation-progress.json` observation throughout the scan. The local and
cloud invocation paths both use this maintained method; no dispatcher or attempt
ownership changes are needed.

Success still requires the complete current body, matching byte count and SHA256,
and the existing ETag and original-condition checks. An object's `reconciled`
observation follows those checks and creation of the fresh client-bound proof.
The scan's `complete` observation follows the existing state checkpoint. Missing
and unchanged-original objects remain `uncommitted`; changed bytes or verified
versions remain `conflict`. Read and checkpoint failures remain failures.

Progress carries input-binding SHA256, scan ID, and timestamp. It explicitly says
observation only, no current readback proof, no resume authorization, and public
readback not checked. The status reader validates the binding and shows the last
recorded observation and timestamp without writing files. Missing, foreign, or
invalid progress cannot grant acceptance. A producer can stop after any update,
so its last observation may be stale. Resume and replay never read this file.
Serialized verification and completed progress never replace fresh-client proof
or the existing full-read fallback.

## Bounded cost and tradeoff

At most 32 periodic byte updates are emitted per object, plus initial/final read
counts and object start/outcome: at most 36 observations per object, plus scan
start and completion. The producer retains one latest file, capped at 16 KiB,
and replaces it atomically without `fsync`. It adds no durable journal records,
remote requests, retries, or automatic writes to published objects. Observation
failures cannot replace the original read/checkpoint result or exception. Fixed
messages avoid copying transport exception text or credentials into diagnostics.

Baseline: `1e572d028a53ee104c31a4ba4eeded530e34ec51`. Candidate:
`8219e1863bfce5b3acd4037415ae77844df3e2ac`, clean tracked files. The measurement
loads the exact baseline continuation source from Git. Both arms use the standard
`Continuation` checkpoint; the local subclass inherits this same read/observation
method, while its authority-snapshot cost is measured separately in ct-2ut4.
Both arms use identical
instrumentation, interpreter, three mock-store objects, and generated bodies:
a committed requested body, an unchanged original object, and an absent object.
The declared limits were three paired repeats, 120 seconds per arm, 64 MiB
scratch, and 256 MiB sampled process-tree resident memory. No network, acquisition,
real catalog, or public publication runs occurred.

| Local scan work | Baseline | Candidate |
| --- | ---: | ---: |
| Current GET requests | 3 | 3 |
| Body read calls | 9 | 9 |
| Full current body bytes | 7,340,028 | 7,340,028 |
| Durable sync calls | 2 | 2 |
| Published-object PUT requests | 0 | 0 |
| Latest-observation replacements | 0 | 17 |
| All serialized JSON characters | 704 | 10,264 |
| Final retained observation bytes | 0 | 565 |
| Median elapsed seconds | 0.060483 | 0.062430 |

All six runs produce identical complete authority state, proof values, remote
request counts, and body read counts/bytes. Each proof remains tied to the actual
client object. Final scratch grows from 705 to 1,270 bytes. Maximum sampled
resident memory is 62,504,960 bytes; this supports no memory improvement claim.
Elapsed ranges were 0.058305–0.061326 seconds before and 0.061159–0.062823 seconds
after. This feature buys bounded visibility with additional local observation
work; it is not a speed optimization. These short synthetic timings do not
predict production overhead or establish a complete process memory budget.

## Verification

The complete publication package and affected dispatcher/status checks passed:
**185 passed, 7 subtests passed in 31.91s**. Focused cases verify partial and
failed reads, invalid length metadata, same committed/uncommitted/conflicting
outcomes, failure and completion ordering, fresh-client proof, full-read fallback,
observer/file failure isolation, input-bound read-only status, and the update cap
even when the declared length is wrong. A 64 MiB generated streaming case produces
1 MiB per read without retaining the complete body and emits no more than 34
read updates.

Exact source hashes, body pins, normalized outcome digest, command, and raw file
hashes are retained in [the receipt](reconciliation-evidence.json). Raw evidence
is under `output/efficiency-debt-20261019/reconciliation/run-final/` and its parent
focused test log. This proves local observation behavior only; remote delivery
of progress, cloud artifact custody, and current production qualification are
outside this run. The ticket remains in progress pending independent review.
