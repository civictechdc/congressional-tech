---
id: ct-an6o
status: open
deps: []
links: [ct-680z]
created: 2026-11-08T17:42:58Z
type: feature
priority: 2
assignee: mikewolfd
tags: [identity, dependencies]
---
# Hash only the packages each parser imports into its producer identity

Every root uv.lock change moves all eight producer parser identities, because the whole lock is hashed into them, so patch-only security bumps (aiohttp, pyasn1, lxml) each need a reviewed identity mapping. reading_version_diagnostics.py already walks each parser's imports; hash only the locked versions of those packages so unrelated security patches stop changing data identities. Surfaced by the ct-680z sweep (2026-11-08).

