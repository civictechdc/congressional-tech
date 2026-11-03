---
id: ct-61ys
status: closed
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

**2026-11-02T16:58:23Z**

2026-11-02 impl-e2 r1b-det 4e2fb4ba (on integrate 0f4711bb): the memory-limit outcome is deterministic. On the 25 readings-bundle decision bodies: v21 17 memory_limit + 8 output_limit; deterministic 9 + 16; all 25 stay unreadable, and 8 change failure class. Lead decision: include in the release; the 25 bodies go into the shared mirror (they were only in spec-run's private bundle-raw); the bundle proof is run twice and must be identical; the 8 flips are recorded with raw evidence as a gate-1 cause.

**2026-11-02T17:03:05Z**

2026-11-02 spec-run: candidate-r1b 9faf86df = integrate 0f4711bb + r4-staging 70364b5f + r1b-det 4e2fb4ba; the bundle moves to bd87fc17; the bundle proof is deterministic (two runs identical, 8 differences, so no registry entry; the 25 bodies are re-decided in D2). The 8 flips are pipeline-data youtube_*.json files, 22.4-23.1 MB decoded, parsing at a 535-546 MiB peak (just over the old 512 MiB cap) and producing 10.9-14.2 MB of output (over the 8 MiB output cap); evidence in r1b-run/logs/r4/bundle-flips-evidence.json. Gap: v21 holds a completed xml reading for c90e782a (38.8 MB) that the 24 MiB bound now refuses. Decision: every html/xml/json compatible entry excludes bodies above the bound (a predicate), so they're recomputed; mirror bodies are stored in canonical form.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
