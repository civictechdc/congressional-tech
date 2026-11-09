---
id: ct-8unc
status: in_progress
deps: []
links: []
created: 2026-11-09T00:31:06Z
type: bug
priority: 1
assignee: mikewolfd
tags: [daily, nightly, gate5, producer-records]
---
# Daily producer keeps its gate-5 records when the final head read fails

Nightly 20261108T193702Z (commit 12675ce0) ran produce_daily, appended archive_r1b.captures (8773215935267904969 -> 5555496601826602150) and archive_r1b.readings (1413391431006651405 -> 2552538235432233094), then the finally block's tables.resolve_tables failed with an iceberg REST catalog connect timeout (/v1/config, client error (Connect) operation timed out). _record_moved never ran, so the two moved heads have no producer record and every later nightly refuses with producer_unrecorded. Raw data is safe; the orchestrator wrote the two records by hand. produce_html_metadata and _activate_record_transition share the same finally shape.

## Design

Engine-first: the pinned engine reports retries=0 on resolve and exposes no catalog-connect retry knob, so the Python caller retries. (1) _final_heads retries the idempotent post-append head read (10/30/90 s, sibling work dirs) in produce_daily, produce_html_metadata and _activate_record_transition. (2) Owed records live beside the records, not in a work dir: before its first append a daily or HTML-metadata run writes, per table, its record minus the head at lake/producers/owed/<table_uuid>/<base snapshot|empty>.json (compare-and-swap; the preflight proved the head current and recorded, so anything pending there owed nothing). Its finally marks each one recorded, unmoved, or refused. (3) The next run's _producer_bases completes an unrecorded head: walk its lineage to the nearest recorded ancestor (appends only), read the owed record at that base, require it pending and naming that exact base record, write the record, mark it recorded by preflight. A stale owed record at an older base is never read. Otherwise the producer_unrecorded refusal names the owed key and why. (4) _require_commit owns the commit check; a changed checkout marks the owed records refused, so no preflight completes them. (5) Scoped recovery and activation supersede a pending daily owed record at the base they append onto, so their appends are never credited to the daily run. (6) No manual operator path; the publish job error text includes exception notes.

Review 2026-11-08 (bcf0a293, merge with fixes; owner: fix both before merging): replaced the work-dir producer-owed.json and complete_owed_records, which could write a stale run's identity onto a later run's heads, bypass the commit check, and lived in a directory the nightly deletes.

## Acceptance Criteria

Tests: transient final read retried and recorded; killed run (no finally) completed by the next preflight with byte-equal record fields; lost final read after hand-written records completed from its own base, never the stale one; planted wrong base record refused naming the owed key; changed checkout refused for good. Existing producer record, daily producer and House XML disposition tests pass.
