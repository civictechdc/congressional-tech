---
id: ct-sv16
status: closed
deps: []
links: [ct-idhg, ct-jl1m, ct-rrfm]
created: 2026-10-18T19:21:16Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Measure complete publication costs by stage

Current evidence separates a historical 34m55 preparation from 2m44 transfer/proof, but does not time the new repeated hashes, serialized journal operations, or largest decoded records. The failed full Linux viewer attempt has no confirmed failing internal stage.

Use existing stage events and retained evidence; do not infer the OOM cause.

## Acceptance Criteria

Record stage time, sampled process-tree memory, scratch, bytes read/hashed, and request counts for a bounded authorized run. Keep failure evidence and exact input/runtime pins. Report successful publication, unchanged poll, and explicit retry separately; no automatic resource-limit increase or retry.

<!-- grade-followup:start -->
## Grade review follow-up

Add bounded-fixture decode-pass and SQLite-reference lookup counts when examining preparation verification costs; separate necessary integrity work from redundant representation/lookup work.

- Attribute measured costs to named stages and exact pinned inputs; do not infer the unknown full-catalog OOM stage.
- Keep verification semantics fixed while evaluating lookup batching or serialization changes; a small helper may remain unchanged with documented cost.

[Function scope and checks: 2 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:622). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:16:48Z**

Completed bounded pinned fixture measurement with reproducible scripts/measure_publication_control.py --checkout/--source/--source-manifest-sha256/--output and controlled request latency. Tracked receipt separates accepted preparation, successful publication, unchanged poll, deliberately failed explicit resume, explicit later resume; records stage time/process-tree RSS/scratch/hash-helper bytes/full remote adapter bytes/request counts/decoder entries/SQLite SELECTs/state serialization/fsync. Native IO/internal hash exclusions explicit; full Linux OOM remains unknown and untouched. Focused runner passed; baseline command/input pins documented in docs/experiments/publication-remediation/control.md.

**2026-10-18T20:57:03Z**

Measurement refinement: each timed command stage now starts with a cold source-identity cache, matching separate prepare/publish/no-op/resume CLI processes while preserving within-command reuse. Receipt explicitly excludes interpreter/import startup and actual GitHub Actions setup. Re-ran exact <=1MiB fixture pin b74045a6dbddaab6a3a53a75071d36c1098a1bacd3da26f3ea361709a89ba6d1 at 1ms modeled request latency; all five stages retained expected outcomes and positive source/full-integrity hash bytes. Smoke receipt /tmp/publication-control-cold-command-stages/costs.json. Root will retain final alternating-pair comparison; no production inference.
