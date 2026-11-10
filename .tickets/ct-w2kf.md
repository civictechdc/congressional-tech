---
id: ct-w2kf
status: open
deps: []
links: [ct-6p6d]
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

