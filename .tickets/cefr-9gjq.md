---
id: cefr-9gjq
status: closed
deps: []
links: []
created: 2026-10-28T12:53:45Z
type: bug
priority: 1
assignee: mikewolfd
---
# D1 scratch monitor tolerates vanished paths

Skip only vanished scratch directories or entries during allocated-byte accounting; retain non-ENOENT refusals and all resource ceilings. Deterministic real-filesystem race fixture before the fix; focused runner and one CODE review.


## Notes

**2026-10-28T12:57:51Z**

Contract bf1ba92e moves the existing loop unchanged and reproduces actual FileNotFoundError opening a queued directory removed at parent scan close; three custom ENOENT cases also fail before the behavior fix. Fix 98d1a2cb skips only FileNotFoundError/ENOENT at directory scan and entry classification/stat, keeps nonmissing errors/interruption and allocated st_blocks*512 without following links. All30 focused scratch/monitor checks pass through production-offline with runtime885; focused.log span6.665s includes doctor (pytest elapsed not emitted). Independent CODE APPROVE, no findings. Shared API/15GiB free floor/5GiB ceiling and D1 mapping unchanged. Full rerun belongs to root/release.
