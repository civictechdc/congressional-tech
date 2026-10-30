---
id: ct-5v1y
status: closed
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


## Notes

**2026-10-30T17:17:30Z**

Verified completed in commit 7bde0dc3: declared blake3>=1.0 in packages/docspec_client/pyproject.toml (uv.lock), deleted the 110-line pure-Python BLAKE3 fallback in packages/docspec_client/src/docspec_client/transport.py (wc -l: 217 -> 109), and verified with uv run pytest -q packages/docspec_client/tests/ (28 passed).
