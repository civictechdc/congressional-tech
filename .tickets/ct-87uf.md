---
id: ct-87uf
status: closed
deps: []
links: []
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, raw, d4, backfill, basin, track4]
---
# T4.1 (D4): Full raw-body backfill of meeting_records and appearance_records into Basin Iceberg tables

Parse the ~60k raw HTML/XML bodies (~9 GB in R2: house_xml meeting/witness XML, senate_page hearing HTML cards, and GovInfo mods.xml) via packages/congress_api/src/congress_api/lake/meeting_records.py and appearance_records.py and commit meeting_records and appearance_records as remote Basin Iceberg tables, plus record the D4 uncertainty measurements in docs/plans/phase-2-annex-20261028.md §4.2 (multi-meeting MODS packages, Senate card coverage by committee site, duplicate witness keys per occasion).

## Acceptance Criteria

Full D4 corpus backfill commits meeting_records and appearance_records to remote Basin Iceberg tables and records the §4.2 uncertainty measurements.


## Notes

**2026-10-30T15:36:29Z**

Committed D4 candidate queries (fixing CHRG-* MODS member_path/context_url filter), materialized full-corpus meeting_records (24,304 rows) and appearance_records (62,782 rows including 34,559 mods rows) into native Iceberg tables, and recorded all three Annex §4.2 uncertainty measurements in docs/plans/phase-2-annex-20261028.md.
