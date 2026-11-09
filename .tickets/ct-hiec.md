---
id: ct-hiec
status: in_progress
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
**2026-11-09T16:34:36Z**

2026-11-09: the daily path already reads new HTML (publish-daily derived_parsers html_metadata, since d2ec0211). Three things blocked an unattended run. Capture was not scheduled (ct-4jms runbook). The pass spent 93% of its time on per-body commits (ct-z4i9, fixed: one commit per pass). And nothing proved scheduled-capture families reach the nightly: added test_capture_scheduler.py::test_every_capture_family_is_one_the_nightly_ingests (capture-scope.json families are a subset of publish-daily receipt_families). One case remains: a day with more than 64 MiB stored or more than 5,000 new HTML bodies stops the nightly at derived_budget_required and needs a supervised scoped run. Reading at most one budget per night and publishing the rest later would change the publish gate, so that is an owner decision; not changed here.
