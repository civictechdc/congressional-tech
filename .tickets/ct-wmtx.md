---
id: ct-wmtx
status: open
deps: [ct-xl0y]
links: []
created: 2026-10-20T18:59:59Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency]
---
# Keep native metadata work bounded as retained history grows

The storage review found full historical-row replay on a cold lifecycle cache miss, whole cached-value cloning on commit, and inventory work across retained snapshots. Measure cold reopen, warm commit and alternating datasets with fixed payload and changed rows; remove demonstrated duplicate work using the existing native owner.

## Acceptance Criteria

Report time, metadata rows/bytes, allocations and catalog calls as history grows. Preserve exact selected releases, old readers, incomplete operations and retention roots. Use existing Iceberg/catalog components; no second SQL authority or automatic expiry. Adopt a change only with local preservation tests and measured benefit, otherwise retain a bounded evidence-based conclusion.


## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F4. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.
