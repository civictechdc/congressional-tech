---
id: ct-mx3g
status: open
deps: []
links: []
created: 2026-11-04T02:25:37Z
type: bug
priority: 2
assignee: mikewolfd
tags: [publication, coverage, chaos-test]
---
# rosters coverage gap note claims 113th-119th but release publishes 119th only

rosters.parquet coverage publishes congress_start=119 and congress_end=119, and all 2,973 rows are congress 119 (verified on release e4538f00), but the gap string reads 'Committee seats cover the 113th-119th Congresses only'. The upstream committee_assignments limits text gets the framing right ('Schema supports 113th-119th Congress committee and subcommittee assignments; currently populated for the 119th Congress in the pinned upstream snapshot') — the rosters gap note should agree with the published rows or state the schema-support vs populated distinction. Discovered via chaos run chaos-congress-mcp-20261103 and confirmed in review.

## Acceptance Criteria

The rosters gap note agrees with the published coverage values for a fixed fixture (both directions: a release genuinely spanning multiple Congresses, and the current 119-only one). A publication test asserts note text consistency with coverage values.

