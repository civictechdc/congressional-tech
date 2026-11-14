---
id: ct-en4n
status: open
deps: [ct-fb7k]
links: [ct-chc4, ct-z4w5, ct-f6hr, ct-0a35, ct-n3ik]
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

## Immediate implementation and scope

ct-fb7k owns the focused House Meeting Not Found / File Not Found detector extension using the 400 retained examples. Reuse its versioned observations here; do not implement a second detector. This parent retains source-role qualification beyond those templates, retained capture-history reconciliation and the evidence-backed deferred-source list. ct-n3ik consumes the role observations in the cheap review queue, while ct-0a35 checks accepted content through real search.

The example set annotates existing inventory bodies: 384 error-template instances, two directly reviewed ordinary metadata/landing controls and 14 unassessed records. Neither extraction completion nor example membership authorizes document-text selection or publisher refetch. The broader source-role work must not block the already authorized CPU reparse.

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

**2026-11-13T21:49:42Z**

Implemented the shared spicy-docs House floor Atom reader and explicit offline CT/Regs consumers. Final retained source replay (SHA c90e782a00651261a9ac21ae8d30df88757b3b66ae99a5ff794f0dc8ca65336e) keeps2,226 entries and65,511 link occurrences; actual CT model resolves all65,511. Entry revisions remain distinct. Original malformed '/https://' href remains recorded, with a separate repair only when the exact target is explicitly stated elsewhere in the same feed. Direct raw/intermediate/final reviews cover entries0/1/1047/1048/2225; independent review caught both planted wrong-target and wrong-bill-version controls. Measurements: CT14s/0.67GiB RSS; Regs8s/0.59GiB. Durable evidence: repairs/house-floor-feed-20261113/{ct-replay-final,regs-final,independent-data-review-ocr-completion.md}. This is a bounded local replay, not freshness, complete historical coverage or public adoption. Daily feed acquisition is not enabled.

The bounded retained response-role API/CLI now preserves separate error, wait, empty and unassessed outcomes. Independent review caught heading-evidence amplification and mixed-content/namespaced XML false positives; fixes retain explicit limits and unassessed source evidence. All11 retained real observations are unchanged, and five independent mechanism probes were re-read after repair. See repairs/response-roles-offline-20261113/. Broader real document/error-quote, portfolio/empty/whole-hearing controls,345 zero-page classifications and complete unresolved-source history remain open. OCR stays paused; publisher refetch stays deferred. The per-ticket named-review matrix is coordination/ocr-offline-ticket-matrix-20261113.md.

**2026-11-13T22:24:49Z**

Bounded native repair review of exact retained bodies 04a74549a18e2de5103e79c99714af3ad9b9ccea7cc0d6c62ddc419af5abbe30 and ed0298387f8c87d6c6bc70241e4510e490fe8e2b4668e2595cbc7f0220d156b8 completed without OCR/refetch. Whole-file hashes match full decompression of retained stored objects and capture metadata; these are not inspection previews. The first has only 1,553 bytes versus a declared 43,652-byte/four-page PDF and ends inside its first page dictionary. PyMuPDF already attempts repair and exposes zero pages; saving refuses and qpdf reconstruction fails. Preserve explicit incomplete-source status, never valid-empty text.

The one-MiB Walling retained import contains a complete earlier nine-page testimony revision followed by a truncated fourteen-page update. Literal source bytes establish both revisions (including CR-separated updated dictionaries), and native inspection recovers five testimony pages hidden by the broken updated tree. Exact original prefix [0:336711], SHA30bedf44e3393fd77166126963beb8c2c52682f15224af4c1ffe5e024e4229b9, opens as the earlier nine-page revision without repair or warnings. It excludes later resume/disclosure additions and is an inspection-only earlier revision, not a complete replacement. A generic qpdf rewrite drops those five testimony pages and blanks a partially readable form, yet subsequent qpdf --check succeeds. Direct author and independent image reviews reject this rewrite; no complete reading, checkpoint reuse or selection follows from structural validity. The original retained_import complete=true flag does not prove publisher-transfer completeness or locate the cause of truncation.

Evidence and exact input/intermediate/output identities: <main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/native-pdf-repair-20261113/{data-review.md,custody-verification.json,literal-revisions.json,earlier-revision-report.json,artifact-hashes.json}. Remaining gate: reconcile complete retained alternatives and intended revision/attachment scope; preserve missing updated image bytes for deferred source recovery. No conclusion is extended to all 345 zero-page failures. OCR remains paused and publisher refetch deferred.

**2026-11-13T22:48:50Z**

Three additional geometry-cohort originals now have exact captured-archive custody and direct page reviews. Two (d128b929c3b1… and924eb1c45958…) end inside declared streams, lack the final PDF trailer/EOF, and need native repair that substitutes missing font data; their rendered and native text is garbled or incomplete. Verified archive identity does not identify the cause of truncation or prove publisher-transfer completeness. The third (15611eacbdfb…) renders coherently but has an invisible native span and omitted graphic-header text. All remain unqualified; no recognition, publisher fetch or selection occurred. Exact identities, full native/output chains and review limits are in repairs/geometry-reconciliation-20261113/archive-native-sample/{data-review.md,classification-delta.jsonl,artifact-hashes.json} under the main recovery evidence root. ct-yy07 owns the numerical geometry reconciliation; this adds source-quality evidence without claiming all zero-page or capture-history cases resolved.

**2026-11-14T05:52:05Z**

Shared feed wiring is now merged across all three repositories: CT PR156, spicy-docs PR27 (f9584d8bbc6d14c7707fbf53d3487e024b0455b8) and spicy-regs PR194 (04be0854af544f2e1af0ae3619d2b8b325c3ed17). Regs passed all four test partitions, lint/dictionary/join checks and live integration at f859398e0ead8d27c330e9e6c22e769427b618dc. Independent retained raw/intermediary/final reviews and exact output comparisons preserve 1 feed / 2,226 entries / 65,511 link occurrences, including per-capture entry/link identity. House feed tables remain explicit local-partial candidates outside hosted query registration; no daily acquisition, current-freshness claim or feed publication follows from this merge.

The reviewed response-role example S301 now links to its exact historical html_text intermediate while its response_roles output remains private and absent from the merged lake index. Independent linkage review: repairs/corpus-assessment-20261113/review-links-20261114/reviewer-shared-reader/independent-review.md. The broader source-role controls, zero-page cause classification and unresolved capture-history acceptance remain open. Publisher refetch stays deferred.

**2026-11-14T11:58:30Z**

The user requested that the 400 previously held HTML/XML bodies serve as inventory examples. Added exact-key annotations under repairs/corpus-assessment-20261113/response-examples-20261114/{examples.jsonl,examples.csv,summary.json,input-manifest.json,README.md}. All 400 already belong to the frozen 18,777-body inventory; no corpus bodies were added or original rows overwritten. Labels preserve 197 NoSuchKey, 173 meeting-not-found and 14 file-not-found template examples. Of the 16 unmatched records, earlier direct reviews supply one ordinary structured-metadata control (M003) and one meeting-landing control (M005); 14 remain unassessed. Reused five original source-role reviews without claiming all template siblings were individually source-reviewed. Every example links its retained-copy descriptor, actual current reading/version and text hash, historical output and frozen selection scope. All 400 separately reparsed successfully in 14 seconds at 0.509 GiB peak; extraction completion remains distinct from source quality. Use these as development/regression data grouped by template family, not a held-out accuracy benchmark. Assembly took 0.34 seconds with no new source retrieval or model calls. OCR remains paused, publisher refetch deferred, selection unchanged. Broader ticket acceptance stays open.

**2026-11-14T12:31:10Z**

Five-step FTS follow-through is now ticketed. New child ct-fb7k owns the missing House meeting/file response detector; this parent retains broader role and capture-history qualification. Linked ct-n3ik for cheap triage and ct-0a35 for actual source-to-search acceptance. Existing raw/review history remains intact; OCR stays paused and refetch deferred.
