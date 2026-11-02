---
id: ct-d3tk
status: open
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

