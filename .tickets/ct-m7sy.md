---
id: ct-m7sy
status: open
deps: []
links: [ct-680z]
created: 2026-11-08T17:42:58Z
type: chore
priority: 3
assignee: mikewolfd
tags: [site, dependencies]
---
# Upgrade the site's Astro from 5.18 to 7.2

Fixes the one critical Dependabot alert (astro), plus sharp and zod alerts. Build-time only: the site is static, uses no image optimisation, and zod validates only our own content. Two major versions; check the archive contract and canary after the upgrade. Surfaced by the ct-680z sweep (2026-11-08).

