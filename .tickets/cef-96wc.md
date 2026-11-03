---
id: cef-96wc
status: open
deps: [ct-itcg, ct-9gmr, ct-qg8e, ct-2c0w, ct-31e2, ct-kn6d, ct-r8jd]
links: [ct-klyz, ct-4jms, ct-5kto, ct-77zb, cef-jh7i, ct-t906, ct-1mbc, ct-kw9b, ct-9gmr, ct-pocg, ct-64el, ct-n2cy, ct-tk10, ct-qg8e, ct-d0o0]
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

**2026-11-01T17:43:18Z**

publish_v21 live viewer release 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419 published to R2 and verified via HTTPS canary:archive (2026-11-01). Verified D1-D4 Parquet snapshots are staged at /private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-impl/cx_model_design/publish_v21/inputs/ (captures: 4,147,132 rows, readings: 1,349,139 rows, filename_readings: 1,311,075 rows, meeting_records: 24,430 rows, appearance_records: 66,483 rows) and unreadable provenance 20261101T153500+0000-34c66cf22e4550f910fa2805bf57a89d7edf05e7cdfcd1f3afe8545930055fff.jsonl is imported to R2; item (2) remote Basin Iceberg table commit/binding remains to sync remote catalog tables with publish-model.json.

**2026-11-01T20:08:15Z**

Correction to the 2026-11-01T17:43:18Z note. Its release facts were independently confirmed. Item 2 is not the only work left. Remaining: items 1-4 of the 2026-10-30T19:28:54Z note, the annex §4.6 child tickets and a durable copy of the inputs (local copy at .cache/archive-release/publish_v21/inputs). Basin work is ct-itcg; row-count explanation is ct-qg8e; CI runtime is ct-2c0w.

The owner confirmed approving the targets used for publish_v21. No device evidence is recorded and apps/site/archive-targets.json remains owner-gated with null ceilings, so A11 real-device timing stays open before archive-jobs.yml can publish. Owner rule: no further live publishes from scratch scripts (ct-9gmr).

**2026-11-01T20:47:10Z**

Owner decision 2026-11-01: B13 and B10 run unattended and out of band; they no longer gate the Phase 2 exit (annex §4.1). Offered and not approved, so they remain required: pinning Explorer CSVs as model inputs in place of native producers, deferring the HTML metadata chain from ct-m104, and removing ct-9gmr from this ticket.

**2026-11-02T00:36:42Z**

Owner decisions 2026-11-01: keep 448651e7 live until a fixed release ships; ZIP contents are the documents (ct-64el). Removal notices for the 7,266 lost links are decided after the rebuild.

**2026-11-02T00:40:43Z**

New blockers: ct-r8jd (runaway limit).

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: add all five publish gates before the next publish: key-by-key comparison with live where every difference has a recorded cause; a link rule (a published link redirects or shows a removal notice, never silently vanishes, covering the 7,266 lost links); one end-to-end receipts-to-release test; write-time refusal of missing required fields; producer proof for every input. Full model run on the Mac under the guard. Autonomy grant: Claude takes the release through merged, tested and live, including the pointer flip.

**2026-11-03T22:53:52Z**

Progress update 2026-11-03: Release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd is LIVE at https://congressional-data.spicygov.ai/viewer-publications/manifest.json (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419). All 5 publish gates passed (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), 7 gated lake snapshots exported and imported to Basin with producer proofs, full production-offline lane passed (10,967 passed on release-train), contract:archive and live canary:archive passed, and congressional-explorer-mcp (v0.5.1, 22 tables) verified live against the published pointer.
