---
id: ct-5v1y
status: open
deps: []
links: []
created: 2026-10-24T18:46:38Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-tw3r
tags: [audit-20261024, efficiency]
---
# Declare blake3 and delete the pure-Python fallback

Efficiency pass E8, confirmed in the audit: blake3 is in no pyproject and not in uv.lock, so locked CI uses the hand-written fallback (transport.py:18-125), about 380-1000x slower, on every news_lake IPC write.

## Acceptance Criteria

- blake3 is declared in packages/docspec_client and present in uv.lock.
- The pure-Python fallback is deleted; a missing blake3 fails at import.
- The capture and native test lanes pass through the project runner.

