---
id: cef-96wc
status: open
deps: [ct-itcg, ct-9gmr, ct-qg8e, ct-2c0w, ct-31e2, ct-kn6d, ct-r8jd]
links: [ct-klyz, ct-4jms, ct-5kto, ct-77zb, cef-jh7i, ct-t906, ct-1mbc, ct-kw9b, ct-9gmr, ct-pocg, ct-64el, ct-n2cy, ct-tk10, ct-qg8e, ct-d0o0, ct-8kl2, ct-082q]
created: 2026-10-28T05:00:43Z
type: task
priority: 1
assignee: mikewolfd
---

# Verify the live switch to one Explorer release

Give site and Congress MCP users the same release and preserve a known rollback point. The approved `e145d24c389e` publication verified the archive pointer flip, archive browser and MCP reads, and prior release `e4538f0064e1`. The public `/dashboard/` still selects the legacy Explorer publication. The remaining switch is to put that route on the qualified shared release and verify both live consumers. [e145 release](../docs/releases/2026-11-05-e145d24c389e.md) · [Cutover checklist](../docs/plans/engine-first-switch.md)

## Acceptance Criteria

- Identify the actual native inputs from `ct-gi01`, immutable release, active workflow bindings and commands, and deployed site revision. Preserve the exact catalog, receipt inventory, producer evidence, and SpicyRegs pins where required. Carry forward the accepted e145 and Basin evidence wherever the release, inputs, and job pins still match.
- Record the live `/dashboard/` and archive site readback from `ct-t915` and the `ct-m104` MCP readback against that exact live release. Record local checks separately. Use the existing five checks in `ct-tk10` and the checked-in publication path for a data change. Carry forward `ct-te1p` worker and logical body-key evidence within its storage-only scope.
- Account for B0 disposition, B7/B8 provenance, B9 listing baseline, active raw locks, scheduled capture, and Basin smoke, table binding, and maintenance validation through the cutover checklist and their owning records. `ct-1l1h` owns the raw lock readback and `ct-4jms` owns scheduled capture. Reuse the owners' evidence where its inputs and scope apply. B10 full rehash, B13 PDF copies, and the site performance gate remain deferred.
- Record the prior archive pointer, protected raw inputs, application revision, and any retained legacy artifacts needed for rollback. Hand off to `ct-5kto` after live acceptance and protection of those references. Keep the retirement and post-retirement verification in the same switch window under the existing cutover order. [Phase 2 order](../docs/plans/phase-2-annex-20261028.md#46-explorer-migration-and-data-coverage)

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

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

**2026-11-04T12:46:09Z**

Owner decision 2026-11-04: B10 (full re-hash) and B13 (PDF copy) are deferred as post-switch work with no date; they are not exit conditions for phase 2.

**2026-11-05T17:11:15Z**

Consolidated ownership from ct-8kl2/ct-98sm: retain actual production bindings, live selected release/site/MCP readback, raw provenance and previous-release rollback evidence. Use ct-tk10's maintained value/cause and link-continuity gates for current source/document changes. Preserve ct-te1p worker and storage-only logical body_key proof without treating its historical population totals as fixed across later semantic releases. Closing superseded trackers does not satisfy this live cutover gate.

**2026-11-05T23:55:26Z**

Wave 1/2 implementation closure transfers two remaining release responsibilities here. ct-t915’s implementation is accepted; verify the deployed native routes, legacy bookmarks, optional-load behavior and site/MCP agreement on the accepted immutable release, with the existing rollback references. ct-m104 owns the exact candidate and installed-reader checks.

ct-ud0b’s nightly approval and completed-candidate recovery implementation is accepted. After publication and reconciliation of remote main and canonical jobs, restore the retained 05:30 America/New_York Mac schedule. Observe a genuine qualifying additions-only run through all five gates; record its selected commit, daily result, gate outcomes and pre/post pointer. An unchanged run or safe refusal is an operational observation, not proof of automatic publication. Preserve a refused candidate and its reason. A crash before the producer record exists still needs head/ledger reconciliation before retry. Keep the scheduler disabled until release readiness.

ct-4jms remains the hosted scheduled-capture owner, ct-9lxf owns whole-operation disk/spill checks, and ct-5kto owns retirement after the live switch. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md)

**2026-11-06T18:43:09Z**

All independently executable cutover verification is complete at 282e815251de20faa302092c5658e79c89bd86c5. The live archive and hosted MCP readback select e145, while /dashboard/ still uses legacy publication 1b3f2ae1b4c5c0b3a4bdc2d9. Sixteen evidence/document checks passed, including accepted manifest/input hashes, actual Pages checkout revisions and availability/size/MD5 checks for all 25 prior-release assets. The November 6 13:21 America/New_York freshness check confirmed unchanged archive/legacy pointers and Pages c3ee2eec. Exact bindings, rollback references and owner checklist are in docs/releases/2026-11-06-cef-96wc-readback.md; durable results are under .cache/archive-release/implementation/reviewed-non-news-20261106/cef-96wc/. This commit is in the release-rollup branch, not yet main or a new deployment. ct-082q daily planning is now qualified; its older pending-pairs blocker is stale. ct-1l1h's authenticated 13:24 America/New_York readback returned an empty lock-rule list; the three required locks are absent, superseding its earlier authentication blocker. Its correction proposals remain unapplied.

Keep open. The sole root integrator owns main integration; ct-m104 owns the final native build, publication/deployment and same-release consumer acceptance. cef-96wc then completes live route/bookmark/rollback readback and qualifying Mac publication proof; ct-1l1h owns lock/header acceptance, ct-4jms scheduled capture, ct-31e2 hosted checks, and ct-5kto retirement after live acceptance. The final release owner retains B8/B9/Basin reconciliation and scheduler restoration. No deployment, pointer flip, schedule change or competing build ran here.

Independent GPT-6.1 Sol/xhigh review (/root/cef96wc_independent_review) read all four requested skills and APPROVED the exact commit as a documentation/evidence handoff; it confirmed the deployed-dashboard selection remains the unresolved causal boundary and required no tracked patch. Its only follow-up was the newer empty-rule lock readback, now reflected in this current note/handoff. Review: .cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/cef-96wc/REVIEW.md.

Independent review: APPROVE for the scoped work; remaining ticket acceptance is unchanged. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/cef-96wc/REVIEW.md).
