---
id: ct-30pw
status: open
deps: []
links: []
created: 2026-10-19T22:31:31Z
type: task
priority: 1
assignee: mikewolfd
tags: [efficiency, publication]
---
# Reduce remote publication journal requests

Reduce remote journal round trips while preserving original write conditions, pre-write intent, concurrent attempt fencing, and recovery after uncertain commits. Keep the supported path simple.

## Acceptance Criteria

Matched local request/byte counts and payload parity; focused interruption, lost-acknowledgment and concurrency tests; independent review. No production writes or workflow runs.
