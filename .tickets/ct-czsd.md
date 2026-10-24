---
id: ct-czsd
status: closed
deps: [ct-2ukk]
links: [ct-2ukk, ct-mi03, ct-13g5, ct-oc2g, ct-a3le, ct-8ax6, ct-xu1o, ct-dzyf, ct-aia9, ct-sb0s, ct-te1p, ct-13cn, ct-n6lj, ct-dmca, ct-8kl2, ct-gziq, ct-gi01, ct-2yl5, ct-bwac, ct-q2ht, ct-7uit]
created: 2026-10-20T02:20:21Z
type: epic
priority: 1
assignee: mikewolfd
tags: [incremental, efficiency, debt]
---
# Make archive-to-viewer updates fully incremental

Small updates should finish without reconstructing unrelated data. This changes storage and publication behavior; it is not a cleanup or a faster spelling of rebuild.

## Design

Keep acquisition, document interpretation, grouping policy and conditional publication with their existing owners. Replace only the whole-dataset storage and execution boundaries that prevent incremental updates. Reuse qualified maintained components; do not introduce a parallel dataset engine, generic scheduler or permanent dual writer.

The user selected `docspec-rs` and enabled Basin Catalog on the existing
`congressional-tech-raw` bucket. DocSpec owns typed data versions and recovery;
the existing application selector chooses one coherent set of completed versions.
Prepare changed bounded partitions as immutable native runs and reuse unchanged
pins. Keep application routing metadata bounded as the catalog grows.

The earlier postponed plan remains historical evidence. Its full-rebuild fallback
and complete-file exports are not part of the incremental update path. Local
proofs and catalog configuration do not establish production adoption.

## Acceptance Criteria

- Cover additions, corrections, deletions, evidence/state edits, group merges/splits, mappings and explicit rule upgrades. Preserve exact source bytes, identities, nested provenance and review decisions.
- Process changed records and the complete affected dependency scope; retain untouched data by verified version. Validate through the same boundaries without rescanning every old payload.
- Resume completed work after worker loss. A global rule change may affect every record, but runs in bounded resumable batches; no restart-from-zero fallback.
- Each child records a relevant baseline before edits, characterizes preserved behavior, measures its improvement and migrates its actual callers. Delete superseded internals after cutover; retain historical evidence.
- No change performs no dataset writes. Compaction and full exports are optional, never correctness prerequisites. Existing snapshots seed adoption without refetching or reclassifying them.
- Complete ct-2ukk before claiming end-to-end qualification. Unknown dependency scope fails explicitly; it must not return partial success or force a full rebuild.

## Notes

**2026-10-21T07:28:00Z**

19 of 20 child tickets under `ct-czsd` are now closed and verified on `main` (`55ba3479`), including native v6 viewer preparation/verification (`ct-ihve`, `ct-87n4`), incremental partition/dependency reuse (`ct-si9g`, `ct-v5kb`, `ct-365w`, `ct-upte`, `ct-7e7q`), oversized row preservation (`ct-rcs8`), and retirement of the 3 legacy full-table Parquet writers (`ct-dat9`). Only live production cutover qualification (`ct-2ukk`) remains `in_progress`.

## Audit 2026-10-24

- Verdict: In progress at review time; graded in prose, not in the batch table.
- Grades: proposal 81 → 70, work 78 → 70.
- Problem: It never measured the production cost it set out to remove; 19 of 20 children closed on local and fixture evidence while production stayed unchanged, and its demand for exact adoption of derived snapshots drove most of the retention package's growth.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/czsd/czsd-verdicts.md:66; docs/reviews/2026-10-24-ticket-audit/batches/czsd/czsd-greenfield.md:68
- Status: Closed as superseded by the simplification plan (Step 0 ct-q2ht, WS7 ct-7uit): its remaining goal, incremental archive-to-viewer updates with exact preservation and resume, is now WS7 (incremental catalog updates on the engine, checked against the Step 0 rebuild oracle). The ct-2ukk cutover is replaced by WS6 (ct-qqk2) and WS7, the hosted runtime check is ct-j9c4, and the quadratic worklist goes with `source_observations` in WS7. One residual is not in the plan: `Archive.__init__` lists every `receipts/` object per run (`raw_archive.py:672`), which the greenfield pass rated minor.
- See docs/reviews/2026-10-24-ticket-audit/README.md
