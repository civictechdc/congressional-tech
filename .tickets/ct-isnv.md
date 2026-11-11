---
id: ct-isnv
status: open
deps: []
links: []
created: 2026-11-10T14:57:27Z
type: bug
priority: 1
assignee: mikewolfd
tags: [site, mcp, model, release]
---
# Exact-kind filters lose about 7,550 testimony documents when official names lead

Found by the model review of the next-release stack (.cache/archive-release/investigations/next-release-review-20261110/model/REVIEW.md, Q1 and finding 4) on the first full build (release-next/build-c03c43da). The name rule (ct-h8dr) moves 16,342 documents to the official House kind vocabulary: testimony -> witness-statement 7,658, opening-statement -> member-statement 623, and so on. The moves are right (documents with no kind fall from 45,340 to 39,997), but two exact-kind filters then silently show about 7,550 fewer 'testimony' documents: the site's Document type menu and bookmarks, and the explorer MCP's search_documents. The MCP's hearing reader already treats the two kinds as one.

## Acceptance Criteria

One owner for kind synonyms (a map, not three lists); the site's Document type filter and saved bookmarks, and MCP search_documents, return the same documents for 'testimony' before and after the name rule, measured on the all-in build; a release note line says the kind words changed.


## Notes

**2026-11-10T19:23:54Z**

2026-11-10 WIDENED: the release's cause record measures the same loss for other exact-kind filters, not only the testimony pair this ticket fixed: amendment 4,975 -> 3,687, opening-statement 5,324 -> 4,682, statement 4,355 -> 3,980, legislative-text 1,060 -> 751, biography 1,288 -> 1,042, committee-report 374 -> 216, transcript 1,214 -> 1,116 (documents now take the kind their official file name states, so a document listed under one word and named under another is counted once). Family filters barely move. Open work: decide per pair whether the Explorer and site should treat the words as synonyms, as was done for testimony / witness-statement; recorded as an accepted defect in the release's cause record.

**2026-11-10T20:38:46Z**

2026-11-10 what release 77673bfb8fcf shows. Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables. schema.json publishes one synonym group, document_kind [witness-statement, testimony]. Documents carrying either word: 63,354 -> 64,128 (no loss); the bare word 'testimony' alone 32,200 -> 24,762. The other words still lose under an exact filter, as widened above: amendment 4,975 -> 3,687, opening-statement 5,324 -> 4,693, transcript 1,214 -> 1,134, committee-report 374 -> 216. Not checked here: that the site's Pages deploy and an Explorer release reading the synonyms are live.

**2026-11-11T14:42:31Z**

validated 2026-11-11, left open for the widened decision only. The testimony part is done and live: schema.json of 77673bfb8fcf publishes one synonym group document_kind [witness-statement, testimony]; the site reads it (apps/site/src/components/explorer/reader/kind-synonyms.ts, deployed by Pages run 42917865017 at 515ecb0e), Explorer reads it (congressional_explorer_mcp/release.py:34-41), Explorer 0.6.6 is on PyPI and the hosted Explorer was redeployed on 77673bfb8fcf with 0.6.6 (decisions-overnight 22:48Z, 01:05Z); docs/releases/2026-11-10-77673bfb8fcf.md lines 36-39 say the kind words changed. Remains: the owner's per-pair decision whether amendment, opening-statement, statement, legislative-text, biography, committee-report and transcript get synonyms too (losses listed in the 'WIDENED' note).
