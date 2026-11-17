---
id: ct-medh
status: in_progress
deps: []
links: []
created: 2026-11-17T18:18:49Z
type: task
priority: 1
assignee: mikewolfd
tags: [hosted, lake, gate5]
---
# One base check for the nightly's pre-check and gate 5; operator lake writes go through the pipeline

Root cause 4 of the 2026-11-17 RCA. lake/daily.py _producer_bases accepts any existing head record, while producer_proof judges it afterwards, so the nightly can append onto a base the gate then refuses, or leave state after an interruption that the gate rejects. Operator sessions also append to production tables under no lock the nightly shares (ct-z4w5 on 2026-11-17).

## Acceptance Criteria

The nightly refuses before appending whenever gate 5 would refuse its base, from one shared rule. Operator writes to production lake tables have one documented path that is serialized with the nightly.


## Notes

**2026-11-17T18:30:37Z**

One rule, in congress_api.lake.producer_records (branch ct-medh-one-base-check): base_problems walks a base's records back to an empty table, a checked-in import or another registered producer's snapshot, with record_problems, import_problems, link_problems and the PRODUCERS registry moved there from producer_proof. Gate 5's _chain_reasons is now the head's link plus base_problems; daily._producer_bases calls base_problems on every recorded head before it owes or appends anything and refuses with `refused: {table: [gate 5's reason]}` under status producer_unrecorded. That covers produce_daily, produce_html_metadata, append_scoped_recovery and the record activations, which all share the preflight. Covers ct-hs34 item 9.

The preflight cannot see the parts of gate 5 that need the publish model: the head record's versions recomputed at its commit (gate 5 also judges a table the night leaves unmoved as a head, with versions) and the per-row version counts (for captures the daily's own stale-mapping check is stricter). It judges reachability from its own checkout's HEAD with its own anchors; in the hosted publish job both are gate 5's.

**2026-11-17T18:45:56Z**

Operator writes to production lake tables (docs/nightly.md does not exist on main, so this lives here).

The one serialized path: lake rows are written only by archive-jobs.yml, whose workflow-level concurrency group raw-source-mirror also holds the hosted capture job. An operator who has new receipts writes them to raw, create-only, under receipts/<family>/<YYYY-MM-DD>/, then either waits for the nightly or runs `gh workflow run archive-jobs.yml -f operation=publish`. The daily ingest lists every family in model/jobs/publish-daily.json from 14 days before that family's newest captured day onward (receipt_inventory.INCREMENTAL_LOOKBACK_DAYS), appends, and writes the producer records. The ct-z4w5 receipts (receipts/documents/2026-11-14/...) were inside that window, so the nightly's discovery would have listed them without the hand append. Nobody writes lake/producers/ records by hand.

Not serialized today: (1) `python -m congress_api.cli.captures_ingest --apply --table <namespace.table>` with a remote engine config from a local checkout (what ct-z4w5 ran against archive_r1b.captures_df55_20261113, the nightly's captures table, followed by a hand-written captures_ingest.py record in lake/producers/); (2) any local script that calls tables.append_rows or a producer's append against the remote catalog; (3) scripts/nightly_publish.py, whose fcntl lock is local to one Mac. The backfill operation (`-f operation=backfill`, model/jobs/backfill.json) is serialized, but I found no hosted way to name receipts outside the 14-day window: its receipt_inventory rows are local files. That gap needs an owner decision, not a hand append.

Proposed guard, not built (captures_ingest.py belongs to another session): refuse `--apply` when `--table` is one of the nightly's tables in model/jobs/publish-daily.json unless an explicit `--nightly-table` flag is given: 6 added lines in packages/congress_api/src/congress_api/cli/captures_ingest.py, no other change. Generation rebuilds into a new table (capture_backfill.execute_batches) keep working. captures_ingest.py is not in the model definition hash.
