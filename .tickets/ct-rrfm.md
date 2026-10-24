---
id: ct-rrfm
status: closed
deps: []
links: [ct-zkzt, ct-1dsp, ct-sv16, ct-2wsw]
created: 2026-10-18T19:44:01Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Bound alias indexing work within one preparation

catalog_aliases retains global URL/resolution/body-version maps and scans twice; index_recoveries adds a third scan and source-to-group list. recovery_index removes recomputation between phases, but does not bound one build. Measure and bound this state; dependent scans may remain when they are the clearest correct method.

## Acceptance Criteria

- Count source scans and peak state on bounded high-cardinality/high-fanout fixtures, define a memory policy, and report scratch/time tradeoffs for any spill or shared-index approach.
- Preserve invalid/self resolutions as conflict evidence, ambiguous-target/body refusal, saved-original precedence, accepted precedence, stable output ordering and exact source/group mapping.
- Keep exact input hashes or a valid process-local proof; do not trade integrity for fewer passes. No fixed one-pass target or claim about the unknown historical OOM stage.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 2 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:613). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:31:06Z**

Returned to open while finishing active reader/resource/export batch; alias memory-policy implementation not yet started.

**2026-10-18T20:39:55Z**

Replaced global alias/source/group maps with disposable SQLite index:8MiBcache,FILEtempstate,32MiBaccountedstatusoutput refusal; groups read throughmmap. Source Parquet scans measured3→1 on18001rows/12000originals/6001bodyversions; output exact3435461bytes/sameSHA. Pythonpeak15477832→9650842bytes;RSSnearlyunchanged;scratch5488640bytes;time0.917→1.597s. Invalid/self/null conflicts, ambiguity, saved/accepted precedence/order/mapping retained.101tests+2subtests and final68tests pass. Receipt documents output-sized memory, tradeoffs and separate ct-hnxbdecodedbudget.

**2026-10-18T20:44:57Z**

Independent review followup: exact final publisher JSON byte ceiling now includes header/brackets/separators and ASCII escaping, using already counted entry sizes plus a tiny empty-array header (no second output walk/copy). Empty/multiple/Unicode boundary fixtures match publisher bytes.42focusedtests pass. Corrected benchmark warm module initialization equally; final Pythonpeak15.48→9.53MB, time0.924→1.618s, headercheck0.000087s. Receipt refreshed.

## Audit 2026-10-24

- Verdict: SUPERSEDED (dormant in production) (batch d8z3b).
- Grades: proposal 72 → 68, work 72 → 72.
- Problem: The ticket's own receipt showed the SQLite spill made preparation 75% slower (0.92→1.62 s) with RSS "nearly unchanged"; only the tracemalloc peak fell.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/d8z3b/d8z3b-verdicts.md:30
- Covered by: WS11 (ct-2wsw) and WS6 (ct-qqk2), which removes the v1 alias path.
- See docs/reviews/2026-10-24-ticket-audit/README.md
