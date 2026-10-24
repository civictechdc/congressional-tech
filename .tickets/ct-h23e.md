---
id: ct-h23e
status: closed
deps: []
links: [ct-gi01]
created: 2026-10-22T11:11:42Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-8kl2
tags: [committee_explorer, memory, sqlite, arrow, docspec]
---
# Spill Assembly.records (_SpilledRecords) and stream catalog/query/parquet/docspec projections to stay under 2 GiB RSS (MemoryMax=2G)

While _SpilledSources (assemble.py) and _SpilledIdDict (ids.py) reduced peak RSS on full pipeline-data from 15.3 GB to 8.19 GB, Assembly.records still holds 1,952,933 DomainRecord Pydantic objects in a Python dict (~5.8 GB), and catalog.py, coverage.py, query.py, parquet.py, and docspec_views.py each materialize full dict[(kind, id), DomainRecord] or list[dict] copies in RAM, exceeding .github/workflows/publish-explorer.yml's MemoryMax=2G.

## Design

1. Replace _ValidatedRecords in assemble.py with _SpilledRecords + SpilledRecordSequence backed by a temporary SQLite WITHOUT ROWID B-tree ((kind, id) PRIMARY KEY) with an in-memory seen-key set (~30 MB, avoiding SQLite reads on the 95%+ of keys that do not collide across sources), a compact structural edge index for graph/scope resolution, and a bounded 4,096-entry LRU cache.
2. Update Catalog.check_graph_with (packages/committee_meeting/src/committee_meeting/catalog.py), coverage.build (coverage.py), query.write_queries (query.py), and parquet.write_tables (parquet.py) to use SpilledRecordSequence and stream/release tables per kind rather than materializing dict[(kind, id), DomainRecord] for all 1.95M records in RAM.
3. Extract explorer_meeting_observations in docspec_views.py directly from the projected Arrow/Parquet tables (meetings.parquet, committees.parquet, witnesses.parquet) and SpilledSourceSequence provider metadata in bounded chunks instead of walking 1.95M Pydantic objects a fifth time.

## Acceptance Criteria

1. Full pipeline-data export (2.05M records, 651k sources) completes with peak RSS < 2 GiB (fitting inside publish-explorer.yml MemoryMax=2G).
2. Output Catalog graph validation, coverage metrics, and Parquet browser tables remain bit-for-bit equivalent.


## Notes

**2026-10-22T15:38:56Z**

Verified full pipeline-data export (2,047,546 records, 308,516 source observations) using _ArenaLog (os.write + os.pread), dependency-ordered iter_json_dicts(), compact tuple/list buffers in parquet.py, and paginate=False in query.py: completed in 594.86s with 1,903,984,640 bytes (1.773 GiB / 1,815.8 MiB) peak RSS and 1.745 GiB peak memory footprint (< 2.0 GiB MemoryMax=2G limit, 0 swaps).

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 84 → 84, work 80 → 80.
- Problem: That measurement was local (macOS footprint output), leaves only 11% headroom under 2 GiB, and depended on ct-s9p2 shrinking sources from 651k to 308k.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:35
- Covered by: plan section 4, which keeps the pread arena; see ct-gi01 (reopened under the engine-first rule) for the explorer's custom assembly code.
- See docs/reviews/2026-10-24-ticket-audit/README.md
