---
id: ct-dzyf
status: open
deps: []
links: []
created: 2026-10-21T15:21:26Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, news-lake, recovery, publication]
---
# Make Coordinator.abandon_cycle work with DocSpecLake-backed publication

Independent CS300 audit finding (re-validated): news_lake.storage.coordinator.Coordinator.abandon_cycle (coordinator.py:264-345) restores failed publication cycles by calling self.lake.table('news.releases').current_snapshot() and per-table PyIceberg snapshot scans. DocSpecLake (docspec_backend.py) has no .table() method, so abandoning a DocSpec-backed cycle raises AttributeError instead of restoring the pinned baseline.

## Acceptance Criteria

- Add a DocSpecLake-native abandon path: restore each content dataset to the exact ReleasePin recorded in the latest available release manifest (releases/<id>.json dataset_pins) via 0-row base-bound update_table against those pins, or explicitly refuse with an actionable error if a dataset has no pinned baseline.
- Cover: abandon after a failed validation mid-cycle (bad C7 corpus), abandon idempotency, refuse when the release record was already appended, and staged-checkpoint discard.
- Keep the PyIceberg path unchanged for the Iceberg Lake.
