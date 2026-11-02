---
id: ct-qg8e
status: open
deps: []
links: [ct-64el, ct-n2cy, ct-ktfe, ct-5f3e, ct-fh62, ct-dx22, ct-c6b0, ct-o2pr, ct-lgxk, ct-d3tk, cef-96wc, ct-tk10, ct-d0o0]
created: 2026-11-01T20:08:13Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, qualification, phase2]
---
# Explain publish_v21 row-count changes against release c94bfedc

Between c94bfedc and 448651e7: list 367,008 to 427,517; sources 605,848 to 537,077; links 439,555 to 432,320; bills 11,832 to 13,234; witnesses 147,048 to 147,888; url_state 1,201,754 to 1,198,835. No ticket explains these.

## Design

Compare the two public releases by key, not by count. Classify added and removed rows by cause (recovery round, URL normalization, parser changes, upstream generation). Then re-measure ct-opy0 and ct-db3w, which were measured on c94bfedc.

## Acceptance Criteria

- Every added or removed row group has a recorded cause and count; anything unexplained is listed as a defect.
- ct-opy0 and ct-db3w carry numbers for the live release.


## Notes

**2026-11-02T00:36:42Z**

Row changes are sized across all 19 manifest files. release_diff.py is a diagnostic and exits 1 on this pair; its failing list names unchecked causes and defects. Recovery round and upstream generation contributed zero rows. Real causes: ct-sh4j eligibility, meetings SQL, oEmbed scope rule, witness key redefinition, URL rules. Stay open until a rebuild proves restoration. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.
