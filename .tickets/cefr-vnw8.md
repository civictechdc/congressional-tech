---
id: cefr-vnw8
status: in_progress
deps: []
links: []
created: 2026-10-27T19:00:52Z
type: task
priority: 2
assignee: raw
---
# F5: prepare revision-pinned per-group switch deletions

Preparation only: all BIND section 6 groups with current paths, symbols, callers, wc-l, hashes, preserved consumers and owner gates. No source deletion.

## Acceptance Criteria

All 19 BIND rows plus mixed tests and rewritten docs covered; static references and uncertainty visible; unique accounting; stale-source verification; switch and phase2 gates explicit.


## Notes

**2026-10-27T19:19:21Z**

Read-only generator built under codex-raw/run2/cxb_inventory_switch.py. All 19 BIND groups covered, exact source pins/hashes/wc-l and static/dynamic caller evidence. Historical 27 mixed tests/5948 lines reproduced from d9730967. Candidate and fixed-head reproducibility measurement under run2/f5; no deletion or build. Parent raw owns independent review and final note commit.

**2026-10-27T19:24:34Z**

Final candidate switch-deletions-candidate-final.json SHA256 91e2d900d4df332abb1c1da094ea8009a0f407023e02e20d1da929ca28df4c62. Fixed CT5eba5950/DS7052dba8 regeneration byte-identical; 19 groups,629 unique files,0 unresolved path seeds,30 explicit shared/manual ranges. Historical27/5948 reproduced; currentretention28. Stale verification exit2 correctly reports subsequent committed DS changes and active uncommitted source. Own intermediates removed after measurement, retained scratch13MB. Parent review/selection and final-head remeasure remain.
