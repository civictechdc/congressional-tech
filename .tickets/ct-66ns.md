---
id: ct-66ns
status: open
deps: []
links: [ct-gi01]
created: 2026-11-02T04:01:45Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [model, coverage, phase2]
---
# Documents coverage overcounted, and events lack meeting links

review-c-explorer: of 960 raw=yes, 45 have file URLs; the rest are URL-less entries or meeting-documents string matches. At least 610 events have old documents in sources without meeting_keys.

## Acceptance Criteria

Coverage counts real document evidence, and those events are linked or explained.


## Notes

**2026-11-02T12:28:28Z**

Round 1b 2026-11-02 (lead): source-annotations-meetings joins the URLs the House record lists: +2,089 links on 458 meetings, and 38 meetings go from not_stated to present. impl-f.
