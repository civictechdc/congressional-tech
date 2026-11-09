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

**2026-11-09T21:59:09Z**

2026-11-09 implemented on claude/ct-hiec-carry-budget: _daily_html_metadata narrows an over-budget scope to the oldest budget's worth (_carry_html_metadata: one native job, oldest receipt (day,key) then hash, O(W log W)) and reports carried bodies/stored_bytes (producer report, top-level report['carried'], daily-summary.json). Status stays completed. Gate: archive_publish_job.produce_daily_inputs publishes only status=='completed'; model tolerates unread html_metadata (document-page-metadata.sql outcome 'unread'; profile-completeness.sql checks only sniff/html/xml/json), so no gate change. Unknown stored sizes still refuse; one oversized body reads alone. Tests: test_daily_html_over_budget_reads_the_oldest_budget_and_carries_the_rest[count|bytes] (each body read once over 3 nights, no duplicate rows, gate-5 records); 8 affected files 331 passed. Planted no-carry, newest-first, ignore-bytes and dropped-report variants: each failed the new test.

**2026-11-09T22:41:56Z**

2026-11-09 review fixes on claude/ct-hiec-carry-fixes: (1) unknown stored size counts as max_bytes+1 in the carry and triggers it when the list has >1 body, so on R2 it is read alone (exempt from the post-custody byte gate) instead of refusing every night; carried.stored_bytes stays known sizes, plus unknown_sizes and oldest_day. (3) SQL joins from work_list/admitted (small side); identical outputs to ae218288 on the fixture (3 carry calls compared). (4) day pattern from RECEIPT_DAY.pattern. (5) nightly summary.json daily_carried. (6) docs and ct-4jms corrected. Unreachable re-admit refusal deleted. Tests: two-day/two-family ordering, count vs bytes, single oversized body, R2 unknown-size carry, local unknown-size refusal opens no body; nightly record_daily. Focused 9 files: 357 passed (partial). Planted 8 failures, each caught. Local path: an unknown size still refuses permanently (kept per instruction).
