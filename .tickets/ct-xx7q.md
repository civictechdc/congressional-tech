---
id: ct-xx7q
status: closed
deps: []
links: []
created: 2026-10-22T18:41:23Z
type: bug
priority: 0
assignee: mikewolfd
parent: ct-4t6s
tags: [parquet, committee-explorer, deduplication, sources, assemble]
---
# Eliminate 74,759 duplicate (provider, identifier) rows and 20,215 unreferenced orphan rows (30.8% of rows) in browser sources.parquet

Raw data audit of sources-1..3.parquet (308,516 rows) revealed 94,974 redundant or unreferenced rows (30.8% of the table):
1. 74,759 Duplicate (provider, identifier) Rows (24.2% of table): 308,516 rows represent only 233,757 unique (provider, identifier.value) pairs:
   - youtube: 67,242 duplicate rows (134,593 rows for 67,351 unique videos — 99.84% of all YouTube videos are stored twice: Row 0 is the pre-enrichment snapshot in issue-history.json.gz cited only by issues.parquet; Row 1 is the current snapshot cited by materials.parquet).
   - congress.gov: 7,298 duplicate rows (28,894 rows for 21,596 unique identifiers), of which 7,324 rows have the exact same byte-for-byte payload (up to 278.8 KB/row), differing only in UUID because SourceRecord.id hashes the file-level input_snapshot_id instead of record-level (provider, scheme, value, payload_sha256).
   - senate.committees: 124 duplicates; gpo-video-matches: 72; curated-recordings: 22.
   - Root cause in assemble.py:987-1166: _dedup_citations (ct-s9p2) returns early when len(citations) <= 1 (line 995) and only compares citations already inside a single issue's tuple; when an historical issue (key not in self.records at line 1102) or single-citation issue cites an old SourceRecord UUID, it is never remapped to the current SourceRecord UUID in self.sources for the same (provider, scheme, value) identity.
2. 20,215 Unreferenced Orphan Rows (6.55% of table): Cross-referencing all source_ids across committees, meetings, materials, witnesses, and issues shows 20,215 rows in sources-1..3.parquet are referenced by ZERO rows in any published table because parquet.py:write_catalog dumps all of catalog.sources (including sources only cited by internal intermediate records like occurrence, material_version, representation, assessment, person, legislative_item).

## Design

1. In assemble.py, derive SourceRecord.id from record-level (provider, identifier.scheme, identifier.value, payload_sha256) (or canonicalize (provider, scheme, value) -> current_sid across self.sources) so unchanged records in updated weekly snapshot files keep a stable UUID.
2. In assemble.py:finish() (lines 1085-1172) and _dedup_citations (lines 987-1047), build an identity map of current sources ((provider, scheme, value) -> current_sid) and rewrite any historical DataIssue citation (including single-citation issues and key not in self.records) whose (provider, scheme, value) exists in self.sources to point to current_sid, retaining old sources in RetainedSources only when that (provider, scheme, value) no longer exists in current sources.
3. In apps/committee_youtube/src/committee_explorer/parquet.py:write_tables / write_catalog, collect the union of all source_ids actually emitted across the 5 published tables (committees, meetings, materials, witnesses, issues) and filter sources.parquet to emit only referenced SourceRecords.

## Acceptance Criteria

1. Zero duplicate (provider, identifier.scheme, identifier.value) rows in sources.parquet unless an historical issue specifically cites a vanished source record.
2. Zero unreferenced orphan rows in sources.parquet (100% of rows in sources.parquet are referenced by at least one row in committees, meetings, materials, witnesses, or issues).
3. Total row count in sources.parquet drops by ~94,974 rows (-30.8%), shrinking into a single sources.parquet file.


## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch syem).
- Grades: proposal 90 → 90, work 83 → 83.
- Problem: Historical issue citations are re-pointed at the current SourceRecord, whose payload may not contain the quoted value, and some e2e tests import no production code.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:115
- Not covered by a plan workstream.
- See docs/reviews/2026-10-24-ticket-audit/README.md
