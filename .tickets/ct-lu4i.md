---
id: ct-lu4i
status: closed
deps: []
links: [ct-3djs, ct-ylaw, ct-hm4b]
created: 2026-10-18T19:44:01Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Make catalog storage operations explicit

Catalog publication has a generic write fallback when conditional selection is unavailable. LocalStore.put also uses check-then-replace for immutable bytes; R2Store mixes namespace-specific policies. Small-object reads and key ordering have no explicit bounds.

Sources: catalog_publication.py:153-156; catalog_cache.py:53-77; r2.py:164-218. The maintained derived-file and selector routes already have stronger checks.

## Acceptance Criteria

Require conditional selector and exclusive immutable capabilities explicitly; unsupported adapters fail before writes. Exercise two-writer conflicts without replacing selected data. Keep large tables on file APIs, bound small selector reads, and stream listing where order is not required. Preserve caller-required ordering and missing/partial-read behavior.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 5 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:481). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:18:42Z**

Removed generic selector write fallback; required conditional-selector/exclusive-derived methods fail before writes. LocalStore immutable small writes use exclusive link, selectors read at most 1MiB+1 with remote declared length checks. Local listings stream by default; ordered receipt/metadata replay sorts explicitly. Tests preserve missing/partial behavior and concurrent selector/small immutable/file conflicts. 134 tests + 5 subtests pass.

**2026-10-18T21:05:17Z**

Final integration found a benchmark-only regression: MirrorOverlay retained the mutable verified-file dictionary, and catalog validation later enriched it with rows/catalog/key. Unchanged source bytes then falsely failed the input snapshot check. Reopened for a snapshot of the original hash/size facts; the issued custody proof still returns to its caller unchanged.

**2026-10-18T21:07:54Z**

Fixed the final integration regression by storing independent hash/size facts in MirrorOverlay while returning the same issued custody proof. Independent review approved. A dedicated enrichment-versus-byte-change regression and the complete core benchmark module pass; 42 related offline checks pass. No source bytes or production run changed.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch d8z3b).
- Grades: proposal 85 → 85, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
