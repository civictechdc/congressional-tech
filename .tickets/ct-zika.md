---
id: ct-zika
status: closed
deps: []
links: [ct-lvvr, ct-bs70, ct-hnxb, ct-15wc]
created: 2026-10-18T19:44:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Account for browser logical decode and full-copy memory

Observation parts are capped at 1 MiB but decode joins and parses complete logical blocks; normalization and explicit full-copy add result/worker-clone/JSON allocations. Define transient admission separately from retained caches, eliminate redundant part copies, and specify exact handling of values larger than the ordinary budget. Do not silently truncate or change full-copy fidelity.

## Acceptance Criteria

- Fixtures cover one logical value larger than the part cap, split UTF-8, large reference lists, nulls, duplicates and exact full-copy ordering.
- Account for parts, joined bytes, text, objects, scalar output and worker/clipboard copies; document the unavoidable full-result cost.
- Before introducing a hard rejection, specify the supported exact-value route and visible resource-failure criterion; routine detail stays lazy and full copy remains explicit.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 9 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:691). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:23:57Z**

Streaming UTF-8 removes retained decoded-parts and joined-block byte copies. Logical/value/clone/full-JSON/clipboard costs and 16MiB ordinary accounting threshold documented without silently rejecting/truncating exact values. Allocation RangeError directs to complete source Parquet. Shared budgeted block decoding preserves >1MiB Unicode value,10k refs,nulls,duplicates/order;19catalog/worker tests passed.
