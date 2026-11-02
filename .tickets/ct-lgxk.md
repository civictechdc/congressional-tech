---
id: ct-lgxk
status: open
deps: []
links: [ct-qg8e, ct-64el, ct-yf1c]
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


## Notes

**2026-11-02T04:01:45Z**

No confirmed code; recheck after a rebuild.

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): The ZIP rule would put 'ZIP' back on about 34k member PDFs; fix skips format words via a registry list and uses the HTML rendition's title. impl-g.

**2026-11-02T14:16:11Z**

2026-11-02 impl-g (r1b-g): link-word titles 11,047 to 0 on the Run B slice; a recovery-only title test was added (it fails on base SQL).

**2026-11-02T14:46:01Z**

2026-11-02 green-g (request changes): link-word titles still miss a format word plus a size ('Download XML (6KB)': 611 live; 'PDF (48.1 MB)' in Run B), and the generic_titles check reuses the same list. Needs a format-only rule and an independent check. Also a wrong title from a 'Skip to Content' grouping link.
