---
id: ct-aory
status: closed
deps: []
links: []
created: 2026-11-25T13:50:09Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-lwxs
---
# Contribute RefSpec 1.4+ agency aliases for remaining federal sub-units (GPO, NIH institutes, Fed banks, CSB)

Follow-up from ct-w34j (PR #243, sealed RefSpec 1.3 yielded 87.27% of non-empty House XML Government - Federal rows). Follow REF-075 D4/D5 (read statutory/agency citations, owner-adjudicated batch) in RefSpec to add the ~213 remaining unaliased federal sub-units/institutes (e.g., Government Printing Office, regional Federal Reserve banks, NIH institutes, U.S. Chemical Safety Board, Air/Army National Guard), cut sealed RefSpec 1.4+, and update model/jobs/refspec/refspec.json to push House XML federal coverage >=90%.

## Completion Notes (2026-11-25)

- **Upstream RefSpec:** Added 94 verified REF-075 D4/D5 statutory/official federal sub-unit aliases and cut sealed RefSpec `1.4` (`schemaVersion: "1.4"`, 157 aliases, `view-manifest.json` `sha256:c89935de...`) in `Formspec-Labs/RefSpec#2` (merged `96c62e00`, `378 passed, 11 deselected`).
- **Congressional-Tech Integration:** Vendored RefSpec `1.4` and updated pinned model/publish manifests in PR #251 (merged `586cbd43`).
- **Coverage & Raw Check:** Real `0e7084cd` build + `scripts/measure/org_agency_raw_check.py` lifted `house_xml` `Government - Federal` non-empty coverage from `87.27%` to `90.31%` (`2,993/3,314`, `41,015` links), with `0/100` wrong, `0` state leaks, `0` unread, and `planted_flagged=true`. Durable receipts archived at `.cache/archive-release/investigations/ct-aory-refspec-14-20261125/`.

