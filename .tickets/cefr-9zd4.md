---
id: cefr-9zd4
status: closed
deps: []
links: []
created: 2026-10-27T14:08:33Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B9: verify raw listings and stage append-only baselines

## Acceptance Criteria

Native SQL joins listing to receipts, old captures and verification; detect missing/replaced objects, hash25sample plus orphans, stage verified provenance; first live run remains owner-gated.


## Notes

**2026-10-27T15:38:48Z**

Local done: native listing/receipt/index/verification joins, orphan reports,25-body sample and staged create-only provenance. All CODE/ARCH findings fixed; independent fix review APPROVE;17 native/local regression cases and20 owner-command/ratchet checks pass. First live baseline and weekly maintenance integration remain owner/engine gates; commands in b9-b12 README.
