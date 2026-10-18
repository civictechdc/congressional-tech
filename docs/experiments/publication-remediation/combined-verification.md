# Combined publication verification

The original 42 remediation tickets are implemented and locally verified. Repeat
operations improved on the retained fixture; fresh publication became slightly
slower. This evidence does not claim full-catalog or deployed-job performance.
Hosted unchanged-job qualification remains open in **ct-x7vx**; the parent epic
stays open until that observation exists.

## Comparable measurements

Three alternating before/after trials used the same retained seven-filename,
six-document fixture, exact runtime, instrumentation and 1 ms modeled latency per
private adapter request. Baseline: `f9f4499beceb405e614bc18cad41a2bb1134a845`.
Candidate: `f5257491a88b1cd19082d33d91426578d8e2cf4d`. The baseline already includes
the earlier compression-level change; this comparison does not measure that change.

Each arm runs in a fresh process. Each command starts with a cold source-identity
cache; interpreter/import startup is excluded. Commands within an arm share that
process, so memory observations include retained allocations. The complete success
time is the median of each trial's preparation-plus-publication sum, not the sum
of stage medians. The critical path remains preparation followed by publication.

| Operation | Median seconds, before → after | Time change | Modeled requests | Modeled transfer bytes | Maximum sampled process-tree RSS, MiB | Maximum stage-end scratch, bytes |
| --- | --- | --- | --- | --- | --- | --- |
| Fresh publication, including preparation | 3.388 → 3.642 | +7.5% | 1,929 → 1,929 | 667,178 → 668,595 | 120.73 → 117.34 | 758,896 → 757,379 |
| Unchanged poll | 0.207 → 0.098 | -52.6% | 11 → 8 | 10,560 → 9,065 | 118.47 → 117.12 | 758,896 → 757,379 |
| Deliberately failed resume | 2.810 → 1.668 | -40.6% | 1,369 → 1,369 | 306,462 → 307,263 | 119.06 → 118.00 | 759,426 → 757,909 |
| Explicit resume | 2.701 → 1.664 | -38.4% | 1,378 → 1,378 | 311,129 → 312,546 | 119.17 → 118.08 | 760,136 → 758,619 |

Fresh publication ranges were 3.356–3.485 s before and 3.624–3.732 s after.
Preparation rose from 0.317 to 0.545 s; publication itself was essentially unchanged
at 3.081 versus 3.079 s. Preparation now includes broader release-source identity,
streamed admission and spill work. The measurement establishes the combined cost;
it does not isolate each change's contribution. The durable publication path still
performs 1,929 modeled requests and 2,199 fsync calls across preparation/publication.
Further fresh-publication gains require profiling and reducing that durability
work while preserving crash recovery and conditional selection.

Resume state serialization fell from 96,523,320 to 350,198 characters, and fsyncs
fell from 1,097 to 7. Complete remote reconciliation remains: total resume request
count stayed 1,378. Unchanged polls use 8 private GETs instead of 11, with zero
publication writes, table downloads or decode passes. New source identity hashes
more implementation bytes; fewer hash calls alone are not a claim of less I/O.

For an illustrative workload, each fresh publication adds about 0.254 s, each
unchanged poll saves 0.109 s, and each explicit resume saves 1.037 s. Three unchanged
polls offset the extra time of one fresh publication in this fixture. Actual gains
depend on workload frequency and scale; percentages from separate optimizations
are never added.

## Correctness and evidence

All **269 publication payloads per trial** matched: full file SHA256/size checks,
complete ordered Parquet values and schemas, exact sidecars, all 256 ID shards,
reader-visible metadata, review binding and source identities. All payloads were
also byte-identical on this fixture. Captured actual published recovery bytes
matched across all pairs: 123 bytes, SHA256
`d0a71ed2cd9cfd4532f61cc3a42d8eef6b4cd4687227d7fd44eaa3f6b271f27e`.
The candidate's prepared recovery matches those bytes and its exact manifest and
accepted-source inputs. The baseline predates prepared-recovery retention, so that
absence is explicit; candidates cannot waive preparation verification.

The synthetic fixture binds zero reviews and withdraws all 86 with recorded reason
`document_missing`, identically before and after. These counts are distinct from
the live rebuilt catalog, which has 86 bound and zero withdrawn reviews. No review
was reinstated by this work.

Raw trials, selected controls, source fixture, journals and failure evidence remain
under `output/publication-remediation-20261018/combined/` in the primary checkout.
The six cost receipts and comparison are retained in this directory's `evidence/`.
The first comparison refused the baseline's absent internal recovery file; those
trials were preserved and both arms rerun with identical capture instrumentation.
An earlier runtime-evidence lookup stopped before timing because optional DuckDB
was absent; absence is now recorded explicitly without installing packages.

Limits: 50 ms RSS samples can miss peaks; scratch is sampled at stage completion,
not continuously. Modeled transfer bytes count private response bodies, downloads
and PUT payloads, excluding headers, public HTTP, artifact APIs, native Arrow I/O,
internal hashes, CI setup and interpreter startup. Requests use local test adapters,
not cloud traffic. Three small trials are not statistical or full-catalog qualification.
The earlier full Linux OOM remains unresolved; no retry or resource change occurred.
The separate bounded-memory receipt documents native single-row allocation limits
and the measured memory/time tradeoffs.

## Validation and review

- Corrected production-offline suite: **9,072 passed, 38 subtests passed, 50 deselected**.
  The declared offline profile excludes native loopback tests; the affected local
  HTTP route also passed separately. Preserved the initial four failures and fixes.
- Final integrated JavaScript suite: **152 passed**. Site build: **29 pages**;
  emitted bootstrap smoke checks: **2 passed**, using Node 22.22.2.
- Final comparison evidence tests: **54 passed**, including changed values, metadata,
  source/runtime pins, recovery, failure identity, bounds and candidate-waiver refusal.
  These overlap the full suite and are not added to its count.
- Independent lane reviews covered implementation and failure paths. Final review
  found mutable verification metadata leaking into benchmark byte snapshots; root
  fixed that boundary and verified real byte changes still fail. The original
  offline localhost marker and two earlier-failure assertions were corrected.
- Independent final comparison review approved actual selected-byte capture outside
  timing. Its candidate-capability finding was fixed with a regression test. That
  postprocessing-only guard does not change the measured candidate revision.

Full logs, exact runtime/package pins, source hashes, built site and raw evidence
are preserved locally. No new audit grade or exhaustive regrade is claimed.
No remediation deployment, push, workflow dispatch, retry, held-out classification
or source-document acquisition occurred. The original rebuild and its automatic
publisher completed separately and passed live verification.
