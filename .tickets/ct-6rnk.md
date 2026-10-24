---
id: ct-6rnk
status: open
deps: []
links: [ct-3ttc, ct-98sm, ct-tw3r]
created: 2026-10-22T11:11:43Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-8kl2
tags: [committee_explorer, docspec, parquet, ci]
---
# Fix resolve_docspec_binary and ExportPolicy schema in docspec_views.py and unify stage/*.parquet with docspec-rs ExportPin outputs

resolve_docspec_binary in docspec_views.py checked DOCSPEC_BIN instead of DOCSPEC_BINARY and defaulted to a stale Wave 1A worktree binary, causing all POST /exports/run calls to hit 422 and fall back to export-compat-*. In addition, export.py wrote Python stage/*.parquet files and hashed them into manifest.json without copying the docspec-rs ExportPin Parquet files back to stage/*.parquet.

## Design

1. Update resolve_docspec_binary in apps/committee_youtube/src/committee_explorer/docspec_views.py to check DOCSPEC_BINARY first, then DOCSPEC_BIN, then QUALIFIED_DOCSPEC_RUNTIME / target/release/docspec (removing stale scratch worktree paths).
2. Ensure build_browser_export_spec emits exact docspec-rs ExportPolicy fields (order_by, page_index_columns, row_group_rows) verified against the 4b29482 binary with zero 422 fallback.
3. In export.py and docspec_views.py, copy the docspec-rs ExportPin Parquet files (pin['object']['path']) back to stage/{name}.parquet and update their partition descriptors (sha256 and byte_size) before writing manifest.json so public/releases/<id>/*.parquet and state/export-pins.json are bit-for-bit identical.

## Acceptance Criteria

1. All ExportPins in state/export-pins.json use extended ExportPolicy (order_by + page_index_columns) with zero export-compat-* fallbacks.
2. Every browser Parquet file in public/releases/<id>/ has the exact same SHA-256 and byte size as its corresponding ExportPin in state/export-pins.json.


## Notes

**2026-10-22T15:38:56Z**

Verified resolve_docspec_binary env/path hierarchy in docspec_views.py and weekly_tables.py, ExportPolicy schema alignment, and bit-for-bit stage/*.parquet == ExportPin sha256/byte_size unification across all 8 browser partitions.

## Audit 2026-10-24

- Verdict: PARTIAL (batch kl2a1aa).
- Grades: proposal 87 → 87, work 73 → 73.
- Problem: Published `stage/*.parquet` are again Python-written, while export-pins.json records the ExportPin digests, so AC2 ("same SHA-256 and byte size") is false on main.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:33
- Status: Reopened. Unmet: the resolver still falls back to unpinned `target/debug` builds and PATH; owner WS3 step 6 (ct-tw3r). Revisit under engine-first rule: AC2 (published `stage/*.parquet` equal the ExportPin outputs) was reverted by `f2fea711`, so the explorer publishes Python-written tables again. No plan workstream owns the explorer; linked to the epic ct-98sm.
- See docs/reviews/2026-10-24-ticket-audit/README.md
