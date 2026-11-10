---
id: ct-xj8s
status: open
deps: []
links: []
created: 2026-11-10T20:37:59Z
type: task
priority: 3
assignee: mikewolfd
tags: [model, record-roles]
---
# Navigation pages published as documents: 48 web pages linked from 30 or more captured pages

Split from ct-aoxp when it closed on release 77673bfb8fcf (2026-11-10); its 08:48Z note said a general furniture rule needs its own ticket and an owner view. Measured then on 619db5f9e08e (.cache/archive-release/investigations/document-roles-20261110/dr-05b-web-pages-linked-from-10-or-more.csv): 48 web-page documents are linked from 30 or more captured pages (22 from 100 or more), and 8 documents are a site's home page; none has a meeting now that the help page is a wrapper. From 10 pages up the list also holds 23 parts of one printed hearing, which are real. Options weighed in ct-aoxp: a link-count threshold (flips documents as captures grow), or a per-host list of application pages.

## Acceptance Criteria

An owner view on which index pages are documents is recorded; the chosen rule (or a decision to keep them) is applied and measured on a full build with the count before and after.

