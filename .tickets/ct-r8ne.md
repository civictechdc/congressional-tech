---
id: ct-r8ne
status: open
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

