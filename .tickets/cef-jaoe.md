---
id: cef-jaoe
status: in_progress
deps: []
links: []
created: 2026-10-27T05:53:31Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, M2]
---
# M2: measure receipt decoding, model joins and grouping on local raw data

Build a scratch-only DataFusion measurement harness after S1 fixtures. Pin inputs and decision rules before runs; report receipt-shape census/conflicts and largest-line peak memory, join intermediate/build sizes, named versus inline time/RSS, sampled graph labels and resource refusal. No live storage or application join/export implementation.


## Notes

**2026-10-27T10:33:02Z**

Owner refocus ends this measurement: reader tested on all 2289 receipts, all raw-line hashes match, and all 285 count differences are explained duplicate references with secondary storage sizes retained. Full model fit and a 20% named-step advantage are not established; C6/D2 retain those checks. See the short m2-reader.md note and committed census/conflicts. No further measurement rounds.
