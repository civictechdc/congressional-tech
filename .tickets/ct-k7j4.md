---
id: ct-k7j4
status: closed
deps: []
links: []
created: 2026-11-18T14:39:04Z
type: bug
priority: 2
assignee: mikewolfd
tags: [model, recordings]
---
# Senate page matcher has the same one-address-per-date weakness

Follow-up to ct-mwod, named by both independent analyses on 2026-11-18 (Codex gpt-6.2-astra with greybeard and etl-workflow; an Opus review). The House rule dropped a correct video-to-meeting match when the same page was stored from a second address. The Senate rules compare literal addresses the same way in three places: model/sql/senate-page-candidates.sql:129-130 (single_url_on_date), model/sql/senate-page-meeting-links.sql:39 (the fallback that needs it) and :72 (the tie rule between pages competing for one event). model/sql/appearance-observations.sql:140 reads those links for Senate witness attribution, so a dropped link there can move witnesses, not only recordings.

No Senate match is known to have been dropped; this is exposure, not an observed loss. Senate hosts carry no party prefix, so the alias forms to look for are www against bare host, http against https, a trailing slash, and query-order or tracking parameters.

First measure: in the live release's sources and url_state, count Senate committee pages held under more than one address with the same path and query. Fix only if the count is not zero, with the same shape as ct-mwod (count pages, not addresses) and a test that adds a mirror to an existing match and keeps its key.

## Acceptance Criteria

The count is recorded here; if not zero, the Senate rules count pages and a test covers a mirrored address.


## Notes

**2026-11-20T23:23:14Z**

Measured release `0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3` on 2026-11-20. The union of sources and URL state contains 47,290 committee addresses, including 35,378 held addresses. The production page key applies `url_resolve(url, NULL)` before comparing the path and query. Across all formats, 26 groups each contain two held addresses. Of these, 24 pairs have PDF source rows, one pair has only URL-state evidence, and one pair identifies the Banking HTML witness directory. Another 180 groups have multiple known addresses and fewer than two held copies.

Banking is the only pair with published Senate witness rows. The two addresses for `/hearings/witness-list?PageNum_rs=2` differ by a trailing ampersand. Each has seven witness rows on its own page occasion. Neither has an assigned event. The published rows show no lost hearing link.

The full ledger is `<main checkout>/.cache/archive-release/long-tail-20261120/senate-id/ct-k7j4-measurement.json`. Run the adjacent `measure_senate.py` with the worktree Python and its local `DOCSPEC_JOB_CONFIG` to replay the measurement against manifest-verified tables. Two runs produced identical bytes with SHA-256 `758dabcfa19cc7d6b1deed0e757e8d60dc59a374c213c0a477a5daf96a2422ad`.

Commit 1b53167570f71ac34f1eb4c2b69d83e834099e1e updates model/sql/senate-page-candidates.sql and senate-page-meeting-links.sql. Both the date fallback and the tied-event rule compare page keys. Senate records are selected once in senate-page-records.sql. The Banking directory cannot supply a hearing date. In packages/viewer_publication/tests/test_meeting_semantics.py the generic-hearing mirror dropped both links under the old SQL. The repaired rule retains both record-to-event links and the original witness key. Different substantive queries remain distinct.
