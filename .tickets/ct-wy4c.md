---
id: ct-wy4c
status: open
deps: []
links: []
created: 2026-11-10T03:26:29Z
type: task
priority: 3
assignee: mikewolfd
tags: [mods, witnesses, owner-decision]
---
# Decide whether witness rows show military rank and credentials

After ct-rg34, 299 more MODS witness rows no longer show a rank or credential (47 rank, 291 credential). The live release already drops rank on 944 rows and credentials on 6,474. Nothing is lost in raw. Whether a witness's rank or credential belongs in name, position or a field of its own is an owner decision. Source: .cache/archive-release/release-20261110/causes/review-C/REVIEW.md.

## Acceptance Criteria

The owner's decision is recorded here and, if rank or credentials are kept, a parser ticket is filed with the measured row counts.


## Notes

**2026-11-10T05:38:12Z**

2026-11-10 owner decision (questions dialog): rank and credentials go in their own field, not the name and not dropped. Reviewer's corrected count: 299 rows this release (47 rank, 291 credential); live already drops rank on 944 rows and credentials on 6,474. The parser work joins ct-6mvl's version step.
