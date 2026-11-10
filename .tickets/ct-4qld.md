---
id: ct-4qld
status: open
deps: []
links: []
created: 2026-11-10T03:26:29Z
type: bug
priority: 1
assignee: mikewolfd
tags: [gate, release, links]
---
# Release gate link rule passes when a live link key answers a different file

Release build 2026-11-10 (candidate a70ebc3d1466 against live 630164505301): six House Financial Services PDFs (live rows 256823, 256827, 256829, 256831, 256836, 278162) were fused into candidate row 331783 and appear nowhere in the candidate. Their 7 link keys, 14 lookup keys and 13 addresses still answer, but with a different file (live key 28f7a541731b530b, 143,581 bytes, now opens hhrg-119-ba00-20260902-sd002.pdf, 186,557 bytes). None is in retired_links. The gate's link rule reported missing 0, dangling 0, ok: it checks only that every live key still exists. Reviewers found it, not the gate. Evidence: .cache/archive-release/release-20261110/causes/review-DE/REVIEW.md, .cache/archive-release/release-20261110/causes/review-capture-address/.

## Acceptance Criteria

The link rule refuses when a live link key answers a body that is not the live body, a recorded alternate of it, or a retired successor, and names the keys. A test plants the seven-way fusion and the gate refuses it. The rule's count on live-against-candidate for this release is recorded here.

