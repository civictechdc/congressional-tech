---
id: ct-z4w5
status: in_progress
deps: [ct-en4n]
links: [ct-en4n]
created: 2026-11-13T17:46:16Z
type: task
priority: 3
assignee: mikewolfd
tags: [body_text, captures, refetch]
---
# Refetch reviewed damaged or missing publisher sources and preserve new evidence

The user explicitly authorized background OCR/refetch on 14 November. Reconcile retained target history and refetch only reviewed unresolved sources; the earlier deferral is lifted. Known candidates include a 64 MiB Senate prefix, a 1 MiB testimony prefix, a zero-byte PDF WARC payload, damaged page trees and genuinely unresolved landing targets. OCR cannot recover bytes absent from a truncated response. These are candidates pending identity/history reconciliation, not a new fetch queue.

## Design

The user has resumed this work. Continue through measured, explicit target batches. Depend on the response-role/capture-history qualification and reuse acquisition/recovery components. Preserve every original response, header, partial body, hash and receipt. A new complete or alternate publisher response receives its own capture/body identity. Preserve accepted official-hearing and URL-variant fallbacks; encrypted, unavailable or irreparable inputs keep named unresolved outcomes.

## Acceptance Criteria

1. The prerequisite supplies a deduplicated, evidence-backed list excluding already selected complete captures and accepted recoveries. Record the 14 November authorization and current capture eligibility before publisher requests.
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

**2026-11-13T21:31:52Z**

Deferral preserved. Added a retained-history proposal under repairs/response-roles-offline-20261113/deferred-source-proposal.json:2 unresolved landing targets (P001 exact target unattempted,P005 exact target HTTP410),6 already-selected targets explicitly excluded; additional prefix/zero-payload/damaged-PDF/zero-page cases remain unreconciled rather than queued. Reviewer /root/ocr_ticket_completion directly read raw P001/P005/P002 landing links,stored capture/selection trace objects and actual proposal; paths/hashes and scope are in data-review.md and artifact-hashes.json. This reconciles the existing8-target snapshot,not all damaged sources or current publisher state. No acquisition requests ran. The user must lift refetch deferral before requests; source completeness,selection and publication criteria remain open.

**2026-11-14T15:08:53Z**

User authorization on 14 November lifts the old deferral. First bounded reviewed batch used maintained capture policy/Fetcher/DirectAdapter/BodyStore/ReceiptWriter with current URL history and capture scope. P001 Mahoney and P005 Mast targets both returned HTTP410, each a complete tiny HTML response containing only a meta-refresh to its /404 page. /root read both complete raw bodies and receipts. They remain unresolved; new bodies, headers, source hashes and create-only receipts are retained. Three reviewed State Department URLs were not requested because they fall outside the published capture scope. No original or accepted selection changed. Evidence: repairs/source-refetch-20261114/{authorization.json,current-target-history.json,queue.json,results.json,finished.json,README.md}; final batch 1.4 seconds / 0.106 GiB RSS. Remaining damaged/prefix/zero-payload candidates still need exact history qualification; do not repeatedly fetch already satisfied targets.
