# Remaining package overlap and publication reassessment

Baseline: `90982181ad95366c12bb08d2b9789ea4f9042216`. Parent: `ct-d3un`.

## Decision

Keep the existing package boundaries. Share small rules only where inputs,
outputs and failure behavior match. Fix the concrete publication defects found
while independently reassessing all 168 entries in the original below-B+ report.
Local tests and independent review are the merge gates; do not wait for CI.

## Priority and dependencies

| Priority | Ticket | User benefit and scoped change |
| --- | --- | --- |
| 1 | ct-xmo8 | A reader stays on one catalog after a worker failure. Pin the accepted catalog for retries. |
| 1 | ct-u7gg | Avoid repeating completed file hashes and table-reference checks. Carry existing issued proofs through R2 reads and local publication. |
| 1 | ct-lzck | Release failed HTTP responses and show uncertain local writes without claiming remote acceptance. |
| 2 | ct-3g69 | Release catalog readers on success and failure; remove an unused alternate selection helper. |
| 2 | ct-yifn | Apply one body-key digest/shard rule across three retained-evidence consumers. |
| 2 | ct-9a6x | Keep GPO CSV ordering and bytes while reusing the existing atomic CSV writer. |

Two additional P2 fixes complete restored-phase path confinement (`ct-tenb`) and keep proposed selectors separate until verified commit (`ct-du3e`). These preserve ownership and diagnostic evidence; current guards already refuse incomplete publication.

All implementation tickets depend on audit `ct-2d3k`. They can run independently;
`ct-us67` depends on all eight and owns integration, final grades and cleanup. The
epic depends on that qualification ticket. Worktrees isolate edits; keep fewer
than ten tickets in progress.

## Ownership audit

| Area | Decision and evidence at baseline |
| --- | --- |
| Cache decoding | Already shared by `congress_shared.youtube_cache`. Keep I/O, missing-file behavior and transformations with each consumer. |
| Configuration | Already split into resources, paths and CLI logging. Preserve compatibility exports and CSV row order, which controls cache filenames. |
| Source categories | Already centralized in the Congress adapter. Source interpretation and normalized meeting models have different responsibilities. |
| Download and retry | Prior cleanup already shares Congress HTTP, Senate candidates and synchronous R2 body retries. Keep provider-specific retry, absence, bounds and evidence rules. See `download-retry-audit.md`. |
| Retained body keys | `filename_aliases.py:38`, `document_evidence.py:129`, `document_index.py:2277` repeat the same digest/shard test. Share a pure parser in retention, keeping each caller's refusal behavior. |
| CSV retention | `retention/gpo.py:27-43` repeats `retention/tables.py:37-48`. Delegate the byte-writing mechanics; GPO still selects dataclass fields and sorts package IDs. |
| JSON and gzip writers | Keep distinct serialization: ASCII escaping, separators, newline, NaN policy, streaming and gzip headers differ. TinyDB uses unique temporary files and fsync; other writers have different ownership and failure cleanup. A generic writer would require policy switches without an established common behavior. |
| Catalog proofs | `retention/r2.py:332-333` spreads an issued `VerifiedFile` into a plain dict; `document_index.py:2656` drops issued validation. Preserve those checked objects only under their existing custody checks. Serialized facts must not become authority. |
| Catalog reader lifecycle | `document_index.py:685-713` opens two readers without explicit closure. Close on all paths. `selected_filename_path` has no maintained callers; remove the unused route after inventory. |
| Browser readers | Keep local and static delivery paths, and their different recovery/review failure policies. Fix retry identity in `filename-client.mjs`; avoid another reader abstraction. |
| Domain models and native fetch | Keep normalized meeting models separate from exact source models; keep Rust byte transfer separate from Python admission/retry policy. No change to source storage, acquisition or classifier behavior. |

The audit inspected maintained Python `src` trees and current callers, not
`build/lib` copies. An exact-body AST scan found no cross-package duplicate
functions of six or more source lines in those trees. This is a narrow clone
check, not proof that all semantic overlap is absent. The decisions above come
from caller and behavior traces as well as the independent publication review.

## Preservation and verification

- Preserve on-disk bytes, row order, source observations, catalog identity,
  review states and conditional-write authority.
- Prove exact CSV bytes against the old writer, including Unicode and CSV
  escaping. Test replacement failure leaves the prior destination intact.
- Count redundant SHA/reference passes on the actual R2-to-retention and local
  publication routes. Reject changed custody and plain restored proof claims.
- Test worker restart after a mutable pointer changes; keep explicit snapshot
  selection, cancellation and stale-worker handling.
- Test response/reader cleanup at failure boundaries and bounded status reads.
- Independently review each patch. Run focused local tests, then the maintained
  `production-offline` suite once on the integrated code and relevant browser
  tests/build smoke. Do not reacquire sources or rerun full-corpus qualification.

The practical improvement is simpler ownership, fewer repeated integrity passes
and corrected failure behavior. Whole-run speed or memory gains require matched
measurements; this cleanup does not claim them.

## Publication grades

Three independent reviewers cover consumer (57), control (67), and preparation
and storage (44) entries using the original six-dimension rubric. Preserve the
original entry identity, all old grades and current source references. Closed
tickets are not proof. Distinguish resolved items, concrete remaining defects
and intentional costs. Later final evidence records the effect of this batch;
remaining large memory, journal and local-controller work gets separate tickets
with measurement and preservation requirements.
