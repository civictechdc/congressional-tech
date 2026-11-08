---
id: ct-lft6
status: open
deps: []
links: [ct-gi01]
created: 2026-11-08T17:33:29Z
type: task
priority: 3
assignee: mikewolfd
tags: [capture, ct-gi01]
---
# Finish the paid recapture of 564 legacy Explorer files

Split from ct-gi01 (owner decision 2026-11-08). Owner-approved paid Zyte/Firecrawl retry of 445 out-of-scope legacy URLs plus 119 free-run failures, no cost cap. Selections, scripts and per-round evidence: .cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-gi01/20261108-claude/recapture-plan/ (cl-paid-loop.py). Firecrawl returned HTTP 500 on every call on 2026-11-08, so later rounds run Zyte-only; each round stops at the first uncertain provider result. Done when every URL has an outcome, the counts are recorded, and new receipts are picked up by the next capture append.

