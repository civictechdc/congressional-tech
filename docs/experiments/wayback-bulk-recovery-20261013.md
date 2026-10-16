# Bulk archive discovery pilot

Decision: Decide whether a bulk discovery route merits a broader measured trial for the existing 17,739-URL recovery list. No production adoption, collector restart, R2 writes, or broader document acquisition.

Observed behavior: the single-URL Availability API stopped on HTTP 429 after two verified capture batches. This proves rate limiting at that time, not the cause of each earlier failed replay.

Hypotheses and competing explanations:
- H1: CDX host listings resolve many frozen URLs per request. Predict at least twice as many unambiguous matched cases per request as fresh Availability calls, with no loss on freshly accessible positive controls. Authentication refusal, excessive pagination, or lower usable coverage weakens H1.
- H2: End of Term public indexes provide a selective path from URL to archived bytes within a small transfer budget. Predict a public index/locator that can be joined to cases without scanning multi-GB shards. If only large monolithic indexes exist, the cheap-selective-lookup hypothesis fails within this budget; that does not show the documents are absent.
- H3: a shared Wayback service restriction prevents a cheap live comparison. A renewed 429 stops Wayback requests and leaves performance unresolved. A CDX authorization refusal stops that arm; Availability results cannot demonstrate CDX access. A successful request after cooldown does not establish sustained capacity.

Arms:
A. Fresh per-URL Availability requests, unchanged query semantics from the existing runner. Prior sample and 429 evidence are historical controls, clearly separated.
B. Documented CDX host queries with raw original URL, date, MIME, status and digest, plus bounded resume-key pagination. The FTC failure case uses one exact CDX query only if CDX remains accessible.
C. Public EOT-2012 and EOT-2016 URL/CDX indexes and archive locators. EOT is a different collection/time coverage as well as an access method; assess the bundle, not a pure API-speed claim.

Cases: three historically positive cases, nine deterministic untouched URLs (three per target host), the exact FTC URL that triggered HTTP429, and two constructed negative paths. Cases and labels are pinned in cases.json before requests. These are development cases, not a representative population benchmark. Unknown coverage remains unknown; missing results from incomplete pages are never called absent.

Held constant: same target URL strings, original frozen manifest and filename exclusions, one pass, one network worker, five seconds between Wayback request starts, one second for public S3. No publisher requests, paid fallbacks, new URL variants, retries, R2 access or archive mutation. Reuse the pinned Wayback replay validator and maintained capture inspection for any selected local body checks. Retain exact sent request URL/method/parameters, response status/headers/body, byte counts, elapsed time, failures and assessment. Model/temperature: not applicable.

Bounds: 20 minutes; 60 total requests; 512 MiB total response bytes; 32 MiB per response; up to two CDX pages of 10,000 rows per host; EOT 2012 and 2016 only. At most six local validation bodies chosen deterministically from successful case matches; historical cached bytes can be replayed as historical validation only. Stop an affected service on 401/403/429 without switching endpoints to evade it. The actual 429 case is tested first, followed by one positive baseline; CDX access is checked before running the remaining paired cases. If an endpoint is refused, classify access failure, retain it, and skip dependent work.

Decision rule, fixed before collection: advance an arm to a broader trial only if it resolves at least two freshly tested case URLs per network request on average, preserves all comparable freshly accessible positive controls, produces no false negative-control match, and supplies at least one complete structurally valid fresh document or substantive HTML body within budget. Count all setup/index requests and bytes for cold-start cost; separately report possible cached-index reuse. If scope/access/budget prevents a full comparison, verdict is unresolved or not solved for that gate. Any narrower benefit is a separate finding. No extrapolated recovery rate or live speedup without measured denominators.

Assessment: report endpoint access, definitive positive matches, completed negative lookups, unknowns, request counts, bytes, wall time, complete body validity and content relevance separately. CDX digests and filename equality are candidate grouping signals; retain URL/capture provenance and compute local SHA256 before byte-identity claims. Full index pagination is required before declaring no CDX match. EOT partial scans likewise cannot establish absence.

Evidence directory: `.cache/wayback-bulk-pilot-20261013/`. Preserve original criteria and add dated amendments if needed. Stop when the decision is answered or a bound is reached.


## Findings recorded 2026-10-13

The predeclared bulk-substitution gate did not pass. Availability matched nine of 13 real cases; EOT matched nine, with a combined metadata match for all 13. EOT required 16 metadata requests and missed one freshly accessible positive control, so it did not meet the two-cases-per-request or control-preservation requirements. Bounded CDX host pages matched none of the selected cases and remained incomplete; this cannot establish archive absence.

The narrower selective-access hypothesis was supported. Public EOT cluster summaries and compressed byte ranges supplied four complete records unavailable through the bounded Availability arm: two readable PDFs and two substantive HTML statements. All four passed exact WARC target/date/status and digest checks. The initial pilot used 44 requests, 64,933,505 response bytes and six body validations. Two mistaken EOT path requests remain in the accounting. Overall elapsed time includes analysis and is not a pure throughput measure. No production adoption or R2 writes resulted from this pilot.

The user separately requested EOT as a backup. A new deterministic holdout of 24 previously unprobed, exact-index-matched URLs produced 24 complete validated records: 12 PDFs and 12 HTML pages, with 4,703,803 decoded bytes. This passed the separate bounded-backup rule of at least 20 valid records. It does not estimate recovery across all missing URLs or reverse the failed broader gate. A local output-ID collision was resolved by preserving and reusing all five responses already obtained; the trial made 24 total source requests, without repetition. The maintained in-memory capture/verifier path passed 24 receipts and all 48 decoded/WARC body checks. A one-shot import is queued behind the unchanged daily cloud-writer guard. At startup no R2 writes had occurred. No expansion beyond these 24 is automatic.

Evidence: `.cache/wayback-bulk-pilot-20261013/final-report.json`; `.cache/document-eot-backup-20261013/sample-01/attempt-02/stage-completion.json`; `offline-check-result.json`; `startup-verification.json`. Raw observations and original criteria are preserved.
