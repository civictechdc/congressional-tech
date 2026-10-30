---
id: ct-oun5
status: closed
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


## Notes

**2026-10-30T16:16:17Z**

Completed ss-vfgz (C0), ss-iwqu (C3), and ss-6jg6 (C4) in /Users/mikewolfd/Work/wt/ds-engine-first on branch impl/engine-first-20261027 at commit b368968384c914a6621d43d1ba754d04d4c70a1d. Built release binary target/release/docspec (--locked --release --features remote --bin docspec) with SHA-256 c27077db7a8b60fde569bddcf7b9948032bcd4baec5253d5490e31a3c4687401 and reported to coordinator 9e04a2e5-de01-4df4-8c0d-eaaf0a941bbc for Session 3 runtime pinning.

**2026-10-30T16:16:46Z**

Completed and 3-hat reviewed in /Users/mikewolfd/Work/wt/ds-engine-first (impl/engine-first-20261027 @ b368968384c914a6621d43d1ba754d04d4c70a1d; darwin-arm64 release binary SHA-256: c27077db7a8b60fde569bddcf7b9948032bcd4baec5253d5490e31a3c4687401): C0 (ss-vfgz: gc.enabled=true default & drop 2MiB/2048-row remote write caps), C3 (ss-iwqu: byte-deterministic Parquet export across threads/batches/permutations/spills), and C4 (ss-6jg6: ConnectedComponents binary keys, smallest-member component_id, and 4M-node/2M-edge 256MiB budget).
