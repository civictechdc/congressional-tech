---
id: ct-lgxk
status: open
deps: []
links: [ct-qg8e, ct-64el]
created: 2026-11-02T00:36:42Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, phase2]
---
# Rows titled ZIP or PDF from link-text fallback

34,184 rows in c94bfedc were titled "ZIP", 33,842 of them PDFs, and 3,743 rows are titled "PDF". Traced to the link-text fallback in 068f2a40; present in all 4 reachable releases. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

A format word is never a title; affected rows use the document title or stay null, with a check. Recheck after the ZIP rule.

