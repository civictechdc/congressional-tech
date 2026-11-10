---
id: ct-w2kf
status: closed
deps: []
links: [ct-6p6d, ct-07wr]
created: 2026-11-10T15:47:02Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine, performance, nightly]
---
# Engine: read each lake file once (read-through cache for immutable lake objects)

From the docspec-rs feedback root-cause analysis (cause A) and measurement M1 (root-cause/PLAN.md). Every statement that names a lake table reads it again from the object store: no object cache in src/storage/remote, and the Iceberg scan is one stream. In build c03c43da 44 statements that read a lake table take 545 of 895 s. M1: the 11 statements that read only captures take 144.9 s remote and 9.2 / 7.4 / 6.8 s on a local copy at 1 / 2 / 8 threads. Change: a read-through cache for immutable lake data files under the engine's Iceberg reader: one download per file per job, checked against the manifest size, later reads local. Check opendal's layers-foyer feature before writing one. Branch dx/object-cache in docspec-rs, cut from fix/nested-slice-bytes. Links ct-6p6d.

## Acceptance Criteria

A second scan of the same snapshot in one job issues no remote data request (counted in a test against a fake store); concurrent scans of one file share one download; results identical; cache bytes are admitted against scratch and removed with the job; engine check green. Outward: binaries, pin move, and one full-size build with the timing of the 44 lake statements before and after.


## Notes

**2026-11-10T16:39:20Z**

2026-11-10: NOT built. Checked in the engine repository: the one line (fix/docspec-one-line-20261109, f803ee6) already reads lake files once for managed jobs: src/engine/managed_job/snapshots.rs sizes and copies a snapshot input's whole read closure (metadata, manifest list, manifests, every live data file) and src/storage/custody.rs reads it back through a URI-to-retained-copy map with no fallback to the source. A cache on the pinned line would be a second copy of that. On the pinned line the gain comes from ct-07wr (captures as the model's first retained step). The engine-side mechanism reaches the pipeline when it moves to the one line (ct-x00f) and, for the model, to managed jobs (owner: write it up first).
