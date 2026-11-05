---
id: ct-m56x
status: closed
deps: []
links: [ct-94hw]
created: 2026-11-04T15:19:41Z
type: task
priority: 2
assignee: mikewolfd
tags: [capture, custody]
---

# Record custody when a capture body already exists

`BodyStore` now preserves the actual stored size and single-PUT MD5 for conditional upload refusals (HTTP 412), legacy gzip, retained references, and same-run reuse. It reuses qualified metadata for the exact saved copy and looks up that key after an unqualified 412. `ReceiptWriter._capture` records the values on reused bodies. Legacy multipart `.gz` records verified size and uses the reader’s exact listed ETag for the conditional read. The Git snapshot writer still accepts a 412 without a follow-up HEAD. The `ct-94hw` fallback covered the earlier 85 present but unpinned bodies and still serves old receipts.

## Acceptance Criteria

- Preserve valid acknowledged size and digest information in the same-run cache. Reuse metadata from the exact physical-key lookup already performed for a legacy object or retained reference. Only make an additional HEAD request when the existing object otherwise lacks qualified metadata, including an unqualified HTTP 412 result.
- Record the actual stored length and single-PUT MD5 under the existing storage rules. Do not substitute the attempted compressed upload's size or digest. Keep the outcome `unchanged` and the create-only write. Distinguish missing, invalid and unavailable metadata rather than inventing a successful value.
- Carry verified `stored_md5` and `stored_bytes` through the unchanged receipt and normalized capture reader. Cover HTTP 412 with deliberately different attempted and stored bytes, both retained-object paths, cached pins without a redundant HEAD, and invalid or missing metadata.
- Reuse `R2Adapter.head`, `single_put_md5` and the existing capture mapping. The mapping already accepts these fields; avoid touching byte-hashed `captures.py` unless a specific missing behavior is demonstrated. Preserve the separate snapshot writer's existing behavior and the reader fallback for old receipts.

[Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

## Notes

**2026-11-05T20:18:16Z**

Applied the accepted third-round scope update. The current description records the root cause, delivered work, remaining behavior and bounded checks; historical notes remain unchanged. No implementation or operational action was performed. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

**2026-11-05T21:21:58Z**

Closed on source merge `0d2c8420` (`bdc25451`). The final focused run passed 77 checks across three selected files in the 491-file production-offline lane. Six writer-to-normalized-capture cases covered HTTP 412, legacy gzip, bare and gzip retained references, multipart gzip, and cache reuse. The planted 412 used a stored gzip whose length and MD5 both differed from the attempted upload. The storage adapter tests distinguished missing objects, invalid metadata, and unavailable lookups. Blind GPT-6.1 Sol/xhigh review accepted the final behavior, including two HEAD requests across four alternating references to the two physical copies. The capture mapping and parser pins stayed in place. [Final focused run](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/head-response-tests.log) · [Review handoff](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/STATUS.md)
