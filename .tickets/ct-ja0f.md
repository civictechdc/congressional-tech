---
id: ct-ja0f
status: closed
deps: []
links: []
created: 2026-10-24T18:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-v967
---
# Back up the recovery decisions (accepted.json) to provenance/

Done on Oct 24. A verified create-only copy of `viewer-publications/recoveries/accepted.json` was written to `provenance/recoveries/accepted-00922c1e….json`.

## Acceptance Criteria

- The copy is 9,638,187 bytes with sha256 `00922c1eb29d84cdf68b1d17fb00e050f443942f13b3d35e775192ff42b73864`, written create-only and verified.


## Notes

**2026-10-24T18:21:14Z**

Closed: the backup is `provenance/recoveries/accepted-00922c1e….json` (9,638,187 bytes, sha256 `00922c1eb29d84cdf68b1d17fb00e050f443942f13b3d35e775192ff42b73864`). Evidence: `docs/reviews/2026-10-24-ticket-audit/README.md`, "Actions taken on Oct 24". The local copy in the gitignored `output/provenance-backup-20261024/` is a convenience, not the evidence.
