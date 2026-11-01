---
id: ct-itcg
status: open
deps: []
links: []
created: 2026-11-01T20:08:13Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [basin, lake, cutover, phase2]
---
# Commit publish_v21 D1-D4 inputs to Basin and bind live table pins

publish_v21 was built from local Parquet snapshots. The Basin tables still hold older data (ct-87uf recorded 24,304 meeting and 62,782 appearance records; v21 has 24,430 and 66,483), and publish-model.json pins no snapshots. Data model §8.1 requires a release to be reproducible from its input record at pinned table versions.

## Design

Commit the five verified inputs to the archive namespace through the checked-in native jobs. A hash-verified local copy is at .cache/archive-release/publish_v21/inputs (ignored by Git; machine-local). The source is the session scratchpad named in the cef-96wc 2026-11-01T17:43:18Z note. If a checked-in job lacks a needed capability, ct-9gmr supplies it; do not use scratch scripts. The lead performs the live commit.

## Acceptance Criteria

- captures 4,147,132; readings 1,349,139; filename_readings 1,311,075; meeting_records 24,430; appearance_records 66,483 rows read back from Basin, compared per table with the local inputs by key, not by count alone.
- publish-model.json has real snapshot pins and publish.json its receipt keys and refreshed model_spec digest.
- A rebuild from those pins reproduces release 448651e7 or every difference is explained.

