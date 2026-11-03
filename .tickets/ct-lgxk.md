---
id: ct-lgxk
status: closed
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

**2026-11-02T15:30:02Z**

2026-11-02 impl-g: format-plus-size titles are link words, and generic_titles uses its own rule (95800ba5); title order is reading, then listing, then rendition (127a7c0b); navigation self-links don't group (a19fa66e). red-g2 is doing a focused re-check; data effect measured on the integrated run.

**2026-11-02T15:38:20Z**

2026-11-02 red-g2: merge with two fixes. generic_titles must count a registry match OR the new rule (it now misses 'Untitled', 'Read more', etc., and the recovery path passes raw titles); add 'Printable PDF of this Document' and 'Download Report' as link words. 'Exhibit A' and 'Appendix D' pass.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
