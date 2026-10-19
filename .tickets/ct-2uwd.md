---
id: ct-2uwd
status: in_progress
deps: [ct-2d3k]
links: [ct-d3un, ct-vxzu]
created: 2026-10-19T16:40:41Z
type: task
priority: 1
assignee: mikewolfd
tags: [overlap-followup]
---
# Consume one verified mapping write receipt

publish_corpus_recovery_mappings.py:47-57 reconciles and reads complete mapping bytes again after generic guarded-client full readback, ignoring its exact receipt. Mapping control reads remain unbounded; outer read failure can also obscure the prior uncertain failure. Three-way additions merge and fresh prior edits/deletions must stay.

## Acceptance Criteria

- Consume exact issuing-client/key/body/current-version receipt; retain complete bounded plain-client fallback.
- Use the supported accepted mapping 16 MiB ceiling and reject oversize/truncated/malformed reads before publication.
- One mutation attempt, original ETag, canonical additions, fresh edits/deletions, conflict refusal and before/proposed retained bytes remain.
- Dual PUT/reconciliation errors retain both causes without formatting credentials.
- Count one full successful guarded mapping readback and prove foreign/stale/missing receipts trigger independent verification.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: scripts/dispatch_corpus_recovery_publication.py:259:run.mapping_phase, scripts/publish_corpus_recovery_mappings.py:14:publish_mappings. See docs/package-overlap-rescore-20261019.md for the full grade map.

**2026-10-19T16:56:07Z**

Prioritized for efficiency and architectural debt per user direction. Require measured work/resource changes and simpler ownership; preserve behavior and data. Grok/Cursor is concurrently refactoring /scripts; use this ticket as its acceptance checklist and avoid duplicate implementation. Keep open until reviewed evidence passes.

**2026-10-19T17:00:42Z**

Related reshape ct-vxzu shares the plain exact-byte reconcile and consumes _verified_transfer. It does not close this ticket. publish_mappings still consumes the guarded readback here.

**2026-10-19T19:40:28Z**

Local implementation ready for independent review. Shared congress_api.retention.control_documents preserves publisher reader AST and 4/16/32 MiB policy; mapping reads/proposals enforce accepted 16 MiB. Real guarded receipts checked for issuing identity/key/body/current version; unusable receipts trigger bounded independent verification. Plain lost-ack reuses exact readback: 3 to 2 full GETs (206 to119 local fixture bytes), one PUT/original IfMatch/result and saved-byte hashes preserved. Dual errors retain both exception objects; guarded failures receive no outer retry/read. Focused tests107 passed +2subtests; bounded comparison and hashes under primary output/efficiency-debt-20261019/mappings; report docs/experiments/efficiency-debt/mappings.md. Keep in_progress pending independent review.
