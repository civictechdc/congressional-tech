---
id: ct-fyid
status: closed
deps: []
links: []
created: 2026-10-20T16:51:57Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, storage, schema-evolution]
---
# Support reading and writing evolved optional Iceberg columns in storage.mapping

tests/test_evolution.py:7-32 adds an optional column (pilot_note) to news.items via Iceberg update_schema(), but only tests reading pre-evolution rows where pilot_note is NULL. storage/mapping.py:140-160 (record_to_row and row_to_record) iterates exclusively over SCHEMA['$defs'][kind]['properties'], silently dropping any evolved optional columns present in the Iceberg table's current schema on both write and read. In addition, mapping._resolve (line 34) only resolves a single $ref hop.

## Design

1. Make mapping._resolve follow chained $ref definitions iteratively.
2. In storage/mapping.py (to_arrow_table / record_to_row and from_arrow_table / row_to_record), preserve optional columns present in the table's authoritative Arrow/Iceberg schema that are not in the base JSON Schema properties (converting Iceberg primitive types appropriately and omitting NULLs on export), and allow Coordinator/Lake to round-trip evolved optional columns when permitted by the table schema.

## Acceptance Criteria

- In tests/test_evolution.py, after adding optional column pilot_note to news.items, writing a row with pilot_note='verified' and reading it back via Lake.read_all and read_release preserves pilot_note='verified' on the new row while omitting pilot_note (NULL) on rows from the earlier release snapshot.


## Notes

**2026-10-20T17:30:52Z**

Chained $ref resolution plus evolved top-level Iceberg columns round-trip by Arrow type in both directions. Coordinator accepts only table-declared extras, and a release validates/exports the evolved column. test_evolution.py: 3 passed.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 85 → 85, work 83 → 83.
- Problem: Evolved columns work only in the PyIceberg oracle; production `DocSpecLake.commit_records` rejects them.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:57
- Covered by: WS8 (ct-d8cf), which deletes the PyIceberg oracle where this works.
- See docs/reviews/2026-10-24-ticket-audit/README.md
