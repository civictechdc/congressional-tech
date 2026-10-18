---
id: ct-bs70
status: closed
deps: [ct-lvvr]
links: [ct-p6aq, ct-zika, ct-qyey]
created: 2026-10-18T19:28:38Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Avoid repeated and unused browser range reads

Uncached source IDs download their full prefix shard repeatedly. selected() reads broad min/max row spans, and oversized merged prefetches can bypass cache admission then be fetched again.

Source: apps/site/src/components/filename-catalog.mjs:176-193,231-241,319-338. These are static amplification paths, not measured savings.

## Acceptance Criteria

Reuse prefix-shard reads within the shared cache budget, group requested positions by row group, and limit prefetch to admitted ranges. Count transferred bytes/requests for sparse details and repeated same-prefix IDs. Preserve position, digest, cancellation and exact-result checks; do not create new unbounded caches.

<!-- grade-followup:start -->
## Grade review follow-up

Include immutable-manifest fetch policy, admitted range prefetch, physical decode amplification, sparse selection, same-prefix shard reuse, and modern-versus-archived navigation cost.

- Mutable pointers remain fresh; immutable manifests can cache without violating identity.
- Count exact requests/bytes/chunks on sparse and oversized-prefetch fixtures; no redundant uncached prefetch transfer.
- Historical navigation remains supported and equal while modern detail avoids legacy arrays; strict range and bound checks remain.

[Function scope and checks: 11 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:274). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:18:51Z**

Dependency ct-lvvr completed first. Added budgeted prefix-shard reuse, immutable manifest caching, admitted-only prefetch and sparse row-group column assembly. Controlled sparse/prefetch/shard counters and unavoidable physical decode boundary recorded in browser.md. Catalog/publication suite 20 passed, new sparse fixture separately passed after its adversarial assertions were added.
