---
id: ct-w34j
status: open
deps: [ct-6him]
links: []
created: 2026-11-09T00:52:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-lwxs
tags: [entities, organizations, spicy-regs]
---
# Org entities phase 2: federal agencies from the SpicyRegs agency roster

Size M. Plan: docs/plans/org-entities-20261108.md (Federal agency table). Ask SpicyRegs to publish an agencies generation (Federal Register roster names/short names/parents from its vendored RefSpec registry, plus REF-072 successor bridges); pin it as spicy_agencies in model/jobs/spicy-regs/spicy-regs.json. Model SQL org-agency-matches.sql: whole-segment hash-equality join. Aliases (military branches, VHA/VBA, CRS, ...) are org_decisions 'same' rows seeded from fed_agency.json top_unmatched; legislative bodies absent from the roster get decision-anchored orgs. Measurement: .cache/archive-release/investigations/entity-matching-measure-20261108/fed_agency.json (roster as-is: 57/81 sampled federal strings; 2,193/3,662 = 60% of house_xml Government - Federal appearances).

## Acceptance Criteria

1) No new Federal Register fetch in congressional-tech; agencies come from the pinned SpicyRegs generation. 2) >=90% of house_xml Government - Federal appearances link to an org (baseline 60%). 3) scripts/measure/org_agency_raw_check.py, written to the AGENTS raw-check rules, finds <=1 wrong in 100 linked rows, and flags a planted state-EPA -> federal-EPA link; a second reviewer confirms the planted case. 4) GAO's ~600 strings resolve to one org_id, General Accounting Office included.

