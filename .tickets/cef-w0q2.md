---
id: cef-w0q2
status: in_progress
deps: []
links: []
created: 2026-10-27T18:57:22Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine-first, C5]
---
# C5: forward explicit remote connections through native SQL jobs

## Acceptance Criteria

NativeDatasets.run_job forwards approved remote configuration and only its named secrets to the same verified executable, preserving local behavior and completed-failure identity. No separate application joins or fallback.

