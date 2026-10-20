---
id: ct-n7la
status: closed
deps: []
links: []
created: 2026-10-20T18:28:03Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Refuse insufficient combined staging capacity before import

Check the enforced typed preparation budget together with unchanged native scratch requirements and retained 8 GiB headroom before bulk preparation. Account for separate filesystems and already retained stage bytes; recheck at bounded work boundaries.

## Acceptance Criteria

Local tests prove early refusal before source iteration, combined same-volume accounting, separate-volume accounting, explicit native limits and unchanged existing staging. Budget estimates are labelled estimates; native admission remains authoritative.


## Notes

**2026-10-20T18:29:30Z**

Added early combined-capacity helper and 12 passing local characterization tests after red import failure. Accounts for retained stage bytes and separate filesystems; uses unchanged native scratch and 8 GiB headroom. Actual adoption wiring and independent review remain pending the typed-preparation lane.

**2026-10-20T18:56:21Z**

Implemented early and bounded-progress capacity admission without changing native limits. Preparation uses an enforced metadata-derived budget; repeated checks use tracked bytes, not directory scans. Red integration2failed/1passed; final46passed/1actual-native deselected in3.46s. Independent static review APPROVE with exact file hashes in primary output/docspec-reuse-20261020/capacity-integration-review.json. Production import remains untouched; aggregate adoption qualification is ct-nc7l.
