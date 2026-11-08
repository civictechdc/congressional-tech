---
id: ct-m7sy
status: closed
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


## Notes

**2026-11-08T19:07:05Z**

Branch claude/ct-l1zw-m7sy: astro 5.18 -> 7.3.8, @astrojs/react -> 7.1.0, @astrojs/check 0.9.12; sharp 0.35.5, zod 4.6.7; npm audit 0 vulns. Content config moved to src/content.config.ts with z from astro/zod (Astro 6 removes the legacy path). 7.4.x and @astrojs/react >=7.1.1 need Node >=22.23.4, above .node-version 22.22.2, so pinned with ~ until Node is bumped. Build ok; 30/30 pages same list, same text and links (only &#34; vs &quot; entity in an mcp attribute); test:explorer 111/111, archive-unit 19/19, astro check 0 errors, archive contract 3/3.

**2026-11-08T20:01:35Z**

2026-11-08 closed: Astro 5.18 -> 7.3.8, @astrojs/react 7.1.0, sharp 0.35.5, zod 4.6.7, esbuild declared (0.28.2); npm audit 0 vulnerabilities; same 30 built pages (only hashed bundles differ); validate-explorer green (run 42516117742). Astro 7.4+ needs .node-version >= 22.23.4 (later).
