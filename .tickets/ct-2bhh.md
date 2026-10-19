---
id: ct-2bhh
status: closed
deps: []
links: []
created: 2026-10-19T22:31:31Z
type: task
priority: 1
assignee: mikewolfd
tags: [efficiency, catalog]
---
# Lower catalog preparation memory and repeated work

Remove measured catalog preparation overhead with the smallest change that preserves published values and reader behavior. Use the retained bounded fixture; avoid another packed-membership experiment.

## Acceptance Criteria

Before/after memory and work measurements; exact payload and review-result parity; focused local tests and independent review. Record limits and actual improvement.

## Notes

**2026-10-19T22:35:39Z**

Implemented narrow retained source columns and bounded saved-flag reads in the existing Catalog; lazy list promotion stays under its reader lock. Publisher drops unused browse columns before take. Controlled retained fixture: 8,950,006 fewer source Arrow bytes (43.9%); no demonstrated overall process-peak or speed gain. All 269 payload hashes/sizes and non-timestamp manifests match across three samples/arm; baseline 60 and final 64 focused checks pass. Evidence: docs/experiments/efficiency-round-two/catalog.md. Ready for independent review; no full-catalog/live/hosted work.

**2026-10-19T22:38:08Z**

Independent review approved a41e369. Retained Arrow source data falls 20,405,570 to 11,455,564 bytes; all 269 payloads match. 60 baseline/64 final checks; combined 139 pass. No demonstrated total peak or speed gain. Evidence: docs/experiments/efficiency-round-two/catalog.md.
