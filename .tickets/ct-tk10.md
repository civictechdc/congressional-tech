---
id: ct-tk10
status: open
deps: []
links: [cef-96wc, ct-n2cy, ct-qg8e, ct-d0o0]
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
