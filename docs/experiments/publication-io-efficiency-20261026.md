# Publication I/O efficiency, 2026-10-26

Local implementation is complete on `codex/publication-io-efficiency-20261026`.
Runtime source is `7145114742d2915e6bf1757c86039e31e3254884`, based on pushed
main `0bfeb21e84b73a9637713a3673d61dc97beb53be`. This work has not been merged,
pushed, deployed or used for a production publication. Separate primary-checkout
changes were preserved.

## Changes and measured result

| Change | Concrete improvement | Check retained |
| --- | --- | --- |
| Bounded upload submission | Six workers and at most six submitted, unconsumed jobs; observed failure stops refill and cancels queued work. | Conditional requests, running-job drain, pointer publication only after successful transfers. |
| Concurrent journal restore | Six-event fetch window; workers stage and parse fetched bytes once; ordered validation retains file receipts instead of the raw prefix. | Complete sequence/nonce/digest/binding/transition/size validation before accepting history/state; workers join before spool cleanup. |
| Bounded acknowledgment groups | Up to six acknowledgments join the next intent/control record; byte pressure flushes a smaller group. | Each payload still has its individual durable pre-PUT intent. No uploader barrier or second mutation authority. |
| Retained Arrow reader | Details and facets use the already-loaded bounded Arrow source. Generated core-Parquet decoder passes fall from two to zero. | Real export/footer/schema checks, observation-count ownership, batch admission, exact typed values and output verification. |
| Current measurement tooling | Journal/payload/control request categories, request duration, journal lock wait/hold and restore duration; generated native fixture runner. | Offline in-memory service, real local writes/syncs, explicitly modeled request latency and pinned sources. |

Three baseline journal trials and two completed final grouped trials each used
1,000 one-byte payloads, six workers, real local evidence writes/fsyncs and modeled
1 ms SDK request latency. All original source and instrumentation hashes are in
[the retained receipts](publication-io-efficiency-20261026/summary.json).

| Per 1,000 payloads | Baseline trials | Grouped trials |
| --- | ---: | ---: |
| Payload PUTs | 1,000 | 1,000 |
| Journal PUTs / restore GETs | 1,669 | 1,002 |
| Raw journal bytes | 865,151 | 740,025–741,045 |
| Upload fsyncs | 1,677 | 1,008 |
| Restore fsyncs | 1,675 | 1,008 |
| Remote GET/PUT/HEAD added by acknowledged replay | 0 | 0 |

This is about **40% fewer journal requests** and **25% fewer combined payload and
journal PUTs** in these completed fixture trials. Scheduling affects baseline
coalescing, so these percentages are not fixed production promises. One later
sequential pair observed 1,549 baseline journal objects versus 1,002 grouped.

Concurrent restore alone reduced the earlier three-trial fixture median from
3.164 to 1.698 seconds. The final grouping trials ran under host contention;
wall-time comparisons there are not qualified. One additional sequential pair
observed upload 26.117 to 11.095 seconds and restore 12.754 to 4.447 seconds;
these are single observations under variable host conditions, not a stable
speedup estimate. Request and fsync counts are the stronger result. Small JSON
admission work increased with acknowledgment grouping; no CPU reduction is claimed.

RSS sampling was unavailable in the original scale trials. The later pair has
samples, but one pair does not qualify a memory comparison. Raw-prefix retention
is removed structurally; event keys, reconstructed state and small file receipts
still grow within existing count/byte ceilings. The interrupted third grouped
trial has no completed receipt and is not counted as a result.

## Recovery format and behavior

New remote journal records use explicit version 2 with a bounded `verified_writes`
array. The reader retains unchanged version 1 history, including its single joined
acknowledgment, and accepts a version 2 tail. Old version 1-only readers reject
version 2 rather than silently ignoring its acknowledgments. Continuation state
format remains version 1. Required producer hashes change, so a new accepted
preparation is required before publishing with this code.

A crash can lose up to six buffered acknowledgment facts in addition to any
in-flight uncertain requests. Their original individual intents remain durable;
recovery resolves uncertain outcomes without blindly resending payload PUTs.
Normally acknowledged/replayed payloads need no GET/HEAD readback. Public checks
remain bounded smoke checks.

Both records are count/byte admitted before a byte-pressure split flush and its
incoming event. Nonce-bound conditional creation still fences each sequence.
Malformed groups, duplicate/unknown acknowledgments, changed staging custody,
late corruption, fetch failures and local I/O failures refuse acceptance. Pending
facts and the chain position survive failed appends.

Restore staging writes each fetched raw event once. The worker parses the same
bytes and returns the parsed event plus a custody receipt. Only receipts remain
for the accepted prefix. New accepted evidence is synced and hardlinked after
full validation; existing equal evidence is checked by size/digest without
rereading the spool. Temporary staging is cleaned after success or handled failure.

## Verification and limits

- Reader/upload/harness integration at source `a117ae5f`: **213 passed, five real-native cases deselected, two subtests passed**. This covers exact Arrow/physical reader output parity and six-job submission/failure admission.
- Recovery/capacity integration at `a117ae5f`: **155 passed**, including the existing 100,000-upload interruption/replay and late-prefix corruption case.
- New grouped-journal owner checks: **127 passed**, followed by **15 passing grouping checks** after the final sequence-width sizing refinement.
- Final integrated grouped recovery/bounds checks at `71451147`: **115 passed, one expensive full-release fixture deselected**. The already-passed 100,000 restore was not repeated after grouping; mixed-version and group/crash behavior have dedicated focused tests and actual 1,000-payload fixture round trips.
- Independent subagent reviews approved the queue, Arrow reader, staged restore and final grouped format without another broad audit.

These counts overlap and are not additive unique test totals. The completed
command outputs were observed before a subsequent power outage. The outage
cleared their temporary logs; the pinned measurement receipts and source commits
survived in this worktree. All 17 receipt hashes and JSON bodies were verified
afterward. The final native fixture receipt records successful publication, an
unchanged poll, the expected injected failure and successful explicit resume,
with all three Parquet payloads byte-identical to the baseline. Successful
publication and acknowledged resume each made zero payload GET/HEAD requests.

The native fixture's three generated Parquet payloads remained byte-identical
between the baseline and retained-Arrow implementation. Detail-specific empty,
chunked/sliced, Unicode, null/empty-list and typed-field cases also compare exact
physical output bytes. The independent detail-output verification pass remains.
Metadata/proof identities change with the producer source, as required. The tiny
fixture demonstrates fewer decoder passes, not a qualified preparation speedup.

No full-catalog duration, live object-service latency, deployment or product
release qualification is claimed. No operational setting changed. Further
unmeasured local copy/hash and logical detail/facet traversal costs remain outside
this scoped implementation.

## Reproduce

The current native fixture uses the maintained measurement harness:

```sh
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python \
  scripts/measure/measure_native_publication.py \
  --checkout "$PWD" --output /tmp/publication-native-new --trials 3
```

The exact isolated journal reproduction script is
[journal_benchmark.py](publication-io-efficiency-20261026/journal_benchmark.py).
Run it in fresh output directories, with `--checkout` selecting the baseline or
candidate checkout and identical `--telemetry` pointing at the baseline's
`scripts/measure` directory. Use `--count 1000 --latency-ms 1`; it uses no remote
service. Receipts pin the source, telemetry, sampler and script hashes. Preserve
completed and interrupted outcomes separately.

Post-outage confirmation on unchanged runtime `71451147`: **54 passed in 2.32s**
across `test_journal_ack_groups.py`, `test_journal_restore.py`,
`test_filename_arrow_readers.py` and `test_measure_publication_fixture.py`.
The expensive completed scale checks were not rerun.
