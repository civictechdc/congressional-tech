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
