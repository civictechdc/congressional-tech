---
id: ct-z4w5
status: open
deps: [ct-en4n]
links: [ct-en4n]
created: 2026-11-13T17:46:16Z
type: task
priority: 3
assignee: mikewolfd
tags: [body_text, captures, refetch, deferred]
---
# Deferred: refetch unresolved damaged or missing publisher sources after detection qualification

User sequencing decision: qualify error-page detection and reconcile retained target history first; publisher refetching happens later. Known candidates include a 64 MiB Senate prefix, a 1 MiB testimony prefix, a zero-byte PDF WARC payload, damaged page trees and genuinely unresolved landing targets. OCR cannot recover bytes absent from a truncated response. These are candidates pending identity/history reconciliation, not a new fetch queue.

## Design

Keep this work deferred until the user resumes refetching. Depend on the response-role/capture-history qualification and reuse acquisition/recovery components. Preserve every original response, header, partial body, hash and receipt. A new complete or alternate publisher response receives its own capture/body identity. Preserve accepted official-hearing and URL-variant fallbacks; encrypted, unavailable or irreparable inputs keep named unresolved outcomes.

## Acceptance Criteria

1. The prerequisite supplies a deduplicated, evidence-backed list excluding already selected complete captures and accepted recoveries. User deferral is explicitly lifted before publisher requests.
2. For each resumed request, retain transfer completion evidence, source identity, old/new hashes and receipts; verify actual PDF/markup readability and source completeness before selection.
3. Reconcile every requested item to a selected qualified copy, accepted scoped fallback or explicit unresolved reason. Preserve logical document associations and prior evidence.
4. Publish qualified results through existing gates and independently read back them without treating HTTP success or OCR completion as proof of completeness.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T17:46:56Z**

Additional confirmed damaged-source candidates: 04a74549a18e2de5103e79c99714af3ad9b9ccea7cc0d6c62ddc419af5abbe30 (1,553 retained bytes versus declared 43,652; page tree missing) and 8ec3cad9a2221fc57fb59b03aa7318c916bead34adabb971ea114795c518eedb (32,056 bytes, no readable trailer/xref). Keep every candidate subject to ct-en4n retained-history reconciliation before a later refetch. A shared error string does not prove all 345 page-selection failures have the same cause.

**2026-11-13T18:48:44Z**

Deferral remains in force. Neither inventory creation, source classification nor a corrected parser authorizes publisher refetching. OCR is also paused independently. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.
