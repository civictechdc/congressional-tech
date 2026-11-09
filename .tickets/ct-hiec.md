---
id: ct-hiec
status: open
deps: []
links: [ct-4jms, ct-082q]
created: 2026-11-08T17:33:29Z
type: feature
priority: 2
assignee: mikewolfd
tags: [congress_api, html, daily]
---
# Read new HTML pages daily without supervision

Moved out of ct-082q's acceptance criteria (owner decision 2026-11-08). New HTML pages captured after a release should get their description, published/updated dates and selected text through the scheduled daily path, without a supervised run. The original pages stay saved in raw, so nothing is lost meanwhile. Depends on scheduled capture (ct-4jms).


## Notes

**2026-11-09T17:56:09Z**

2026-11-09 owner decision: on a day whose new HTML exceeds the derived budget (64 MiB or 5,000 bodies), the nightly reads one budget's worth and carries the rest to the next night instead of stopping at derived_budget_required. Changes the publish-gate semantics for html_metadata only. To implement after thread 1 (claude/ct-thread1-unattended) lands.
