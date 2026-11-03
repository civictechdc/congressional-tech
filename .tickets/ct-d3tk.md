---
id: ct-d3tk
status: closed
deps: []
links: [ct-qg8e]
created: 2026-11-02T03:01:04Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [release, docs, phase2]
---
# Correct release-diff evidence counts

Final review of docs/measurements/release-diff-c94bfedc-448651e7-20261101.md found three counts to reconcile. Public witnesses show 18 events whose package changed, not 17; add the missing event and re-score the 8/3/6 tally. url_state +21: exact hrefs give 13 on 6324e3ed and 2 on b0fe3f4c, union 14, not 12/1/13; reconcile with '8 on newly real pages'. Moved CHRG-*.zip URLs are 10,195, but the doc also says 10,201. A swapped subject key still exits 0 in release_diff.py, which the doc discloses. The test lane, verifier and MODS for the other 16 events were not rerun in that final pass.

## Acceptance Criteria

The doc's counts are reconciled from public releases and raw records, or each difference is explained.


## Notes

**2026-11-02T12:36:53Z**

Round 1b 2026-11-02 (lead): Counts corrected in the measurement doc on r1b-h: 18 moved meetings re-scored 9 better, 4 worse, 5 tied (MODS titles read from govinfo); url_state +21 is 14 + 7; 10,195 CHRG zips. Close at merge.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
