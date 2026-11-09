---
id: ct-6him
status: open
deps: []
links: []
created: 2026-11-09T00:52:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-lwxs
tags: [entities, organizations]
---
# Org entities phase 1: string keys, decision log, stable org IDs

Size M. Plan: docs/plans/org-entities-20261108.md (Tables, Stable IDs, Decision log). Model SQL org-strings.sql over appearance_records_resolved; new provenance kind org_decisions beside reviews in congress_api.retention.provenance (same import stage, supersedes, withdraw); replay in org-decisions-current.sql; engine components step for grouping; org-priors.sql reading the prior release (witness_key_map pattern); empty release tables organizations, organization_ids, witness_organizations, organization_redirects. No custom union-find or cannot-link code. Measurement basis: .cache/archive-release/investigations/entity-matching-measure-20261108/org_variants.json (60.2k strings, 42.9k after cheap rules).

## Acceptance Criteria

1) Witness rows and their organization/on_behalf_of text are byte-unchanged. 2) Two clean rebuilds from raw produce byte-identical org tables. 3) A planted merge yields one surviving org_id and a merged redirect; a planted split keeps the anchor's ID and mints a new one with split_from. 4) A withdrawn or superseded decision has no effect on replay. 5) Model step cost is linear in distinct strings; no pairwise string comparison.

