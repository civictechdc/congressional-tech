---
id: ct-5f3e
status: closed
deps: []
links: [ct-sh4j, ct-qg8e, ct-itcg]
created: 2026-11-02T00:36:42Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [captures, gates, phase2]
---
# Capture comparison does not compare complete or outcome

capture_comparison.py:42 lists complete and outcome under not_compared, along with attempt, fetch_http_status and fetch_outcome. So it could not report 171,894 member rows moving from true to NULL, or the v21 rows that disagree with raw receipts. The guard also cannot see in-domain wrong values.

## Acceptance Criteria

The comparison reports changes to those fields by count and by raw value, tested with a fixture where only complete changes. Whether a change refuses or is reported is decided in this ticket.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): The old index lacks complete and outcome, so it can't compare them. Decided: a generation comparison reports every eligibility-field change by count and old/new value and refuses unexpected changes. impl-e1.

**2026-11-02T13:54:36Z**

2026-11-02 (lead): compare_generations implemented on r1b-e1.

**2026-11-02T17:21:55Z**

2026-11-02 impl-e1/spec-run: the D1 captures rebuild vs v21 is ACCEPTED by compare_generations with the expected-change-class file (r1b-captures-causes cabfffb9, off candidate-r1b). 4,147,132 rows on both sides, 0 rows on one side only, 0 unexpected changes. An independent raw judge read the receipt lines (status, body size, content_range) of all 111,324 changed rows and left none unexplained. Result: .cache/archive-release/r1b-run/compare/generations-expected.json. Limit: like the backfill guard, this sees changed rows only; an unchanged value that is wrong but in-domain is not covered here (gate 1 and the raw value comparison cover that).

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
