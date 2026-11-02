---
id: ct-n6fz
status: open
deps: []
links: [ct-gi01]
created: 2026-11-02T04:01:45Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [explorer, videos, phase2]
---
# Three videos appear in API responses but not in the videos table

OxCoikJbuMw and hCg0yJjUJEA are unlisted, so uploads scans miss them; xYlb_m1rNnY is public, cause unknown.

## Acceptance Criteria

Add publisher-linked videos and explain the third.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): 18 directory-channel videos missing; xYlb_m1rNnY is an unprocessed 34.5-hour live stream absent from a complete uploads scan (YouTube omission inferred, not proven). impl-g.

**2026-11-02T14:16:11Z**

2026-11-02 impl-g (r1b-g): of the 18 videos, 1 has a page link, 12 are named only in House XML meeting records, and 5 appear only in YouTube API responses (nqOUEtSu-hU, zuHYKHmaNMQ, UpRZk58JKpI, vqJ0GLe_MKI, qdd6SAV-CDk). Lead decision: keep all 5 in videos as unmatched committee-channel videos; the owner rule is that no fact is dropped, and the matcher may link them later.
