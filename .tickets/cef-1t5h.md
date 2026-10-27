---
id: cef-1t5h
status: in_progress
deps: []
links: []
created: 2026-10-27T04:07:58Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, B15]
---
# B15: distinguish weekly fetches from rescued import and keep receipts public

## Acceptance Criteria

Weekly receipts keep actual fetch times; rescued run is listed in import-runs; receipts carry no local paths, cookies or credential parameters; focused runner passes and rescued dry run is read-only.


## Notes

**2026-10-27T04:12:17Z**

Prepared three public-receipt/import-run contracts, implementation and PLAN B15 correction, but not committed: required runner stops before pytest because sandbox denies /bin/ps. Full baseline and focused test attempts retained in scratch. Local-only rescue dry run: 33 snapshots, 2013 files, 226 distinct bodies, zero missing blobs; metadata/presence only, no independent re-hash and no network. Ticket remains open. Separate contract and implementation patches retained for contract-first commits after verification.

**2026-10-27T04:25:20Z**

Unsandboxed baseline retained: 11296 passed, 33 failed, 3 errors before new changes. All 9 B15 tests pass with the prepared implementation. Contract-only check proves 3 expected failures against the merged implementation (registration, URL escaping, unsafe writer refusal); no assertions weakened. Real import and weekly credential remain owner-gated.
