---
id: ct-l47f
status: closed
deps: []
links: [ct-6v77]
created: 2026-11-14T14:24:24Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-cbkz
tags: [perf, lake, memory, append]
---
# Keep incoming text off native append hash build side

The pinned native append plan builds incoming payload columns for LEFT ANTI JOIN. A right anti-join builds only existing keys and streams incoming rows. This affects bounded adoption of about 12 GB decoded markup, without changing the append API or acquiring source data.

## Design

Swap the join direction in lake.tables.append_rows after native plan confirmation. Preserve null-safe work keys, old values, guarded native retries, source and writer identity, and empty/no-op behavior. Measure a bounded local payload comparison and separately test the 310k-key identity aggregation.

## Acceptance Criteria

Exact local native overlap/null/empty/rerun and conflict checks; unchanged binary-key behavior; physical plan builds only existing key columns; fixed-input measured payload comparison under unchanged 6 GiB watchdog admission; independent reviewed commit. Whole-generation adoption remains in ct-cbkz and must account for identity aggregation separately.


## Notes

**2026-11-14T14:27:33Z**

Confirmed on pinned native engine 4c4a94c8 with a real local native table pin: baseline LEFT ANTI is CollectLeft with incoming projection [key,text]; candidate RIGHT ANTI is CollectLeft with existing projection [key] and incoming text on the right probe side. Both plans retain NullsEqual:true. Evidence: repairs/ct-narrow-append-20261114/plan-probe/{baseline,candidate}.json under the durable OCR recovery root.

Minimal implementation changes only join direction and its explanation, leaving identity_sql, layout, native retry binding and source/writer hash construction intact. Because writer identity hashes tables.py bytes, this code revision intentionally obtains its own writer fingerprint; identities remain source/definition/engine/layout/key bound. 19 focused native tests passed (partial production-offline, 2/555 files), including exact old-value preservation, nullable work-key matching, binary compound keys, empty input and unchanged rerun. Measured 0.52 GiB RSS under 6 GiB admission. Full append payload comparison, key-identity scale and independent repaired-commit review remain in progress.

**2026-11-14T14:44:25Z**

Narrow implementation accepted at exact code commit aa449247d6f36ca414a2f4870813d63ec893b8bd. Independent reviewer /root/shared_reader_ci_finish approves all five changed files and its own native mixed binary/nullable-key consumer probe; certificate repairs/ct-narrow-append-20261114/independent-review/review.md (SHA1421cc424c5db1ddb06712ce518d0e6b869726702dacd473706e33a285a7dd82).

Full actual append comparison: identical2049-row/140,593,042-byte synthetic input, exact old-value preservation,2048new rows; native pool still reserved at pending-retain completion148,194,591 ->41,146bytes with identical140,771,478decoded pending bytes. Both pending relations spill to scratch. Whole-process RSS/speed savings are NOT established: baseline0.186GiB/0.237s versus candidate0.553GiB/0.313s are preserved. The correction removes the wide hash build, not every append allocation.

Separate310,963-key actual append passed45,711,561bytes of ordered identity strings at0.442GiB full-process peak. Simultaneous appends produced retries[0,1],2048new rows exactly once,2049distinct final keys, old overlapping value preserved and fresh native no-op;0.72GiB peak.19focused native tests and the separate body-text interrupted-commit consumer test passed (partial production-offline runs, not a full-lane claim). No API, extraction version, production catalog, source payload, OCR, selected text or publication change.

Final detailed evidence and preserved harness refusals: repairs/ct-narrow-append-20261114/RESULTS.md and handoff.json under the main durable OCR recovery root. Source/payload/identity/writer traces are explicit. Corpus owner's actual existing-key probes passed separately; proposed first adoption chunks are at most64MiB decoded Arrow and65,536keys, but combined actual-baseline/payload/pending/writer capacity remains for ct-cbkz's separately authorized first chunk. No12GB whole-generation admission is claimed. Closing only this independently reviewed causal fix; root owns integration/CI/push/merge and parent adoption.
