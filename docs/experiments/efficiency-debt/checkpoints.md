# Smaller durable publication checkpoints

The normal success fixture, including accepted preparation, falls from **3.564 to 2.931 seconds median** over three fresh processes per arm (17.7%). Source downloads, requests and published payload values remain unchanged. Resume is measured separately; its overlapping ranges do not support a consistent speed claim. This is a local generated fixture with 1 ms modeled request latency; it establishes no full-catalog or hosted speed claim.

## Change and required behavior

`Continuation.flush` serializes one compact JSON value, checks its complete encoded size against the existing 32 MiB accepted-state limit, then writes, fsyncs, replaces and fsyncs the containing directory. It removes pretty-printing and many tiny Python stream writes. Oversize state now refuses before creating/replacing the temporary file. JSON fields, types, values and the normal reader remain unchanged.

`Continuation.record(publication_write_verified, ...)` now advances an existing protected version in the **same** checkpoint as the verified write facts. The cloud attempt's `after_write` callback no longer emits an extra checkpoint. Exact current readback still precedes the verified event. A crash before that checkpoint leaves the original intent/condition; explicit fresh-process reconciliation verifies the current full body before deriving its version. It neither repeats a committed PUT nor treats serialized verification as current proof.

Every write-ahead intent, complete readback, local journal-intent fsync, remote event PUT/readback, nonce/digest chain, event ordering and concurrent sequence fence remains. The change does not defer cloud state persistence. Accepted state remains 32 MiB; count limits, 16,384 events, 1 MiB events and 64 MiB history remain unchanged. Informational events remain valid. The local dispatcher still has its distinct duplicated event/checkpoint work until `ct-2ut4`.

## Matched evidence

Baseline production is `6855f37ba98acec4b113f211650c0cee62319cec`; candidate production is `5ef925157e7d3990526855ca51b058d92d050d38`. The final report commit only adds documentation/evidence and ticket notes after that measured implementation commit.

The maintained tiny fixture has seven sources and six groups. Both arms run its real preparation/publisher with the existing in-memory remote/custody adapters. Before execution, the proposal declares a 1 MiB source ceiling, 2 GiB sampled RSS ceiling, 120 seconds per arm, 1 GiB scratch ceiling, three repeats and identical 1 ms per-request delay. No network, acquisition or classifier runs.

The measurement counter recognizes state serialization through either `json.dump` or `json.dumps`. Because that counter changed with the implementation, the original baseline diagnostic trials are excluded from the accepted comparison. Replacement baseline trials use a dedicated managed worktree at the exact old production revision, with **only** the new non-runtime telemetry helper copied in. A common locked interpreter and third-party dependencies use explicit source paths for that baseline; saved import probes confirm both publication modules come from it. No environment symlink, primary source/environment modification or other active worktree cleanup occurs.

The strict existing `compare_publication_costs.py` gate accepts all shared inputs, runtime/executable, four instrumentation hashes, revision consistency and exact output comparisons for all three pairs. Each pair preserves all 269 payload files, stable-ID shards, review binding and prepared/published recovery values under the gate's documented source-identity normalization. The toy fixture withdraws all 86 production review identities as missing; it does not establish their real-catalog binding. The separate Catalog experiment covers bound/withdrawn review cases.

| Normal publication, after preparation | Before | After |
| --- | ---: | ---: |
| Median seconds | 3.047 | 2.426 |
| State serialization calls | 548 | 547 |
| State serialized characters, median | 61,665,612 | 53,492,225 |
| State serialization seconds, median | 0.566 | 0.142 |
| fsync calls | 2,193 | 2,191 |
| GET / PUT / HEAD requests | 833 / 821 / 270 | 833 / 821 / 270 |
| Remote body read / PUT body bytes | 319,614 / 315,587 | 319,614 / 315,587 |
| Stage-end scratch bytes | 769,461 | 745,769 |

Including preparation, downloads remain exactly 56,476 bytes in two requests; fsync calls are 2,201 → 2,199; state serializations are 550 → 549; state characters are 61,714,864 → 53,535,654. The observed CPU improvement comes mainly from compact whole-value encoding, not removal of durability work. Request counts and transfer bytes do not improve. State still grows with the required retained write facts and still checkpoints per event.

Explicit successful resume uses two state serializations, seven fsync calls, 834 GETs, one PUT and 543 HEADs in both arms. Its matched medians are 1.729 → 1.644 seconds, with overlapping ranges of 1.715–1.730 and 1.570–1.735 seconds; no consistent resume speed claim follows. Compact state lowers its serialized characters from 350,690 to 303,306. The failed explicit-resume probe also retains its separate failure outcome and original evidence.

## Verification, limits and replay

Existing state, attempt and continuation checks: **60 passed**. New checkpoint/fault/admission tests, state bounds and cost-comparison checks: **74 passed**. The new tests verify one checkpoint owns protected-version advancement, interruption after committed readback but before checkpoint replacement resumes without a second PUT, Unicode/empty values survive compact JSON, both file/directory fsyncs remain and oversize admission leaves accepted state intact. Existing tests cover runner loss, lost acknowledgment, competing append, missing/invalid history, original conditions, stale inputs, changed runtime and changed file custody.

Compact encoding temporarily holds a JSON string and encoded byte buffer alongside state; the 32 MiB file-admission limit is **not a total process/native allocation budget**. The matched complete-success maximum sampled RSS is 126,386,176 → 123,322,368 bytes; this small fixture is not a large-state memory qualification. No Linux, production allocation, deployed-publication or total resource claim follows.

[Compact comparison evidence](checkpoint-evidence.json) records the exact revision/source/helper pins, all before/after stages and raw receipt hashes. Full raw receipts, original excluded diagnostic trials, baseline import probe, proposal, watchdogs and strict comparison remain in primary `output/efficiency-debt-20261019/checkpoint/`. The dedicated baseline worktree remains available for independent review; root owns its later managed archive. Independent review accepted the result after verifying all nine retained cost receipts, shared instrumentation and runtime, three recalculated normal-path medians and all 269 actual payload hashes in each arm.
