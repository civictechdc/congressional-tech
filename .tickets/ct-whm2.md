---
id: ct-whm2
status: open
deps: []
links: []
created: 2026-11-04T02:33:37Z
type: bug
priority: 1
assignee: mikewolfd
tags: [archive, ci, publish]
---
# Hosted publish: fetch the pinned spicy-regs inputs on the runner

publish-model.json pins spicy_regs at ../../.cache/archive-release/r1b/inputs/spicy_regs/spicy-regs.json, and that manifest's 25-odd tables resolve to Parquet files beside it (44 MB). Nothing under .cache is in git and no workflow step or job downloads them, so a hosted publish fails when the model build reads spicy-regs. The public source in the manifest (pub-72e95c0c20a84508b42b03a6ff6d55f8.r2.dev) still serves the pinned paths (amendments.parquet: 200, 143,880 bytes = pin).

## Acceptance Criteria

The manifest is checked in (or fetched by pin), and a hosted publish obtains every table it names from the manifest's source by its generations path, refusing any file whose sha256 or size differs from the pin, before the model build. Repo test with a local HTTP fake; recording_decision_files needs nothing (the daily path takes it from bucket records).

