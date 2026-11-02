---
id: ct-61ys
status: open
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

