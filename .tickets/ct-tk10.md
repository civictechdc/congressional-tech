---
id: ct-tk10
status: open
deps: []
links: [cef-96wc, ct-n2cy, ct-qg8e, ct-d0o0, ct-4jms, ct-ud0b]
created: 2026-11-02T10:24:38Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, gates, phase2]
---
# Gate every publish on key comparison, link rule, end-to-end test, write-time schema and producer proof

Owner decision 2026-11-02: all five gates before the next publish. publish_v21 reached live with defects because nothing compared it with the previous release or with raw data, required fields were not refused at write, links vanished silently, and inputs carried a digest but no producer. Each gate must be able to fail on the defect class it covers; a check that agrees with itself is not a gate.

## Acceptance Criteria

- Key comparison: release_diff against the live release by key, value by value, refuses unless every difference group has a recorded cause.
- Link rule: every link key published by the live release resolves in the candidate, by redirect to its successor or a removal notice; none vanish. Covers the 7,266 lost links.
- End-to-end: one fixture runs raw receipts through captures, readings and model to release files, including a ZIP with members, an HTTP 202, an empty 2xx and a NULL URL.
- Write-time schema: required fields (sources.url and others named in the schema) are refused when written, not found later.
- Producer proof: every pinned input records the producing code revision and job; publish refuses an input without it.
- Each gate has a test proving it fails on an injected defect, and the publish workflow runs all five before the pointer flips.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Plan (plan-h): gate 1 release_comparison in publish_candidate (release_diff never failed on value changes); gate 2 retired_links.parquet seeded from c94bfedc/a06e2a63/0db23484 with site and MCP redirect or notice; gate 3 end-to-end in archive_publish_job.execute; gate 4 required fields for all tables (registry declared one of 21); gate 5 per-row producer version (parser_version/catalog_version current or registered-compatible; captures.mapping_version), since writer_job/writer_commit are receipt provenance (NULL on 4,144,875 of 4,147,132 v21 rows). Implementing: impl-h, branch r1b-h.

**2026-11-02T12:36:53Z**

Round 1b 2026-11-02 (lead): impl-h done: 13 commits on r1b-h (1055fefb..36ac49a0), rebased on integrate-round1 76c521a0. All five gates in the real publish path, each with a test that fails it on an injected defect. Offline against 448651e7 (base c94bfedc): gate 1 refuses (69 reasons, 39 value changes); gate 2: 7,266 base keys vanish, all covered by the seeded ledger (7,134 redirect, 132 removal notice; the 132 not yet read raw); gate 4 refuses 72 NULL sources.url; gate 5 refuses v21 captures (no mapping_version); gate 3 is a code test. Waiting on e1's mapping_version (2 strict xfails) and a cause record for the real candidate. Report: .cache/rounds/r1b/h/offline-gates/report.json. Open: the end-to-end test shows a ZIP dip.xml member not listed as a document; check against the data model.

**2026-11-02T13:13:02Z**

2026-11-02 green-h (request changes): numbers reproduce exactly against 448651e7. Defects: (1) removal notices are wrong for 70 of the 132 keys: duplicates at an address whose other document survives, with a successor in 69; the redirect rule never looks at addresses; the 71st (a 403 page) takes a notice. The 61 ZIP-member keys come from the D1 archive-member defect. (2) Gate 1 passes a changed file whose handler finds nothing (e.g. witness values). (3) The link rule never checks that every history key landed in the ledger; impl-h's offline harness redirected 6,260 to the wrong document (the real model is unaffected). (4) dip.xml is never asserted. (5) 114 of 229 columns are declared non-null; review the rest. (6) Gate 5 checks a version per row, not the commit and job. (7) Three publish journeys are xfail on any ValueError. (8) Resume after a successful flip errors (archive_controller.py:296, traced). Waiting for red-h before sending fixes.

**2026-11-02T13:13:51Z**

2026-11-02 red-h (merge with fixes; 179 passed): gate 1 passes, with no cause record, a witness organization rewrite, a source moved between documents, and a url key repointed; link_history is unchecked; strict xfails hide every path to published; evidence on explained entries is optional; the gates pass with nothing checked when the pointer is missing or in legacy format. Every path (CLI, CI, daily) goes through execute, and gate_and_flip is the only pointer writer. Combined red+green fix list (11 items) sent to impl-h.

**2026-11-02T13:59:45Z**

2026-11-02 impl-h: all 11 review fixes on r1b-h (head 5810b591, 19 commits on 98fb1424); full production-offline lane green with no xfails left (3.6 GiB). Gate 1 now refuses red-h's three probes and silent handlers; explained causes need evidence pins. Gate 2 adds address successors (§8.2) and the history chain from the pointer's previous release. The 7,266 lost links become 7,203 redirects and 63 notices (61 ZIP-member keys to recheck on the rebuilt candidate; 1 HTTP-500 ZIP; 1 unlisted sciencedirect article). Gate 3: dip.xml is not a document (§7.3), all six suites run. Missing or legacy pointer refuses unless first_release is declared. Resume after a flip returns release_unchanged. Gate 5 also checks a per-snapshot producer record. Gate 4 finds 17 NULL nominations.description in 448651e7 (upstream check in progress). red-h2 is re-reviewing. Next: ct-ud0b.

**2026-11-02T14:25:28Z**

2026-11-02 red-h2 (merge with fixes): red-h's probes now refuse, and 12 of 17 mutants were caught. The address-successor rule redirects across editions: all 69 address redirects come from version_keys addresses and land on different bodies (7 editions collapse onto 3 documents), against data model §7.5. New rule: redirect only to a successor holding the same body or text fingerprint; otherwise show a notice listing the address's current versions; all 69 bodies to be read. Gate 5's producer record is self-attested (it accepted README.md, the first commit, version 99): recompute the byte-hashed version at the recorded commit and require the table's registered producer. Tests for M1 (first_release with a live pointer) and M10 (link history). Sent to impl-h.
