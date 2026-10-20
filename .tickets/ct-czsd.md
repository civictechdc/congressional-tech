---
id: ct-czsd
status: in_progress
deps: [ct-2ukk]
links: []
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
