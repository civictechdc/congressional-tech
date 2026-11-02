---
id: ct-61ys
status: in_progress
deps: []
links: []
created: 2026-11-02T15:35:26Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [readings, determinism, phase2]
---
# Parser worker memory cap gives nondeterministic readings for bodies near the limit

spec-run 2026-11-02: body c90e782a (38.8 MB XML) came back status memory_limit in some identical re-reads and completed as xml in others, under the 512 MiB parser worker cap. A reading that depends on run-to-run memory isn't reproducible, so compatible-version proofs and the C3 byte-identity goal can flake.

## Acceptance Criteria

The same body and parser version always give the same reading: decide the limit outcome deterministically (e.g. by a size or complexity bound checked before parsing, or a cap with headroom proven on the largest bodies). A test re-reads the largest bodies N times and gets identical rows. Measure how many bodies sit near the cap.


## Notes

**2026-11-02T16:39:19Z**

2026-11-02 (lead): now blocking. The readings-bundle proof failed again on candidate-r1b (c90e782a readable this time). Retries won't do for the release: impl-e2 is making the memory-limit outcome deterministic on r1b-det (parser_worker/process_resources, in bundle_version), joining this release's version move, with an N-times re-read test on the largest bodies.
