---
id: ct-h5ks
status: open
deps: []
links: []
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, site, navigation, w5, track2]
---
# W5: Update site navigation and landing page entry points (Header, Footer, index, youtube-coverage, Base)

Add the Phase-2 Explorer / Document Archive link to apps/site/src/components/Footer.astro and feature it on apps/site/src/pages/index.astro, fix active='dashboard' on apps/site/src/pages/youtube-coverage.astro, and add id='top' to apps/site/src/layouts/Base.astro for the footer Back to top button.

## Acceptance Criteria

Footer.astro and index.astro link to the Phase-2 Archive Explorer, youtube-coverage.astro sets its own active nav state, and #top works on every page.

