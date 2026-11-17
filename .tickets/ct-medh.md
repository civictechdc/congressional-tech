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

Plan (branch ct-medh-one-base-check): move gate 5's base-chain walk (producer_proof._chain_reasons and the version-free part of _record_reasons/_import_reasons, PRODUCERS, job paths) into congress_api.lake.producer_records as one function; producer_proof and daily._producer_bases both call it, so the daily refuses before any append with gate 5's own reason text. Covers ct-hs34 item 9. Publisher-only parts that stay in gate 5: the head record's recomputed versions (needs the model spec) and the row-version counts. Operator-write finding so far: the ct-z4w5 append ran congress_api.cli.captures_ingest --append-stage --apply against the remote catalog from a local clone, then wrote a captures_ingest.py producer record to lake/producers/ by hand; neither holds the raw-source-mirror concurrency group the hosted capture, publish, backfill and maintenance jobs share. The serialized path: put receipts in raw (create-only), and let a lake write happen only in archive-jobs.yml (the nightly's daily ingest discovers receipts/<family>/<day>/ within 14 days of the newest captured day; older receipts go through a committed model/jobs/backfill.json receipt_inventory and gh workflow run archive-jobs.yml -f operation=backfill).

**2026-11-17T18:45:56Z**

Operator writes to production lake tables (docs/nightly.md does not exist on main, so this lives here).

The one serialized path: lake rows are written only by archive-jobs.yml, whose workflow-level concurrency group raw-source-mirror also holds the hosted capture job. An operator who has new receipts writes them to raw, create-only, under receipts/<family>/<YYYY-MM-DD>/, then either waits for the nightly or runs `gh workflow run archive-jobs.yml -f operation=publish`. The daily ingest discovers every family in model/jobs/publish-daily.json from 14 days before that family's newest captured day onward (receipt_inventory.INCREMENTAL_LOOKBACK_DAYS), appends, and writes the producer records. The ct-z4w5 receipts (receipts/documents/2026-11-14/...) were inside that window, so the nightly would have ingested them without the hand append. Nobody writes lake/producers/ records by hand.

Not serialized today: (1) `python -m congress_api.cli.captures_ingest --apply --table <namespace.table>` with a remote engine config from a local checkout (what ct-z4w5 ran, followed by a hand-written captures_ingest.py record in lake/producers/); (2) any local script that calls tables.append_rows or a producer's append against the remote catalog; (3) scripts/nightly_publish.py, whose fcntl lock is local to one Mac. The backfill operation (`-f operation=backfill`, model/jobs/backfill.json) is serialized, but I found no hosted way to name receipts outside the 14-day window: its receipt_inventory rows are local files. That gap needs an owner decision, not a hand append.

Proposed guard, not built (captures_ingest.py belongs to another session): refuse `--apply` when `--table` is one of the nightly's tables in model/jobs/publish-daily.json unless an explicit `--nightly-table` flag is given (about 8 lines in packages/congress_api/src/congress_api/cli/captures_ingest.py). Generation rebuilds into a new table (capture_backfill.execute_batches) keep working. captures_ingest.py is not in the model definition hash.
