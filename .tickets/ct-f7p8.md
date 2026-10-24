---
id: ct-f7p8
status: closed
deps: []
links: [ct-gi01, ct-uov2]
created: 2026-10-22T11:11:42Z
type: bug
priority: 1
assignee: mikewolfd
external-ref: ss-55jg
parent: ct-8kl2
tags: [docspec, committee_explorer, congress_api, data_integrity]
---
# Eliminate silent payload/lines truncation in docspec_views.py and weekly_tables.py and support 1-row large string batches in docspec-rs

Forensic audit of d6bdc1f3 revealed that docspec_views.py:502-505 sliced payload at 250,000 codeunits (corrupting 3 rows in sources-3 and sources-5 into invalid JSON), and weekly_tables.py:379-393 silently truncated lines[:200] when len(payload) > 1,000,000 due to a 40.5 MB binary PDF scrape in senate.json.gz (intelligence.senate.gov).

## Design

1. In docspec-rs (src/storage.rs), update effective_batch_bytes and split_oversized_batch so multi-row flat/string batches exceeding max_batch_bytes are split into compact per-slice buffers (compact_batch_slice), and a 1-row batch with a single large Utf8/Binary cell (such as the 24.4 MB Senate source payload) is admitted as an isolated 1-row batch without failing oversized_batch (while preserving single-row receipt budget tests where explicit).
2. Remove pc.utf8_slice_codeunits truncation from apps/committee_youtube/src/committee_explorer/docspec_views.py and write byte-bounded row groups in parquet.py (_write_sources and _write_table).
3. Remove silent lines[:200] truncation from packages/congress_api/src/congress_api/retention/weekly_tables.py:senate_event_to_row and sanitize binary %PDF- scrapes explicitly in the Senate parser/adapter.

## Acceptance Criteria

1. Zero rows in exported sources-*.parquet or docspec-ws ExportPins have truncated payloads; json.loads(row['payload']) succeeds on all 651,623 source rows.
2. weekly_tables.py stores exact canonical JSON payloads without silent truncation.


## Notes

**2026-10-22T15:38:56Z**

Replaced payload/lines truncation with lossless oversized Arrow RecordBatch slicing in docspec_views.py, weekly_tables.py, and docspec-rs src/storage.rs so 24.45 MB single-row Senate payloads admit and export with zero truncation.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 90 → 90, work 82 → 82.
- Problem: The ticket closed at 5f1402ff (11:39), but the engine fix c949c67 landed at 11:43 and was pinned at 12:02, so it closed before its own dependency existed.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:34
- Covered by: WS12 (ct-uov2), no closing before a dependency lands.
- See docs/reviews/2026-10-24-ticket-audit/README.md
