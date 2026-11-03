---
id: ct-umtm
status: open
deps: []
links: [ct-9lxf, ct-tk10]
created: 2026-11-02T17:20:05Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [recovery, phase2]
---
# Resume document recovery after the release, aimed at removal-notice links first

Owner decision 2026-11-02: resume the October recovery effort after the fixed release. The verified recoveries (5,154) are already in the archive. The NARA leg (.cache/document-bulk-recovery-20261014T1552Z/nara) stopped on 2026-10-14 on proxy failures with long target-filter URLs ('preserve results'); it validated 10 veterans.house.gov transcripts (7 NARA recoveries in v21) and left unfinished batches (e.g. oversightdemocrats.house.gov testimony). The 15 GB workspace .cache/nara-filename-estimate-20261015 holds the Wayback continuation, residual hosts and docs.house.gov follow-ups. Both are protected (never prune).

## Acceptance Criteria

Fix the proxy request-length transport issue; import the remaining valid recoveries through the checked-in recovery import with evidence pins; target first the release's removal-notice links (132 against 448651e7) and remaining dead links; each recovery verified against its source; gate 1 records them as additions with causes.


## Notes

**2026-11-02T22:27:53Z**

2026-11-02: the merge-by-fingerprint conflicts expose likely wrong accepted recoveries (statement link to biography body; congress 103 vs 114). The recovery round should re-verify accepted recoveries whose link and copy disagree on congress, document class, person or hearing date.
