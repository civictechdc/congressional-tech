# Bounded recovery startup (ct-tdsx)

Present recovery status now admits at most **32 MiB of decoded JSON** and has a
**30-second recovery startup deadline**. Missing status remains valid. Any
present status that is oversized, hung, corrupt, or bound to another catalog
rejects initialization; no baseline-only fallback is introduced.

The decision uses retained evidence, without source acquisition or hosted
qualification. Four still-retained sidecars range from 6,721,144 to 12,610,490
bytes; the earlier session inventory of eight sidecars had the same maximum.
The ceiling permits 2.66 times that maximum. Retained initialization checks passed
but do not establish a recovery latency percentile. Thirty seconds is an explicit
availability policy (about 1.07 MiB/s at the ceiling), allowing twice the existing
optional-review deadline. Larger future publications require an explicit policy
review. The deadline starts when recovery loading begins, after manifest lookup.

## Shared transport and preserved behavior

`filename-startup.mjs` owns byte admission, streaming, digest verification,
interruptible waits and cleanup for both status loaders. Recovery retains its
mandatory rejection behavior; optional reviews retain their 16 MiB per-input /
15-second total policy and their empty maps plus `review_error` on failure.
The review binding and publication share one deadline. Each caller retains its
own catalog, classification and position validation.

Descriptor length and SHA-256 bind decoded bytes. An identity response's visible
`Content-Length` can reject an inconsistent response early. Encoded responses and
CORS responses use the actual decoded count and digest because their length
header can describe compressed transfer bytes or hide encoding information.
No byte-prefix or partially verified recovery result is accepted.

Reads stop at the first chunk that exceeds the descriptor count. Timeout or
caller cancellation aborts transport, requests cancellation and releases the
reader without awaiting an uncooperative cancellation promise. A fetch that
ignores abort still settles its caller; a late response receives cancellation.
Each async wait removes its abort listener instead of accumulating one pending
race handler per chunk. A monotonic elapsed-time check also catches synchronous
validation exceeding the deadline once control returns.

## Bounded comparison

Baseline: `3757f55ed33ea390895c20a2007cb08eb39ce519`. One synthetic comparison
uses a 207-byte valid status, a 4 MiB overrun delivered in 64 KiB chunks, a
32 MiB+1 descriptor and a stalled stream. Results count decoded bytes delivered
to JavaScript, not encoded network traffic.

| Case | Before | After |
| --- | --- | --- |
| Valid / absent status | Complete verified maps / empty maps | Identical result hashes; same 207 / 0 bytes |
| Stream overrun | Reads 4,194,304 bytes across 64 chunks, then rejects | Reads 65,536 bytes once, cancels and rejects: 98.44% fewer delivered bytes |
| Inadmissible descriptor | Fetches and reads 4,194,304 bytes, then rejects | Rejects before fetch: zero delivered bytes |
| Stalled read | Still pending at the fixture's 75 ms observation ceiling | Rejects at about 16 ms under a 15 ms test deadline; aborts and cancels |

These are work-count and deadline results, not a production latency or heap
benchmark. Native Fetch decompression/chunk buffering and the final parsed maps
remain outside the byte-buffer bound. A single already-delivered chunk can be
larger than the expected count; the loader does not copy it into its admitted
buffer. Cleanup requests cannot force a broken transport implementation to release
its own internal resources.

Twenty focused loader/worker checks pass, including encoded/CORS inputs,
ignored abort, late response, hung cancellation, streamed overrun, absence,
invalid descriptor, malformed JSON, corrupt digest/catalog/positions, caller
cancellation and optional review failure. The real worker returns an initialization
error for corrupt recovery. The existing recovery-corruption regression also
passes unmodified. No catalog/search source was changed.

Evidence is retained under
`output/efficiency-debt-20261019/recovery/`: `policy-evidence.json`,
`comparison.json`, the exact baseline loader and reproducible `compare.mjs`,
`tests.log`, and `existing-recovery-regression.log`. Dependencies are pinned
Hyparquet 1.31.2 / compressors 1.1.2 installed offline inside this worktree.
Ticket remains in progress pending independent review. No publication or push.
