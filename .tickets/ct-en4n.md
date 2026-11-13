---
id: ct-en4n
status: open
deps: []
links: [ct-chc4, ct-z4w5]
created: 2026-11-13T17:46:16Z
type: task
priority: 1
assignee: mikewolfd
tags: [body_text, quality, captures, html, xml]
---
# Qualify error and landing-response detection against retained capture history

The review identified 384 retained error-template bodies (197 NoSuchKey, 14 File Not Found, 173 Meeting Not Found); none were selected in the inspected frozen release. Eight checked landing targets are already discovered by document_links: six have selected PDFs, one was never attempted and one returned HTTP 410. A separate WARC contains HTTP 200 with application/pdf but zero payload bytes. These observations require response roles and capture-history reconciliation, not an assumption that every PDF-looking URL or short body needs refetching.

## Design

Reuse the link reader, retained captures, queues, selection/recovery history and maintained content-quality measurements through narrow adapters. Version body-role and quality findings separately from historical parser completion. Distinguish substantive content, error/wait/empty responses, metadata, containers, justified empty and unassessed bodies. Preserve accepted requested_content_in_official_hearing and user_accepted_url_variant recoveries and every logical association. Inventory portfolio attachments separately. Publisher refetching is deferred by the user.

## Acceptance Criteria

1. Independently qualify known error families with real documents quoting error phrases, legitimate short/empty content, XML manifests/playlists, PDF portfolios and accepted whole-hearing fallbacks as controls. Do not reuse a generic text-length threshold as proof.
2. Trace all eight landing URLs through link readings, capture attempts, retained copies, selection and accepted recovery. Reconcile both missing and existing outcomes; do not count successful captures as unresolved.
3. Preserve raw identity and refusal evidence, report selected versus unselected effects, and plant false-positive and missed-error cases that the independent check catches.
4. Produce a deduplicated unresolved-source list with reasons and evidence for the deferred refetch ticket. Classification alone does not initiate retrieval.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T17:46:56Z**

Retained-input triage also owns classification of the 345 select-at-least-one-distinct-page errors; do not turn a zero-page parser view into valid-empty text. Raw specimen 04a74549a18e2de5103e79c99714af3ad9b9ccea7cc0d6c62ddc419af5abbe30 is 1,553 bytes while its PDF linearization header declares 43,652 bytes / 4 pages; pdfinfo reports a missing/null top-level pages object. Distinguish damaged/truncated sources from legitimate containers and inspect the remaining members before assigning one cause to the whole bucket. Evidence: .cache/archive-release/ocr-recovery-20261113/raw-review/inspection.json.
