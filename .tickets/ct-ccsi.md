---
id: ct-ccsi
status: in_progress
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 3
assignee: mikewolfd
tags: [model, titles]
---
# New documents take bare numbers and 'Biography' as titles from link text

1,386 documents first titled on 2026-11-10 take their title from link text on 268 newly ingested event pages: 111 are bare numbers, 163 are 'Biography' and one is '.'. No existing title was replaced or emptied. Source: .cache/archive-release/release-20261110/causes/review-DE/REVIEW.md.

## Acceptance Criteria

A link text that is a bare number, punctuation or a generic label is not used as a title when the file name or the page gives a better one; the counts of such titles are measured before and after on a full build.


## Notes

**2026-11-10T13:27:30Z**

2026-11-10 status: fixed on claude/ct-next-release (247bbf6f, 2249baf8, 99e7e0dd). Of the ticket's 275 titles, 103 become 'Biography - <name>' and 172 show their filename; 334 other junk titles change with them. Left: full model build on the stack to measure before/after, review, release. Closes when released.
