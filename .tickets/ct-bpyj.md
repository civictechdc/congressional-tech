---
id: ct-bpyj
status: closed
deps: [ct-2d3k, ct-piku, ct-u7gg, ct-3g69, ct-du3e, ct-tenb]
links: [ct-d3un, ct-esm4]
created: 2026-10-19T16:40:41Z
type: task
priority: 1
assignee: mikewolfd
tags: [overlap-followup]
---
# Share accepted viewer plans across local and cloud publication

Cloud attempts accept recovery-prepared.json and issued inventory, while local dispatcher prepares a separate file phase then calls upload without validation (dispatch225-246; publisher299,369,396). This repeats local hashes/status derivation and leaves state ownership spread across nested dispatcher adapters and controller dictionaries. Shared transfer client exists; accepted-plan ownership does not.

## Acceptance Criteria

- A common named accepted viewer plan contains protected identities, source/catalog pins, accepted recovery result, exact file inventory and original release/selector conditions.
- Local preparation accepts its existing pair-validation proof and returns that plan; cloud preparation retains required GitHub artifact acceptance.
- Both routes consume accepted status with no second recovery scan and reuse issued local file proof only under unchanged custody.
- Move domain phase/Store adapter construction behind an explicit maintained entry point; preserve sealed-body coverage, local lock, pins, local phase evidence, and original-condition resume.
- Full/recovery/no-op/superseded/failed outcomes remain inspectable; a fresh process independently verifies restored files.
- Exercise real local builder/upload integration rather than only stubbed phase reuse; compare unchanged values/hashes and meaningful hash/index counts.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: apps/site/scripts/publish-viewer-r2.py:198:recovery_for_publication, apps/site/scripts/publish-viewer-r2.py:204:select_recoveries, apps/site/scripts/publish-viewer-r2.py:285:upload, scripts/dispatch_corpus_recovery_publication.py:94:run, scripts/dispatch_corpus_recovery_publication.py:267:run.prepared_phase, scripts/dispatch_corpus_recovery_publication.py:274:run.publication_phase, scripts/viewer_publication_attempt.py:153:publish. See docs/package-overlap-rescore-20261019.md for the full grade map.

**2026-10-19T16:52:02Z**

The ct-du3e fix preserves proposed versus selected bytes through verified commit. Store.read and Store.put still hide source custody in nested adapter methods; both reviewed rows remain open here. See final gradebook for the distinction.

**2026-10-19T16:56:07Z**

Prioritized for efficiency and architectural debt per user direction. Require measured work/resource changes and simpler ownership; preserve behavior and data. Grok/Cursor is concurrently refactoring /scripts; use this ticket as its acceptance checklist and avoid duplicate implementation. Keep open until reviewed evidence passes.

**2026-10-19T17:00:42Z**

Related reshape ct-esm4 packages corpus recovery and pins the files that execute. Related only. It does not close this ticket.

**2026-10-19T20:15:20Z**

Local implementation ready for independent review at refreshed 014303e baseline. One AcceptedViewerPlan reuses issued inventory/status for local/cloud; artifact checks stay cloud-only. Original input/release conditions remain in the existing continuation before upload; a fresh process rehashes 271 files once. Domain Store/phases moved to corpus_recovery.publication; runtime admission/lock/pins/guard stay in the dispatcher. Real seven-source builder/upload comparison: 269 payloads and manifests/status/results/original conditions match; observed output helper hash passes fall 823 to 270, bytes 279,129 to 50,688. Total recovery scans remain one, moved into preparation. Adds three GETs and three fsyncs; no speed/memory gain claimed, and the tiny arm is slower. 222 distinct focused checks plus seven subtests verified after isolated PyYAML environment repair. Primary accepted-plan evidence and committed report/JSON retain limitations. Remain in_progress pending independent review.

**2026-10-19T20:19:49Z**

Independent code and evidence reviews approved 0757790. Integrated at e9b18a9: 251 local tests and 7 subtests passed in one final run. Actual 269 payload hashes per arm, manifests/results and original write-condition counts match. Known output hash helper passes fall 823 to 270; one recovery scan moves earlier. The tiny candidate is slower and adds 3 GETs/syncs; no speed or memory gain claimed. Shared plan and maintained domain entry point reduce duplicate acceptance work. Evidence: docs/experiments/efficiency-debt/accepted-plan.md.
