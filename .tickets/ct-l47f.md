---
id: ct-l47f
status: in_progress
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
