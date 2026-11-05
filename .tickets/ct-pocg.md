---
id: ct-pocg
status: closed
deps: [ct-73oe, ct-deh9]
links: [ct-30fp, ct-kw9b, ct-vpo2, ct-h1nd, ct-77zb, cef-96wc, ct-1mbc, ct-9gmr, ct-c5xf, ct-082q]
created: 2026-10-30T14:10:02Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, congress-api, retention]
---
# Read useful metadata and testimony once from each retained HTML body

Give older captures the same useful metadata and cleaner testimony as new ones. Run the existing bounded readings producer for HTML metadata and publisher-marked content. Keep body-level extraction keyed by body and parser version, then resolve links per capture. The Round 2 branch carries implementation work for the combined scope.

## Acceptance Criteria

- Reuse unchanged body/version pairs. Select intended HTML inputs and report missing bodies, excluded formats, error pages and partial-format outcomes. Preserve originals, unrelated earlier readings and older readable schema parts, avoid unrelated reads, and resume without duplicate output.
- A fixture with the same HTML at distinct URLs shares extraction and resolves links per URL. Missing context remains unresolved. Measure exact body/version selection, reads or downloads, elapsed time and peak resources on the retained replay.
- Prove supported marked content removes unrelated text without dropping testimony. Preserve the independent two-way cohort comparison and the existing fallback, including marked-empty, nested or multiple blocks, malformed, boilerplate and unannotated cases. Record selected, fallback and failure counts and output sizes.
- Preserve safe text, meaningful order and links, exact selectors and retained body evidence. Provide bounded snippets and content references for publication without copying full text into every document row. Preserve the owner’s review conditions in the absorbed `ct-c5xf` evidence. If integrating Round 2’s replacement-character normalization, check the affected GovInfo fingerprints and link continuity under the existing release gates.

## Notes

**2026-11-02T13:14:11Z**

2026-11-02 (lead): Round 2 plan at .cache/rounds/r2/html/plan.md (against integrate-round1 98fb1424). html_metadata becomes a fifth readings parser run by produce_daily after the combined pass, so there is one replay path. The version is owned by readings.py, outside the readings bundle; extruct is provenance and a lock-only compatible entry. No readings schema change: facts, format statuses and the main-content reference go in fields. All 192,191 html bodies (4.54 GB), with the 82,599 in the release first. Keep the prefetched 67,540 in the mirror through Round 2. Cost: about 80-100 CPU-minutes, 12-20 minutes wall time at --rss-gb 4.

**2026-11-02T13:15:40Z**

2026-11-02 (lead): add to Round 2: normalize Unicode replacement characters (U+FFFD and its double-encoded form) out of the html text fingerprint, so copies differing only by them merge (7 GovInfo packages). Round 2 re-reads all html bodies anyway.

**2026-11-05T17:11:15Z**

Consolidation accepted 2026-11-05: absorb ct-c5xf.

User outcome: Versioned HTML extraction, content selection and selective replay.

Remaining acceptance: Independent no-dropped-testimony comparison; safe ordered text and exact selectors; explicit fallback counts; bounded snippets; body/version reuse; capture-context URL resolution; resume and unread-gap accounting.

Source evidence and full original criteria remain in: .tickets/ct-pocg.md:27; .tickets/ct-c5xf.md:38; .cache/rounds/r2/html/plan.md:120. The superseded records remain available; completed work is reused and unfinished criteria stay with this owner.

**2026-11-05T19:53:12Z**

Closed as superseded on 2026-11-05. ct-082q owns all remaining scope, acceptance and evidence as one HTML delivery feature across extraction, native publication, site, MCP and shared verification. This is consolidation, not a claim that implementation or publication is complete. Original criteria and historical notes remain here; ct-082q links back to them.
