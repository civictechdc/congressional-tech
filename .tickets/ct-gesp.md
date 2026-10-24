---
id: ct-gesp
status: closed
deps: []
links: [ct-fw0m, ct-eauq, ct-hnxb, ct-gubr, ct-qxpa]
created: 2026-10-18T19:44:01Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Close preparation streams on success and failure

Blocks.close skips stream.close when flush fails, and observation construction does not own both writers across all exceptions. Fetch response bodies and helper Parquet/baseline readers also need explicit lifetimes. Handle cleanup belongs here; staging-file ownership and installation belong to file_custody/builder_target.

## Acceptance Criteria

- Explicitly close every acquired writer, response and reader on success or failure; preserve the primary exception and distinguish finalization from abort.
- Inject second-writer-open, serialization, compression, write and readback failures. All acquired handles close, unfinished blocks are not flushed during abort, and no success descriptor accepts partial work.
- Successful artifact bytes and exact verification rules remain unchanged; partial-file retention/removal stays with the owning stage.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 9 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:342). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:34:06Z**

Added explicit resource lifetimes for block finalization/abort, Catalog readers/constructor failure, builder/repack readers, detail readback/count generators, baseline hashing and fetch responses. Cleanup errors preserve primary error notes; abort never flushes incomplete blocks; observation descriptor accepted only after readback. Atomic verified fetch retains prior selector and named failure evidence.102focusedtests pass with second-open/serialization/compression/write/readback/close/download fault injection. Remaining decoded working-set policy belongs ct-hnxb.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch d8z3a).
- Grades: proposal 87 → 87, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
