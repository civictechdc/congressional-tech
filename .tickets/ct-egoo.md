---
id: ct-egoo
status: open
deps: []
links: []
created: 2026-11-10T20:37:59Z
type: task
priority: 3
assignee: mikewolfd
tags: [model, record-roles]
---
# GovInfo details pages after the fold: 2 unplaced addresses, the hearing-number title, capture scope

Split from ct-m878 when it closed on release 77673bfb8fcf (2026-11-10). The fold shipped: 0 documents are saved at a govinfo.gov/app/details/ address and 34,824 details addresses sit as unsaved sources on their hearing. Three owner questions from ct-m878's 14:06Z note were never answered: (1) the 2 unplaced pages (unplaced_landing_pages: CHRG-115hhrg24725, CHRG-116hhrg49571, multi-part packages with no package-level file) are listed nowhere now: accept plain removal notices, list the parts at that address, or keep them as documents; (2) whether the details page's title, the only place the hearing number (e.g. 'S. Hrg. 111-774') is published, should fill the hearing's title; (3) capture scope still admits details pages, so each new package adds one more wrapper page to fetch.

## Acceptance Criteria

Each of the three is decided by the owner and either built with a before/after count on a full build or declined with the reason written here.


## Notes

**2026-11-11T14:44:37Z**

validated 2026-11-11, left open: all three are owner questions and none has been answered (no commit or note since the split from ct-m878).
