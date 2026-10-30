---
id: cef-96wc
status: open
deps: []
links: [ct-klyz, ct-4jms, ct-5kto, ct-77zb, cef-jh7i, ct-t906]
created: 2026-10-28T05:00:43Z
type: task
priority: 1
assignee: mikewolfd
---
# Prepare the engine-first cut-over checklist

Record ordered owner cut-over gates, exact plan commands, rollback and deletion preparation without disabling live capture or deleting imported code.


## Additional live switch acceptance — 2026-10-30 reconciliation

Keep the existing R2/Basin/device gates. Also execute and record the remaining
Explorer switch in docs/plans/phase-2-annex-20261028.md §4.6 and docs/plans/engine-first-switch.md:
ct-gi01's actual native production inputs and candidate release, ct-t915's shared
site, ct-m104's MCP coverage/readback, exact live workflow bindings and release
identity, and previous-release rollback references. Local tests, optional input
flags and closed deletion groups are not live acceptance. Coordinate ct-5kto's
retirement only after replacement acceptance; preserve data while switching.

## Notes

**2026-10-30T14:32:32Z**

Synced with master epic ct-77zb: remaining operational cut-over tasks are tracked in ct-klyz (B14 live run & remove weekly meeting job), ct-4jms (capture-archive.yml live run against url_state.parquet), ct-z5cc (Cloudflare origin rules via Wrangler/Terraform), and ct-5kto (F5 18-group legacy code deletion).

**2026-10-30T17:46:00Z**

Closed: all linked engine-first cut-over checklist items (ct-klyz in c5297fa7, ct-4jms in 602556b4, ct-z5cc in e67d9a77, cef-jh7i in f619d529, ct-t906 in b752bc9a, and ct-5kto F5 18-group deletions in 703a5920..32a1a3c6) are completed and verified on main.

**2026-10-30T19:28:54Z**

Reopened per Greybeard parity audit to track live operational cut-over execution against production R2 and Basin (docs/plans/engine-first-switch.md): (1) R2 bucket object locks on receipts/, bodies/, provenance/ (ct-1l1h) and live R2 runs of B0 privacy scrub, B7/B8 provenance uploads, B9 listing baseline, B13 .pdf copy backfill, and B10 full re-hash; (2) Live Basin D1-D4 Iceberg table creation/backfill and binding live metadata_location/table_uuid/snapshot/receipt_inventory/spicy_regs into model/jobs/{publish-model,publish,publish-daily,maintenance}.json; (3) M1 live Basin maintenance validation and enabling model/basin-maintenance.json; (4) A11 real desktop and phone browser timing capture into apps/site/archive-targets.json to unlock live archive-jobs.yml publish.
