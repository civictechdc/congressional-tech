---
id: ct-en4n
status: open
deps: []
links: [ct-chc4, ct-z4w5, ct-f6hr]
created: 2026-11-13T17:46:16Z
type: task
priority: 1
assignee: mikewolfd
tags: [body_text, quality, captures, html, xml]
---
# Qualify document, feed, error and landing roles against retained capture history

The review identified 384 retained error-template bodies (197 NoSuchKey, 14 File Not Found, 173 Meeting Not Found); none were selected in the inspected frozen release. Eight checked landing targets are already discovered by document_links: six have selected PDFs, one was never attempted and one returned HTTP 410. A separate WARC contains HTTP 200 with application/pdf but zero payload bytes. These observations require response roles and capture-history reconciliation, not an assumption that every PDF-looking URL or short body needs refetching.

## Design

Reuse the link reader, retained captures, queues, selection/recovery history and maintained content-quality measurements through narrow adapters. Version body-role and quality findings separately from historical parser completion. Distinguish substantive documents, Atom/RSS feeds, error/wait/empty responses, metadata, containers, justified empty and unassessed bodies. A complete feed is valid source data: keep its entry identities, updates and links separately from document prose. Preserve accepted requested_content_in_official_hearing and user_accepted_url_variant recoveries and every logical association. Inventory portfolio attachments separately. Publisher refetching is deferred by the user.

## Acceptance Criteria

1. Independently qualify known error families with real documents quoting error phrases, legitimate short/empty content, XML manifests/playlists, valid Atom/RSS feeds, PDF portfolios and accepted whole-hearing fallbacks as controls. Do not reuse a generic text-length threshold as proof.
2. Trace all eight landing URLs through link readings, capture attempts, retained copies, selection and accepted recovery. Reconcile both missing and existing outcomes; do not count successful captures as unresolved.
3. Preserve raw identity and refusal evidence, report selected versus unselected effects, and plant false-positive and missed-error cases that the independent check catches.
4. Produce a deduplicated unresolved-source list with reasons and evidence for the deferred refetch ticket. Classification alone does not initiate retrieval.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T17:46:56Z**

Retained-input triage also owns classification of the 345 select-at-least-one-distinct-page errors; do not turn a zero-page parser view into valid-empty text. Raw specimen 04a74549a18e2de5103e79c99714af3ad9b9ccea7cc0d6c62ddc419af5abbe30 is 1,553 bytes while its PDF linearization header declares 43,652 bytes / 4 pages; pdfinfo reports a missing/null top-level pages object. Distinguish damaged/truncated sources from legitimate containers and inspect the remaining members before assigning one cause to the whole bucket. Evidence: .cache/archive-release/ocr-recovery-20261113/raw-review/inspection.json.

**2026-11-13T18:48:44Z**

The 345 zero-page failures require classification; they are not all proven corrupt sources. Ordinary WARC exclusion is intentional (ct-0hay): no envelope was selected as saved_body. Qualify source role and saved-body reachability before restoring any WARC processing/publication. Broad phrase matches are review candidates, not error verdicts. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T19:48:19Z**

Add the complete House BillsThisWeek-RSS.xml Atom feed as a positive feed/container control. Exact body c90e782a00651261a9ac21ae8d30df88757b3b66ae99a5ff794f0dc8ca65336e has 2,226 entries, publication/update times, weekly page links and embedded bill-document links. Current source inspection found no dedicated consumer in CT, spicy-docs or spicy-regs. CT generic XML can read hrefs; news_lake has an offline feedparser-based Atom adapter. Spicy-docs currently supports RSS 2.0 through its shared feed helper; Atom/source-specific support is an explicit extension. Recommend a shared spicy-docs reader and structured schedule/discovery consumers in CT or spicy-regs, after existing-link/freshness comparison. Scheduled consideration is distinct from votes or completed actions. Keep raw feed and historical readings. Findings and measurements: repairs/ct-f6hr-event-limit-20261113/. No recurring acquisition or publisher refetch was started.

**2026-11-13T19:50:10Z**

Additional current-code limit: ordinary lake/readings.py uses PAGE_PARSE_MAX_BYTES = 24 << 20 and explicitly names c90e782a as an over-bound XML case. Generic href-reading capability does not establish that this 38.9 MB feed has contributed links. Dedicated entry-level routing and a retained-table comparison are required before claiming active feed use.

**2026-11-13T19:51:47Z**

Retained feed shape: 2,226 unique Atom entry IDs point to 198 distinct weekly-page links, with up to 40 entries for one link. Preserve entry identity/update/content versions; URL-only deduplication would discard observations. These are retained-snapshot counts, not complete historical coverage or current freshness. The latest retained entry is dated 2026-09-15. Evidence: repairs/ct-f6hr-event-limit-20261113/feed-shape.json.
