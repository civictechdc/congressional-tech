---
id: ct-r8ne
status: closed
deps: []
links: []
created: 2026-10-30T14:32:31Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, site, css, responsive, w6, track2]
---
# W6: Fix remaining marketing & dashboard visual and responsive bugs

Fix <p class='filter-empty'> placement and .chip selection/focus styles on apps/site/src/pages/proposals/index.astro, fix under-filled auto-fill 2-card grids on index.astro / projects.astro / subprojects/index.astro (plus live frontmatter on V.1.md), and fix mobile (412px) horizontal clipping on /youtube-coverage/ in dashboard.css.

## Acceptance Criteria

proposals/index.astro filter-empty and chip states render cleanly, 2-card grids fill desktop width, V.1.md includes live link, and /youtube-coverage/ has zero horizontal overflow at 412px.


## Notes

**2026-10-30T14:50:39Z**

Completed W6 in wt-track3-site (incorporating Greybeard review b04b2a28): added live/liveUrl/liveLabel to projects Zod schema in content/config.ts and V.1.md/I.2.md, rendered live CTA links on index.astro/projects.astro/subprojects/index.astro, changed auto-fill to auto-fit on proposals/index.astro and 2-card grids, moved #filter-empty outside #proposal-grid with aria-pressed/focus-visible chip styles, and fixed mobile (<=768px) horizontal overflow in dashboard.css.
