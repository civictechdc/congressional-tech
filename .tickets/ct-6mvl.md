---
id: ct-6mvl
status: open
deps: []
links: [ct-17op]
created: 2026-11-10T03:26:29Z
type: bug
priority: 2
assignee: mikewolfd
tags: [congress_api, mods, witnesses]
---
# MODS witness lines: organization lands in position when the first segment after the name is an organization

Follow-up to ct-rg34, from the release cause review 2026-11-10 (.cache/archive-release/release-20261110/causes/review-C/REVIEW.md, rows in rw_14_regressions.csv). The rule 'first segment after the name is the position' puts an organization in position and leaves organization empty: 21 rows newly in this release (e.g. 'Page Barreto, Hon. Hector V., U.S. Small Business Administration'; one also loses 'CEO'), and 2,217 MODS rows of the same shape already live. Also: William Tower's reviewed blank position became 'Fair Oaks' (restore the reviewed entry); 'C. Richard' for C. Richard Dann (wrong before and after); 65 positions are still not a title; 146 names still start with 'Page '; about 350 organization-first lines still carry the organization as the name (reviewer's estimate). Fix the shared rule at its owner, not a 'Page'-only branch; it is a byte-hashed parser change with its own version step and re-read.

## Acceptance Criteria

The 21 rows and the Tower row read correctly; the count of MODS rows with an organization in position and an empty organization is measured before and after on the full table; a raw check judges a sample from the raw line in both directions with a planted wrong value caught.


## Notes

**2026-11-10T13:27:10Z**

2026-11-10 (session congress-1): from the witness recount, a one-row difference between a recount of named, unsuperseded witnesses and meeting_coverage on meeting 102621 exists in both the live and the new release; the change between releases is the same. Unexplained, low priority.

**2026-11-11T14:45:35Z**

validated 2026-11-11, left open: not fixed on main (no commit names ct-6mvl since filing). The MODS + Member-appearances release in flight (claude/ct-mods-and-member-appearances) is congress-1's; whether it changes this shape was not checked here. Note from ct-wy4c: the owner's 'rank and credentials in their own field' parser work was said to join this ticket's version step but is not in its acceptance yet.
