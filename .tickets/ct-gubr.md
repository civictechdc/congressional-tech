---
id: ct-gubr
status: closed
deps: []
links: [ct-hnxb, ct-gesp]
created: 2026-10-18T19:21:16Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Separate viewer building from local search indexes

The publisher constructs the research viewer Catalog, which eagerly builds search-only state such as filter_text alongside publication data. This adds full-catalog work and retained memory before output generation.

Source: docs/youtube-coverage/research/scripts/view_document_filenames.py Catalog.__init__; apps/site/scripts/publish-filename-viewer.py publish.

## Acceptance Criteria

The publication path does not construct search-only indexes. Preserve all published values, row order, IDs, review bindings, and recovery behavior. Compare stage time and peak memory on the same bounded inputs; report actual savings.

<!-- grade-followup:start -->
## Grade review follow-up

Include optional reviewed-search masks, reusable document/position indexes, the bind complexity comment, and avoidable navigation/u32/ID-shard buffer copies in the minimal preparation data flow.

- Publication and offline review tools allocate only data they use; exact output and independent search/review behavior remain unchanged.
- Measure stage memory before/after; preserve full navigation readback through bounded reads or mmap, and retain explicit endian/range semantics.
- Reuse indexes without lossy member comparison; no dependency on the separate decoded-memory implementation is required.

[Function scope and checks: 8 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:358). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:34:06Z**

Publication and identity CLI skip search filter indexes; reviewed masks initialize lazily; binding reuses document/uint32 position indexes and preserves complete member sorting. Group/preferred/u32 and ID-shard output avoid buffer copies; navigation streams full exact verification.25000-source fixture saves1525312retainedArrowbytes (filterbytes1525000);200000-source navigation peak8973165→992970bytes with same hashes and tracedtime2.008→2.409s. Receipt+script tracked.102tests pass including independent search behavior.

## Audit 2026-10-24

- Verdict: SUPERSEDED (batch d8z3a).
- Grades: proposal 75 → 75, work 78 → 78.
- Problem: The criterion holds through its successor, but the measured savings apply only to the test-only v5 generator.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/d8z3a/d8z3a-verdicts.md:88
- Covered by: WS10 (ct-r6xw).
- See docs/reviews/2026-10-24-ticket-audit/README.md
