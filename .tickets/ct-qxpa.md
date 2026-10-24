---
id: ct-qxpa
status: closed
deps: []
links: [ct-gesp]
created: 2026-10-18T19:25:05Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Batch review export reads by Parquet row group

Review export loads entire Parquet row groups for individual source/document rows and repeats document selection across evidence pages. The 16-row cache does not bound or share row-group decoding.

Source: docs/youtube-coverage/research/scripts/view_document_filenames.py:516-558; apps/site/scripts/filename_reviews.py:28-41.

## Acceptance Criteria

Group requested rows by row group with a decoded-byte budget, and reuse each validated document selection across its evidence pages. Count reads on a multi-row fixture and show fewer decodes. Preserve complete-row matching, snapshot checks, evidence hashes and exported bytes; report measured cost without extrapolating fixture timing to production.

<!-- grade-followup:start -->
## Grade review follow-up

Include explicit Catalog.document input bounds, complete-row batch access and the memory/cache lifetime of Catalog.record/document/review_rows.

- Reject negative/out-of-range source rows and preserve shared-reader serialization and snapshot checks.
- Batch source/document row-group reads with a byte-aware lifetime and demonstrate fewer decodes on multi-row/multi-page fixtures without losing complete evidence.

[Function scope and checks: 4 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:581). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:34:06Z**

Complete record/document requests batch by row group under shared lock, with32MiBjoint Arrow row-group cache and explicit one-operation lifetime for oversized groups; source document bounds reject negative/out-of-range/noninteger rows. Export reuses one snapshot-issued exact complete-row selection across evidence pages, while each evidence hash/snapshot/signature remains checked.2member/3page fixture reads2groups instead of3 and selects once; all102focusedtests pass. Cache budget is distinguished from internal one-group decode allocation in receipt.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch d8z3b).
- Grades: proposal 74 → 70, work 84 → 84.
- Problem: Applies to the legacy file path only. The native path, the only one publication now accepts, builds one SelectedCatalogTable per row (filename_viewer.py:647-669), an O(rows) set of separate reads.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/d8z3b/d8z3b-verdicts.md:26
- Covered by: WS6 (ct-qqk2), which may delete the native v6 path.
- See docs/reviews/2026-10-24-ticket-audit/README.md
