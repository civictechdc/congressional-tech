# Fewer remote publication journal requests

The maintained tiny publication removes **109 journal PUT/full-readback pairs** with the real six-worker uploader: normal publication changes from **833 GET / 821 PUT / 270 HEAD** to **724 / 712 / 270**. That is 13.3% fewer PUT requests. All 269 published payload files remain byte-identical, with complete prepared/published recovery parity and the same review binding. No payload readback or version HEAD was removed.

`DurableJournal` owns one pending verified-write fact. It checkpoints that fact locally immediately, then includes it in the next existing journal record. Intent records still receive conditional creation and full journal readback before the payload mutation. Completion and failure records carry the final pending fact. Consecutive transfer completions persist the older fact separately, so there is one pending slot even with parallel uploads. Restore validates the embedded fact before the enclosing event and before any local checkpoint. Existing standalone records remain supported retained history; no second publication mode or generic batching interface was added. The guarded client, attempt dispatcher and payload verification remain unchanged.

A runner lost before that next append leaves the original remote intent. Explicit continuation reads the complete payload, reconciles its exact bytes and derives its current version, as it already does for a crash between payload readback and verification persistence. Persisted verification facts still require their exact recorded version. Failed combined appends retain the pending fact and sequence; nonce-bound payloads and conditional sequence creation still fence competing runners. This extends the existing uncertain-intent interval until the next append; it does not delay any pre-mutation intent or allow a blind retry.

| Normal publication | Before | After |
| --- | ---: | ---: |
| GET / PUT / HEAD | 833 / 821 / 270 | 724 / 712 / 270 |
| Remote body bytes read | 319,614 | 300,311 |
| PUT body bytes | 315,587 | 296,284 |
| fsync calls | 2,191 | 1,973 |
| Local state serializations | 547 | 547 |
| Seconds, one trial | 2.558 | 2.154 |

Preparation still downloads 56,476 bytes in two requests. Successful explicit continuation changes from 834 to 725 GETs because its accepted journal is shorter; it retains one PUT and 543 HEADs. Parallel completion order determines how many facts can join the next intent, so the 109-pair reduction is this observed run, not a fixed count promised for every schedule. One timing sample per arm supports no stable speed or hosted performance claim.

The baseline is `ccd6c3607930f97e8c05593937ec0dc9ca49fb6c` (production source equivalent to `3b87599`); the measured implementation is `2672fe9480769ba7d0847534720b6185cb444153`. Baseline exact-source focused tests pass **74** checks. Candidate checks pass **87**: 51 unit/fault checks and 36 attempt integration checks. Coverage includes original conditions, payload verification, runner loss, the pending-fact crash interval, lost acknowledgment of a combined intent, consecutive completions, malformed embedded verification, changed exact versions, pre-mutation byte admission, competing sequence creation and stale input guards. The old restore checkpoint test now appends completion before asserting that remote history contains its final verification.

The matched generated source contains seven sources and six groups. It withdraws all 86 production review identities as missing; this is not full-catalog review qualification. The isolated interpreter uses locked offline dependencies. Both arms use the unchanged maintained `measure_publication_control.py` and strict `compare_publication_costs.py` gate, the same fixture pin, executable and telemetry hashes, and a fresh process per arm, with the source-identity cache reset at each timed command boundary. A 120-second subprocess timeout bounds each measured arm; observed sampled resident memory stays below 130 MB and scratch below 1 MB. Sampled memory is observation, not a hard allocation limit. No acquisition, remote service writes, browser, workflow, full catalog or CI gate ran.

[Compact evidence](remote-evidence.json) pins source identities, telemetry, all measured stages, test totals and raw receipt hashes. Full receipts, generated input, accepted output files and proposal remain in `output/efficiency-round-two-20261019/remote/` in the primary checkout. The existing measurement command accepts `--checkout`, `--source`, `--output`, `--source-manifest-sha256` and `--request-latency-ms 1`; comparison accepts the two receipt directories through `--before` and `--after`.
