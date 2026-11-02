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

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): about 2,089 document link pairs on 458 events (a DuckDB estimate until the full run); 38 events gain their first document.

**2026-11-02T21:36:15Z**

2026-11-02 inv-rca e9f4e792 (on release-train 616c9526): the release run refused on invalid_url_keys=9, all doc-url literals in six House XML meeting records, read raw: 'mailto:https://…' (HMKP110944, four), 'ttps://…' (HHRG108501, HHRG108517, HHRG108574), '/https://…' (HMTG115698), 'chrome-extension://…/https://…' (HMKP116910). 284b3948 added meeting_document_urls to the model's URL inputs unfiltered; its test fed them empty. URL inputs now take a meeting literal only when it resolves to http(s); the rest stay unresolved mentions, counted by unresolved_meeting_document_urls. Model only.
