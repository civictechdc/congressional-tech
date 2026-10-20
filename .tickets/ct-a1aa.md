---
id: ct-a1aa
status: closed
deps: [ct-owh2]
links: []
created: 2026-10-20T16:50:54Z
type: epic
priority: 1
assignee: mikewolfd
tags: [news-lake, review, quality]
---
# Remediate news_lake adversarial review findings and qualify slices 1-6

Address all findings, defects, and suggestions from the CS 300-level adversarial review of packages/news_lake across contract validation (Slice 1), Iceberg storage and recovery (Slice 2), provider adapters and cursors (Slices 3 & 5), identity resolution and linking (Slice 4), and analytical views (Slice 6).

## Design

Keep packages/news-lake/docs/ as the read-only contract authority. Fix each slice owner in packages/news_lake/src/news_lake/ without duplicating schema rules: atomic/monotonic upserts and fenced control-store transactions in storage/, true DAG reachability and casefold-safe word-boundary linking in identity/, complete C2/C6/C7 checks in contract/, consistent outlet/date/redirect handling in adapters/, and accurate span/decision/date semantics in analysis/.

## Acceptance Criteria

- All 11 child remediation tickets are completed and verified with targeted regression tests in packages/news_lake/tests/.
- Crash recovery converges across all fault points including mid-upsert (between delete and append) and in-flight release states.
- Contract validation (validate_shape and check_corpus) enforces finite floats, C6 decision-graph invariants, C7 input acyclicity, unique checkpoint connector keys, and credential redaction.
- README.md and module docstrings accurately reflect implemented guarantees with no overstated claims.


## Notes

**2026-10-20T17:16:20Z**

Parallel implementation underway. Contract hardening (ct-r33r) complete: 73 tests pass. Labels/export (ct-5yof), analysis views/selection (ct-fmgi), and schema mapping (ct-fyid) reported complete. Waiting on identity, adapters, and storage/recovery agents before integration.

**2026-10-20T17:16:37Z**

Adapters (ct-qcf5), analysis views (ct-fmgi), labels/export (ct-5yof), mapping (ct-fyid), and contract (ct-r33r) are implemented. Remaining work: identity agent fixture/span corrections and storage/recovery agent, then full-suite integration.

**2026-10-20T17:31:00Z**

Implemented in full. 11 remediation tickets plus the final audit (ct-owh2) are closed. Final verification: 281 news_lake tests passed; packet checker passed; schema copy unchanged; README seams audited against implementation.

**2026-10-20T18:09:49Z**

All 10 follow-up findings from the semi-formal code review addressed and verified (290 passed in 38.97s).

**2026-10-20T18:28:05Z**

Implemented all 4 final architectural recommendations (293 passed).
