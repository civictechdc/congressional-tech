---
id: crc-lun2
status: closed
deps: []
links: []
created: 2026-10-28T14:07:53Z
type: task
priority: 1
assignee: mikewolfd
---
# Record hosted disk capacity before native CI setup

## Acceptance Criteria

Every shared offline runtime setup records byte-level disk capacity and its public native-job limits before private runtime installation; existing focused setup checks and YAML shell syntax pass. Actual hosted values remain a lead-run observation.


## Notes

**2026-10-28T14:10:33Z**

Prepared shared-action disk and public-limit record before private installation. Existing local/runtime setup checks: 54 passed in 9.04s. Every action shell block passes bash -n. Actual hosted df values require the lead-run workflow; no hosted action was executed.

**2026-10-28T16:13:33Z**

Final literal six-shard run on 1149c96a covered 13,788 unique selected identities with no missing/extra/duplicate IDs. Five shards passed; the sole failure was a main-only contract assuming the installer was step zero after the added disk diagnostic. Locate the unique actual installer, preserve all trust/missing-credential assertions, and additionally require credential inputs only on that installer. Native variant file passes 15 checks. No production assertion or skip weakened.
