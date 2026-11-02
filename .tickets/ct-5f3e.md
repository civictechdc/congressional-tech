---
id: ct-5f3e
status: open
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
