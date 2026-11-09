---
id: ct-8unc
status: closed
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

Engine-first: the pinned engine reports retries=0 on resolve and exposes no catalog-connect retry knob, so the Python caller retries. (1) _final_heads retries the idempotent post-append head read (10/30/90 s via the injectable daily.SLEEP, sibling work dirs) in produce_daily, produce_html_metadata and _activate_record_transition. (2) Owed records live beside the records: before its first append a daily or HTML-metadata run writes, per table, its record minus the head at lake/producers/owed/<table_uuid>/<base snapshot|empty>.json by compare-and-swap, replacing whatever is still pending at heads its preflight just proved current and recorded under the nightly flock. (3) The next run's _producer_bases completes an unrecorded head: walk to the nearest recorded ancestor (one record lookup per unrecorded snapshot, linear in the dead run's appends; len(lineage)+1 steps bound a cycle, refused with a reason, as is a snapshot missing from the lineage), check appended_from, take the owed record at that base only if pending and naming that exact base record, write the record. A stale owed record at an older base is never read; otherwise producer_unrecorded names the owed key and why. (4) _require_commit owns the commit check, run once per settle. A changed checkout marks every table's owed record refused, each retried (1/5/15 s); any that cannot be marked raises CheckoutChanged naming the keys that must not complete. (5) The "recorded" mark (by the run or by preflight) is evidence only: best effort, with failures in the stopping exception's notes or report['owed_unmarked']. An interrupt (KeyboardInterrupt, SystemExit) gets one head read and one try at each mark, no waits; a failure becomes a note and the next preflight completes the rest. Unmoved tables are not marked (nothing reads that; the next run replaces them). (6) Scoped recovery and activation supersede a pending daily owed record at the base they append onto. (7) No manual operator path; the publish job error text includes exception notes.

Accepted risk (owner, 2026-11-08, questions tool: "Keep auto-complete"): the next run completes a killed run's owed records automatically, so a run whose checkout changed and that then died before checking it is completed under the commit it started from. Also named in producer_records.py "Cannot see".

Review 1 (bcf0a293, merge with fixes; owner: fix both before merging): replaced the work-dir producer-owed.json and complete_owed_records, which could write a stale run's identity onto a later run's heads, bypass the commit check, and lived in a directory the nightly deletes. Review 2 (b81dc5db, merge after fixes): robust refusal marks, best-effort status marks, injectable sleep, ownership checks, walk cap, R2 compare-and-swap loopback test. Review 3 (60357f22): the 32-snapshot walk cap refused real completions (the real runs appended 293 and 135 snapshots), so the walk is bounded by the lineage instead; the dead _owe_records ownership guard is removed; interrupts no longer wait.

## Acceptance Criteria

Tests: transient final read retried and recorded, one owed record per table; a failed recorded mark never fails the run; a refusal mark retried per table, a lasting failure named; killed run completed by the next preflight; 40 unrecorded appends completed, a lineage cycle and a missing snapshot refused; a lost final read with a changed checkout refuses and raises the read; a failed mark while a run stops becomes a note; an interrupt reads once and leaves the rest pending; lost final read after hand-written records completed from its own base, never the stale one; planted wrong base record refused naming the owed key; changed checkout refused for good; activation supersedes a pending daily owed record; R2 If-None-Match/If-Match with 412 PreconditionFailed through the real SDK (storage-loopback). Existing producer record, daily producer, House XML, publish job and selective tests pass.

## Notes

**2026-11-09T05:34:29Z**

Merged to local main at 1ae30211 (fast-forward over e2c878ad, after the body-text merge). Full lanes on that tree, 2026-11-09: production-offline (full lane): exit 0 — 12258 passed, 39 skipped in 2451.96s; storage-loopback (full lane): exit 0 — 34 passed. Log: .cache/archive-release/investigations/ct-8unc-lane-1ae30211-20261109.log. Three independent reviews (findings folded in bcf0a293..1ae30211). Not covered by tests: real R2 accepting If-Match on lake/producers/owed/ (archive_publish already uses If-Match in the same bucket), and scoped-recovery supersede (no caller or fixture). The 2026-11-09 killed nightly predates this code and left no owed record: its readings head (1536270973362461595) still needs one hand-written record, pending owner decision.
