---
id: ct-66ns
status: closed
deps: []
links: [ct-gi01, ct-j2yo, ct-dx22, ct-2o4d, ct-67k1]
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

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
