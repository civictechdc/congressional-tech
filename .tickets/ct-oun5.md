---
id: ct-oun5
status: in_progress
deps: []
links: []
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
external-ref: ss-vfgz,ss-iwqu,ss-6jg6
parent: ct-77zb
tags: [phase2, external, docspec-rs, track7]
---
# T7.2 (docspec-rs): Complete engine Phase-2 items C0 (gc.enabled & drop write caps), C3 (ss-iwqu), and C4 (ss-6jg6)

External repository tasks in docspec-rs / spicy-stack (docs/plans/bindings-20261025.md §3.3 & docs/plans/phase-2-annex-20261028.md §4.1):
- C0 (ss-vfgz, ds/storage.rs): Default table creation to gc.enabled = true and drop remote write caps.
- C3 (ss-iwqu): Guarantee byte-identical Parquet export across thread counts, batch sizes, and forced spills so the model profile no longer pins the runner class.
- C4 (ss-6jg6): Emit dense integer component IDs from ConnectedComponents.

## Acceptance Criteria

docspec-rs tickets ss-vfgz (C0), ss-iwqu (C3), and ss-6jg6 (C4) are implemented, verified by scripts/check, and bumped in congressional-tech's runtime pin.

