---
id: cef-c9e8
status: in_progress
deps: []
links: []
created: 2026-10-27T04:54:00Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, S1, E1]
---
# S1/E1: specify executable document fixtures and registry seeds before model SQL

## Acceptance Criteria

Every S1 fixture has explicit inputs and expected results before SQL; all formats and registry samples are covered; real slices execute with the draft rules; main-content extractor is chosen on paired captures with measured time.


## Notes

**2026-10-27T07:27:05Z**

Page contracts precede binding: literal/order/group/date/namespace/entity/fingerprint cases. Current page-reader checks:89 pass, including15 new contracts. Trafilatura2.0.0 on3425 locally located bodies gives3424 nonempty and1622 equal candidate endpoint groups; readability0.9 gives3291/1562. Full discovery6470 candidate bodies;3045 remain unavailable locally after412529-file metadata inventory. S1 stays open: sniff, registries, semantic SQL, real slices, full qualification and labeled sample. See docs/measurements/engine-first-20261027/s1-pages.md; no live storage access or writes.

**2026-10-27T08:57:00Z**

Sniff binding 35315b74 covers all 14 DM formats, exact PDF ranges, the actual bounded reader, Office/ODF and double-gzip WARC. The 87 focused checks pass. The full lane started at 8c731589 with runtime binding 35315b74: 11,368 passed, 33 failed and three setup errors; all 36 baseline failure identities remain unchanged, including subtests (cx_after_s1_sniff_full_comparison.json). Parser status fix 540c4ceb follows DM; its oversized-PDF and ZIP rules were corrected in place. Expected fixtures 8c731589 and b39ae086 cover 25 roles, 15 groups and six link cases before SQL. Current page replay completed. S1 remains open.

**2026-10-27T11:16:26Z**

Owner-bounded extractor choice: Trafilatura on existing available evidence; no more comparisons. Current replay3425/0errors. Bounded native real-slice cache join found212HouseXML;12hash-checked readings complete. Selected available GovInfoZIP empty; EOT body absent. Semantic slice/grouping SQL and real registry seeds keep S1 open.

**2026-10-28T05:11:54Z**

Ownership transferred to site by owner decision 20261028T051000Z. Existing S1/E1 fixture and real-slice evidence retained; new feed-context regression fe45f84b/6b8968f6 reuses XML listing role and passes2native checks. Root keeps model SQL/S2 and does not restart S1/E1 fixtures.

**2026-10-28T05:43:27Z**

Site continuation: executable role fixtures now cover all 14 sniff formats, plus METS/PREMIS/House committee metadata roots and the maintenance page at a file-shaped URL (99bab3f2, b090c468). Focused role/sniff/archive-capture 46 passed, role/group 19 passed; merged owned seams 83 passed. Native actual 167c6a78 coverage is 50 HTML bodies/106 captures: 57 real document captures, 43 errors, five wrappers and one non-real file-shaped document. Existing verified House XML readings remain available; valid GovInfo ZIP and EOT envelope semantic slices remain unqualified in the known local inventory. No detector, threshold or model SQL changed.

**2026-10-28 current XML qualification**

All twelve retained House XML entities pass current sniff/XML leaves at 519ee332, with one bounded auxiliary-cache read each and matching entity SHA-256. Roots remain eleven floorschedule/one committee-meeting. Readings and versions are retained privately; see docs/measurements/engine-first-20261027/site/s1-xml-current.md. This is current-leaf qualification, not canonical raw receipt normalization or full model qualification. Raw's exact original-receipt packet, valid GovInfo ZIP and EOT semantic cases remain open. No body was reopened after the saved-result assertion vocabulary correction.
