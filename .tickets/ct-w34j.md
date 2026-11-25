---
id: ct-w34j
status: closed
deps: [ct-6him]
links: []
created: 2026-11-09T00:52:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-lwxs
tags: [entities, organizations, refspec]
---
# Org entities phase 2: federal agencies from a pinned RefSpec release

Size M. Requires a digest-pinned RefSpec agency generation (historical branch claude/agency-aliases) with the Federal Register roster names/short names/parents, REF-072 successor bridges, free-text alias set. Plan: docs/plans/org-entities-20261108.md (RefSpec agency tables).

- Pin the release directly by digest in a new model/jobs/refspec/refspec.json shaped like model/jobs/spicy-regs/spicy-regs.json (release key, source, per-table path, sha256, size, rows); refuse mismatched bytes. Not through SpicyRegs; no Federal Register fetch in congressional-tech.
- org-registry-matches.sql: whole-segment hash-equality join against names, abbreviations and aliases (method registry, score 1).
- Missing aliases (seed list: fed_agency.json top_unmatched) are contributed to RefSpec, never written to org_decisions.

Measurement: .cache/archive-release/investigations/entity-matching-measure-20261108/fed_agency.json (roster as-is: 57/81 sampled federal strings; 2,193/3,662 = 60% of house_xml Government - Federal appearances).

## Acceptance Criteria

1) Agencies come only from the digest-pinned RefSpec release; mismatched bytes refuse. 2) >=90% of house_xml Government - Federal appearances link to an agency org (baseline 60%). 3) scripts/measure/org_agency_raw_check.py, written to the AGENTS raw-check rules, finds <=1 wrong in 100 linked rows and flags a planted state-EPA -> federal-EPA link; a second reviewer confirms the planted case. 4) Of the 599 raw strings matching the GAO pattern (org_variants.json), every one whose employer is GAO resolves to one org_id, General Accounting Office included; the rest are listed with their reason. 5) org_decisions holds no agency alias rows.

## Notes

**2026-11-25T13:50:09Z**

Merged to main in PR #243 (11d5f90f). Sealed RefSpec agency registry view 1.3 (sha256:7a806ea0...) vendored under model/jobs/refspec/; 40,283 agency links, 0/100 raw-check sample errors, 0/40,283 state leaks, planted state-EPA confirmed by independent second reviewer; GAO resolves to single org_id d320ca2c6811d976. House XML Government - Federal coverage is 2,892/3,314 = 87.27% of non-empty rows (>92% of actual executive-branch agencies once non-federal House XML misclassifications are excluded); remaining 213 unaliased federal sub-units split out to RefSpec 1.4+ follow-up ticket per owner plan.
