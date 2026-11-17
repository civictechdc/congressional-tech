---
id: ct-w3dn
status: open
deps: []
links: [ct-medh]
created: 2026-11-17T19:50:00Z
type: task
priority: 2
assignee: mikewolfd
tags: [lake, operator, hosted]
---
# Close the two operator write paths the nightly does not serialize

Found doing ct-medh (2026-11-17). Lake tables are meant to be written only by `archive-jobs.yml`, whose jobs share the `raw-source-mirror` concurrency group with the capture. Two gaps remain.

1. `python -m congress_api.cli.captures_ingest --apply --table <the nightly's captures table>` run from a local checkout against the remote catalog still works, under no lock the nightly shares. This is what appended to `archive_r1b.captures_df55_20261113` on 2026-11-17 (ct-z4w5). Proposed guard, about 6 lines in `packages/congress_api/src/congress_api/cli/captures_ingest.py`: refuse `--apply` to any table named in `model/jobs/publish-daily.json` unless `--nightly-table` is passed. Rebuilds into a new table keep working. That file belongs to the capture-integration work in another session, so the change should be made there or agreed with it.
2. There is no hosted way to ingest receipts older than the daily's 14-day lookback (`receipt_inventory.INCREMENTAL_LOOKBACK_DAYS`): the backfill spec's receipt list takes only local files. An operator with old receipts has no serialized path. Owner decision: accept (old receipts wait for a full backfill) or give the hosted backfill a receipt-prefix input.

## Acceptance Criteria

The local script refuses to append to a table the nightly writes unless told to explicitly, and item 2 is either built or closed with the owner's decision.
